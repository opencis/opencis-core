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
        port: int = 8300,
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

    async def _process_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """
        Main request/response loop.

        For each incoming SMBus+MCTP frame:
          1. Parse SMBus header + MCTP header + CCI message
          2. Extract (opcode, payload) from CCI message
          3. Forward to FM CLI path via send_raw_cci()
          4. Wrap response in SMBus+MCTP response frame
          5. Write response back to client (SMBus Master reads it)
        """
        while True:
            # ── Step 1: Read one full SMBus+MCTP frame ─────────────────
            raw_frame = await read_smbus_frame(reader)

            # ── Step 2: Parse the frame ────────────────────────────────
            try:
                req = SmbusMctpRequest.parse(
                    raw_frame,
                    verify_pec=self._verify_pec,
                )
            except ValueError as exc:
                logger.warning(self._create_message(
                    f"Bad SMBus+MCTP frame ({len(raw_frame)} bytes): {exc}"
                ))
                # Skip malformed frame — keep connection open
                continue

            opcode_str = get_opcode_string(req.cci_opcode)
            logger.debug(self._create_message(
                f"RX SMBus src=0x{req.src_slave_addr:02X} "
                f"opcode={opcode_str}(0x{req.cci_opcode:04X}) "
                f"cci_tag={req.cci_tag} "
                f"pec={'OK' if req.pec_valid else 'BAD'} "
                f"payload={len(req.cci_payload)}B"
            ))

            # ── Step 3: Forward CCI to FM CLI path ────────────────────
            return_code, response_payload, is_background = \
                await self._forward_to_cli(req.cci_opcode, req.cci_payload)

            logger.debug(self._create_message(
                f"TX SMBus opcode={opcode_str} "
                f"rc={CCI_RETURN_CODE(return_code).name} "
                f"bg={is_background} "
                f"resp={len(response_payload)}B"
            ))

            # ── Step 4: Build SMBus+MCTP response frame ────────────────
            resp_frame = build_smbus_mctp_response(
                request=req,
                return_code=int(return_code),
                response_payload=response_payload,
                is_background=is_background,
                fm_i2c_addr=self._fm_i2c_addr,
                compute_pec=True,
            )

            # ── Step 5: Send to client (SMBus Master reads this) ───────
            writer.write(resp_frame)
            await writer.drain()

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
