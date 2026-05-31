"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.

FmSmbusMctpServer — SMBus+MCTP CCI server for CxlFabricManager
==============================================================

Replaces the previous FmMctpCciServer (CciPayloadPacket format) with
a standard MCTP-over-SMBus (DMTF DSP0237) framed server.

Accepts connections from QEMU SMBus Slave devices.
Sends responses to QEMU SMBus Master devices.

Protocol per connection:
  QEMU SMBus Slave  →  [SMBus hdr | MCTP hdr | msg_type | CCI msg | PEC]  →  FM port
  FM extracts CCI opcode + payload
  FM calls MctpCciApiClient.send_raw_cci(opcode, payload)  →  Switch
  Switch returns (return_code, response_bytes, is_background)
  FM wraps: [byte_count | FM addr | MCTP hdr | msg_type | CCI resp | PEC]
  FM sends wrapped response  →  QEMU SMBus Master

Packet format reference: smbus_mctp_framing.py
CCI field layout reference: opencis/cxl/transport/fields.py
"""

import asyncio
from asyncio import create_task, gather
from typing import Optional, TYPE_CHECKING

from opencis.util.component import RunnableComponent
from opencis.util.logger import logger
from opencis.util.server import ServerComponent
from opencis.cxl.cci.common import CCI_RETURN_CODE, get_opcode_string
from opencis.cxl.component.mctp.smbus_mctp_framing import (
    SmbusMctpRequest,
    build_smbus_mctp_response,
    read_smbus_frame,
    SMBUS_MCTP_COMMAND_CODE,
)

if TYPE_CHECKING:
    from opencis.cxl.component.mctp.mctp_cci_api_client import MctpCciApiClient


class FmSmbusMctpServer(RunnableComponent):
    """
    Fabric Manager SMBus+MCTP CCI server.

    Listens on a TCP port (default 8300).
    Accepts connections from QEMU SMBus Slave.
    Sends CCI responses in SMBus+MCTP format to QEMU SMBus Master
    (on the same connection — full-duplex).

    Frame format: DMTF DSP0237 (MCTP over SMBus/I2C).

    Zero switch-programming logic here — all CCI processing is done
    by the switch via MctpCciApiClient.send_raw_cci().
    """

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 8301,
        mctp_client: Optional["MctpCciApiClient"] = None,
        fm_i2c_addr: int = 0x10,
        verify_pec: bool = False,
        label: Optional[str] = None,
    ):
        """
        Args:
            host:         bind address
            port:         TCP port (default 8300)
            mctp_client:  FM CLI path (MctpCciApiClient). When None, returns
                          UNSUPPORTED for all commands (offline/test mode).
            fm_i2c_addr:  7-bit I2C address of the FM (used in response frames)
            verify_pec:   if True, drop packets with bad CRC-8 PEC
        """
        super().__init__(label or "FmSmbusMctpServer")
        self._host         = host
        self._port         = port
        self._mctp_client  = mctp_client
        self._fm_i2c_addr  = fm_i2c_addr
        self._verify_pec   = verify_pec

        self._server = ServerComponent(
            handle_client=self._handle_client,
            host=self._host,
            port=self._port,
            stop_callback=self._on_server_stop,
            label="FmSmbusMctpServer",
        )

    # ── Public helpers ─────────────────────────────────────────────────────

    def get_port(self) -> int:
        return self._server.get_port()

    def bind_mctp_client(self, client: "MctpCciApiClient") -> None:
        """
        Late-bind the FM CLI api_client after the switch connects on port 8100.
        Call this once MctpCciApiClient is running.
        """
        self._mctp_client = client
        logger.info(self._create_message(
            "MctpCciApiClient bound — port 8300 (SMBus+MCTP) bridges to FM CLI"
        ))

    # ── Per-connection handler ─────────────────────────────────────────────

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        peer = writer.get_extra_info("peername")
        logger.info(self._create_message(f"SMBus client connected: {peer}"))

        try:
            await self._process_client(reader, writer)
        except asyncio.IncompleteReadError:
            logger.info(self._create_message(f"SMBus client disconnected: {peer}"))
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.warning(self._create_message(
                f"SMBus client {peer} error: {exc}"
            ))
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass
            logger.info(self._create_message(f"SMBus session closed: {peer}"))

    # ── Packet printer ─────────────────────────────────────────────────────

    @staticmethod
    def _hex_dump(data: bytes, indent: str = "    ") -> str:
        """Format bytes as a hex dump with ASCII side-panel."""
        if not data:
            return f"{indent}(empty)"
        lines = []
        for i in range(0, len(data), 16):
            chunk = data[i:i + 16]
            hex_part = " ".join(f"{b:02X}" for b in chunk)
            asc_part = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
            lines.append(f"{indent}{i:04X}  {hex_part:<47}  |{asc_part}|")
        return "\n".join(lines)

    def _print_rx_packet(self, raw_frame: bytes, req: "SmbusMctpRequest | None",
                         parse_error: str = "") -> None:
        """
        Print full packet breakdown to stdout BEFORE any processing.
        Called for every received frame — valid or invalid.
        """
        sep = "═" * 60
        print(f"\n\033[1m\033[96m{sep}")
        print(f"  SMBus+MCTP RX  [{len(raw_frame)} bytes]  port {self._port}")
        print(f"{sep}\033[0m")

        # Raw hex dump — always shown
        print("\033[2m  Raw bytes:\033[0m")
        print(self._hex_dump(raw_frame))

        if parse_error:
            print(f"\033[91m  Parse ERROR: {parse_error}\033[0m")
            print(f"\033[1m{'─' * 60}\033[0m\n")
            return

        # ── SMBus header ──────────────────────────────────────────────
        print("\033[93m  ── SMBus Header ──────────────────────────────────────\033[0m")
        print(f"    dest_slave_addr : 0x{req.dest_slave_addr:02X}  "
              f"(i2c addr 0x{req.dest_slave_addr >> 1:02X}, "
              f"dir={'WRITE' if not (req.dest_slave_addr & 1) else 'READ'})")
        print(f"    command_code    : 0x{req.command_code:02X}  "
              f"({'MCTP' if req.command_code == 0x0F else 'UNKNOWN'})")
        print(f"    byte_count      : {req.byte_count}")
        print(f"    src_slave_addr  : 0x{req.src_slave_addr:02X}  "
              f"(i2c addr 0x{req.src_slave_addr >> 1:02X})")

        # ── MCTP transport header ─────────────────────────────────────
        print("\033[93m  ── MCTP Transport Header ─────────────────────────────\033[0m")
        print(f"    hdr_ver         : 0x{req.hdr_ver:02X}")
        print(f"    dest_eid        : 0x{req.dest_eid:02X}")
        print(f"    src_eid         : 0x{req.src_eid:02X}")
        print(f"    SOM             : {req.som}")
        print(f"    EOM             : {req.eom}")
        print(f"    pkt_seq         : {req.pkt_seq}")
        print(f"    TO (tag owner)  : {req.to}")
        print(f"    msg_tag         : {req.msg_tag}")

        # ── MCTP message type ─────────────────────────────────────────
        print("\033[93m  ── MCTP Message Type ─────────────────────────────────\033[0m")
        msg_type_name = {
            0x00: "MCTP_CONTROL",
            0x05: "NCSI",
            0x06: "ETHERNET",
            0x07: "NVME_MI",
            0x7E: "CXL_FM_API",
            0x7F: "VENDOR_DEFINED",
        }.get(req.msg_type, f"UNKNOWN(0x{req.msg_type:02X})")
        print(f"    IC (integrity)  : {req.ic}")
        print(f"    msg_type        : 0x{req.msg_type:02X}  ({msg_type_name})")

        # ── CCI message header ────────────────────────────────────────
        print("\033[93m  ── CCI Message Header ────────────────────────────────\033[0m")
        opcode_str = get_opcode_string(req.cci_opcode)
        cat_name = {0: "REQUEST", 1: "RESPONSE"}.get(0, "REQUEST")
        print(f"    message_category: 0  ({cat_name})")
        print(f"    message_tag     : {req.cci_tag}")
        print(f"    command_opcode  : \033[1m0x{req.cci_opcode:04X}\033[0m  ({opcode_str})")
        print(f"    payload_length  : {len(req.cci_payload)} bytes")

        # ── PEC ───────────────────────────────────────────────────────
        pec_status = "\033[92mOK\033[0m" if req.pec_valid else "\033[91mBAD\033[0m"
        print("\033[93m  ── PEC (CRC-8) ───────────────────────────────────────\033[0m")
        print(f"    pec             : 0x{req.pec:02X}  [{pec_status}]")

        # ── CCI payload hex dump ──────────────────────────────────────
        if req.cci_payload:
            print("\033[93m  ── CCI Payload ───────────────────────────────────────\033[0m")
            print(self._hex_dump(req.cci_payload))

        print(f"\033[1m{'─' * 60}\033[0m\n")

    # ── Main client loop ───────────────────────────────────────────────────

    async def _process_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """
        Main request/response loop.

        For each incoming SMBus+MCTP frame:
          1. Print the full packet breakdown (BEFORE any processing)
          2. Parse SMBus header + MCTP header + CCI message
          3. Forward to FM CLI path via send_raw_cci()
          4. Wrap response in SMBus+MCTP response frame
          5. Write response back to client (SMBus Master reads it)
        """
        while True:
            # ── Step 1: Read one full SMBus+MCTP frame ─────────────────
            raw_frame = await read_smbus_frame(reader)

            # ── Step 2: Parse the frame ─────────────────────────────────
            try:
                req = SmbusMctpRequest.parse(
                    raw_frame,
                    verify_pec=self._verify_pec,
                )
            except ValueError as exc:
                # Print the bad packet BEFORE discarding it
                self._print_rx_packet(raw_frame, None, parse_error=str(exc))
                logger.warning(self._create_message(
                    f"Bad SMBus+MCTP frame ({len(raw_frame)} bytes): {exc}"
                ))
                # Build and send an INVALID_INPUT error response
                err_frame = self._build_error_frame(raw_frame)
                if err_frame:
                    writer.write(err_frame)
                    await writer.drain()
                continue

            # ── Step 3: Print full packet breakdown (before execution) ──
            self._print_rx_packet(raw_frame, req)

            opcode_str = get_opcode_string(req.cci_opcode)

            # ── Step 4: Forward CCI to FM CLI path ─────────────────────
            return_code, response_payload, is_background = \
                await self._forward_to_cli(req.cci_opcode, req.cci_payload)

            logger.debug(self._create_message(
                f"TX SMBus opcode={opcode_str} "
                f"rc={CCI_RETURN_CODE(return_code).name} "
                f"bg={is_background} "
                f"resp={len(response_payload)}B"
            ))

            # ── Step 5: Build SMBus+MCTP response frame ─────────────────
            resp_frame = build_smbus_mctp_response(
                request=req,
                return_code=int(return_code),
                response_payload=response_payload,
                is_background=is_background,
                fm_i2c_addr=self._fm_i2c_addr,
                compute_pec=True,
            )

            # Print response summary
            rc_color = "\033[92m" if return_code == 0 else "\033[93m" if return_code == 1 else "\033[91m"
            print(f"  \033[2m→ TX response:\033[0m opcode=0x{req.cci_opcode:04X} "
                  f"rc={rc_color}{CCI_RETURN_CODE(return_code).name}\033[0m "
                  f"bg={is_background} payload={len(response_payload)}B "
                  f"frame={len(resp_frame)}B\n")

            # ── Step 6: Send to client (SMBus Master reads this) ─────────
            writer.write(resp_frame)
            await writer.drain()

    # ── Error frame builder ────────────────────────────────────────────────

    def _build_error_frame(self, raw_frame: bytes) -> bytes:
        """
        Build a best-effort SMBus+MCTP error response (INVALID_INPUT)
        from a raw frame that failed to parse.

        Extracts whatever header fields are readable. Returns empty bytes
        if the frame is too short to build any response.
        """
        from opencis.cxl.component.mctp.smbus_mctp_framing import (
            SMBUS_REQ_HDR_SIZE, MCTP_HDR_VERSION, crc8_smbus,
        )
        if len(raw_frame) < SMBUS_REQ_HDR_SIZE:
            return b""  # too short — cannot form any response

        # Extract what we can
        src_slave_addr  = raw_frame[3]   # device addr | 1
        dest_eid        = raw_frame[5]   # FM EID from request
        src_eid         = raw_frame[6]   # device EID
        flags           = raw_frame[7]
        msg_tag         = flags & 0x7
        msg_type_byte   = raw_frame[8]
        fm_src          = (self._fm_i2c_addr << 1) | 0x01

        # Minimal CCI error header: RESPONSE, tag=0, opcode=0, INVALID_INPUT
        cci_hdr = bytearray(12)
        cci_hdr[0]  = 0x01                                 # RESPONSE
        cci_hdr[8]  = CCI_RETURN_CODE.INVALID_INPUT & 0xFF
        cci_hdr[9]  = (CCI_RETURN_CODE.INVALID_INPUT >> 8) & 0xFF

        resp_flags = 0xC0 | (msg_tag & 0x7)               # SOM|EOM, TO=0
        body = bytes([fm_src, MCTP_HDR_VERSION,
                      src_eid, dest_eid,
                      resp_flags, msg_type_byte]) + bytes(cci_hdr)
        frame = bytes([len(body)]) + body
        frame += bytes([crc8_smbus(frame)])
        return frame

    # ── FM CLI forwarding ──────────────────────────────────────────────────

    async def _forward_to_cli(
        self,
        opcode: int,
        payload: bytes,
    ) -> "tuple[CCI_RETURN_CODE, bytes, bool]":
        """
        Forward CCI command to FM CLI path via MctpCciApiClient.send_raw_cci().

        Returns (return_code, response_bytes, is_background).
        If no client is bound, returns UNSUPPORTED.
        """
        if self._mctp_client is None:
            logger.warning(self._create_message(
                f"No mctp_client bound — UNSUPPORTED for opcode 0x{opcode:04X}"
            ))
            return (CCI_RETURN_CODE.UNSUPPORTED, b"", False)

        try:
            return await self._mctp_client.send_raw_cci(opcode, payload)
        except Exception as exc:
            logger.error(self._create_message(
                f"FM CLI path error for opcode 0x{opcode:04X}: {exc}"
            ))
            return (CCI_RETURN_CODE.INTERNAL_ERROR, b"", False)

    # ── Lifecycle ──────────────────────────────────────────────────────────

    async def _on_server_stop(self) -> None:
        logger.info(self._create_message("TCP server stopped"))

    async def _run(self) -> None:
        server_task = create_task(self._server.run())
        await self._server.wait_for_ready()
        self._port = self._server.get_port()
        logger.info(self._create_message(
            f"FM SMBus+MCTP CCI server listening on "
            f"{self._host}:{self._port} (DSP0237 framing)"
        ))
        await self._change_status_to_running()
        await gather(server_task)

    async def _stop(self) -> None:
        await self._server.stop()
