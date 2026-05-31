"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.

fm_smbus_dual_port_server.py -- Dual-port SMBus+MCTP CCI Server
================================================================

Architecture
------------

  QEMU SMBus Slave  --TCP:8301-->  Request Server
                                       | depacketize SMBus+MCTP
                                       | extract CCI opcode + payload
                                       | send_raw_cci(opcode, payload)
                                       | build SMBus+MCTP response
                                       | push to asyncio.Queue
                                   Response Server  --TCP:8302-->  QEMU SMBus Master
                                       + drains Queue, writes to Master socket

Key design decisions
--------------------
* Two separate TCP listener sockets so SMBus Slave and Master can be
  independent QEMU devices that connect independently.
* A shared asyncio.Queue decouples the two servers: the Request Server
  puts completed response frames in the queue; the Response Server blocks
  on queue.get() and forwards each frame to the connected Master.
* Every received frame is printed (hex dump + all fields) BEFORE execution.
* Malformed frames get an INVALID_INPUT SMBus error response queued to Master.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Optional

from opencis.cxl.cci.common import CCI_RETURN_CODE, get_opcode_string
from opencis.cxl.component.mctp.smbus_mctp_framing import (
    MCTP_HDR_VERSION,
    SMBUS_REQ_HDR_SIZE,
    SmbusMctpRequest,
    build_smbus_mctp_response,
    crc8_smbus,
    read_smbus_frame,
)
from opencis.util.component import RunnableComponent
from opencis.util.logger import logger

if TYPE_CHECKING:
    from opencis.cxl.component.mctp.mctp_cci_api_client import MctpCciApiClient


class FmSmbusDualPortServer(RunnableComponent):
    """
    Dual-port SMBus+MCTP CCI Server (DMTF DSP0237).

    Port ``req_port``  (default 8301):
        Listens for SMBus+MCTP request frames from the QEMU SMBus Slave.
        Depacketizes frame -> extracts CCI opcode + payload ->
        forwards to the FM CLI path (same MctpCciApiClient as port 8200) ->
        builds SMBus+MCTP response frame -> puts it in the shared response queue.

    Port ``resp_port`` (default 8302):
        Listens for a connection from the QEMU SMBus Master.
        Drains the shared response queue and writes each response frame to
        the connected Master socket.

    Usage
    -----
    ::

        # Terminal 1 - start FM + Switch
        python run_pbr_env.py

        # Terminal 2 - test client (sends on 8301, reads on 8302)
        python tests/test_smbus_dual_port_client.py
    """

    def __init__(
        self,
        host: str = "0.0.0.0",
        req_port: int = 8301,
        resp_port: int = 8302,
        mctp_client: Optional["MctpCciApiClient"] = None,
        fm_i2c_addr: int = 0x10,
        verify_pec: bool = False,
    ) -> None:
        super().__init__()
        self._host = host
        self._req_port = req_port
        self._resp_port = resp_port
        self._mctp_client = mctp_client
        self._fm_i2c_addr = fm_i2c_addr
        self._verify_pec = verify_pec

        # NOTE: asyncio primitives MUST be created inside the running event loop,
        # i.e. inside _run(), NOT here in __init__.
        # Creating them in __init__ (before the loop starts) assigns them to the
        # wrong loop on Python 3.10+ and causes wait() to never unblock.
        self._response_queue: asyncio.Queue[bytes] | None = None
        self._req_ready:  asyncio.Event | None = None
        self._resp_ready: asyncio.Event | None = None

        # asyncio server handles (set in _run)
        self._req_server_handle:  asyncio.AbstractServer | None = None
        self._resp_server_handle: asyncio.AbstractServer | None = None

        print(
            f"[FmSmbusDualPortServer] Request  port : {req_port}  "
            f"<- QEMU SMBus Slave (DSP0237 request frames)"
        )
        print(
            f"[FmSmbusDualPortServer] Response port : {resp_port}  "
            f"-> QEMU SMBus Master (DSP0237 response frames)"
        )

    # -- Bind helpers ----------------------------------------------------------

    def bind_mctp_client(self, client: "MctpCciApiClient") -> None:
        """Late-bind the MctpCciApiClient after switch connects."""
        self._mctp_client = client

    def get_req_port(self) -> int:
        """Return actual bound request port (works with port=0 for tests)."""
        if self._req_server_handle:
            return self._req_server_handle.sockets[0].getsockname()[1]
        return self._req_port

    def get_resp_port(self) -> int:
        """Return actual bound response port (works with port=0 for tests)."""
        if self._resp_server_handle:
            return self._resp_server_handle.sockets[0].getsockname()[1]
        return self._resp_port

    # -- RunnableComponent lifecycle ------------------------------------------

    async def _run(self) -> None:
        # -- FIX: create asyncio primitives INSIDE the running event loop ------
        # asyncio.Event() and asyncio.Queue() must be created here, not in
        # __init__, so they are bound to the correct loop.  Creating them in
        # __init__ (synchronously, before the loop starts) causes wait() to
        # silently block forever on some Python / OS combinations.
        self._response_queue = asyncio.Queue()
        self._req_ready      = asyncio.Event()
        self._resp_ready     = asyncio.Event()

        self._req_server_handle = await asyncio.start_server(
            self._handle_slave,
            self._host,
            self._req_port,
        )
        self._resp_server_handle = await asyncio.start_server(
            self._handle_master,
            self._host,
            self._resp_port,
        )

        # Update stored ports to actual bound ports (important when port=0)
        self._req_port  = self._req_server_handle.sockets[0].getsockname()[1]
        self._resp_port = self._resp_server_handle.sockets[0].getsockname()[1]

        self._req_ready.set()
        self._resp_ready.set()
        await self._change_status_to_running()

        logger.info(self._create_message(
            f"Request  server listening on {self._host}:{self._req_port}"
        ))
        logger.info(self._create_message(
            f"Response server listening on {self._host}:{self._resp_port}"
        ))

        async with self._req_server_handle, self._resp_server_handle:
            await asyncio.gather(
                self._req_server_handle.serve_forever(),
                self._resp_server_handle.serve_forever(),
            )

    async def _stop(self) -> None:
        if self._req_server_handle:
            self._req_server_handle.close()
            await self._req_server_handle.wait_closed()
        if self._resp_server_handle:
            self._resp_server_handle.close()
            await self._resp_server_handle.wait_closed()
        # Unblock any waiting response server with shutdown sentinel
        if self._response_queue:
            await self._response_queue.put(b"")

    async def wait_for_ready(self) -> None:
        # Spin-wait until _run() has created the events (handles the edge case
        # where wait_for_ready is called before _run has been scheduled).
        while self._req_ready is None or self._resp_ready is None:
            await asyncio.sleep(0.01)
        await self._req_ready.wait()
        await self._resp_ready.wait()

    # -- Request Server (port 8301) --------------------------------------------

    async def _handle_slave(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Called for each SMBus Slave connection on port 8301."""
        peer = writer.get_extra_info("peername", "unknown")
        logger.info(self._create_message(f"SMBus Slave connected: {peer}"))
        try:
            await self._process_slave(reader, writer)
        except asyncio.IncompleteReadError:
            logger.info(self._create_message(f"SMBus Slave disconnected: {peer}"))
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.warning(self._create_message(f"SMBus Slave {peer} error: {exc}"))
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass
            logger.info(self._create_message(f"SMBus Slave session closed: {peer}"))

    async def _process_slave(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """
        Main loop for the Request Server.

        For each incoming SMBus+MCTP frame:
          1. Read exactly one complete frame (length-delimited)
          2. Print full packet breakdown (BEFORE any processing)
          3. Parse SMBus header + MCTP header + CCI message
          4. Forward CCI to FM CLI path via send_raw_cci()
          5. Build SMBus+MCTP response frame
          6. Push response frame to shared queue -> Response Server sends it
        """
        while True:
            # -- Step 1: Read one complete SMBus+MCTP frame ---------------
            raw_frame = await read_smbus_frame(reader)

            # -- Step 2: Parse --------------------------------------------
            try:
                req = SmbusMctpRequest.parse(raw_frame, verify_pec=self._verify_pec)
            except ValueError as exc:
                self._print_rx_packet(raw_frame, None, parse_error=str(exc))
                logger.warning(self._create_message(
                    f"Bad SMBus+MCTP frame ({len(raw_frame)} bytes): {exc}"
                ))
                err_frame = self._build_error_frame(raw_frame)
                if err_frame:
                    await self._response_queue.put(err_frame)
                continue

            # -- Step 3: Print (BEFORE execution) -------------------------
            self._print_rx_packet(raw_frame, req)

            opcode_str = get_opcode_string(req.cci_opcode)

            # -- Step 4: Forward CCI to FM CLI path -----------------------
            return_code, response_payload, is_background = \
                await self._forward_to_cli(req.cci_opcode, req.cci_payload)

            logger.debug(self._create_message(
                f"CCI done: opcode={opcode_str} "
                f"rc={CCI_RETURN_CODE(return_code).name} "
                f"bg={is_background} resp={len(response_payload)}B"
            ))

            # -- Step 5: Build DSP0237 response frame ---------------------
            resp_frame = build_smbus_mctp_response(
                request=req,
                return_code=int(return_code),
                response_payload=response_payload,
                is_background=is_background,
                fm_i2c_addr=self._fm_i2c_addr,
                compute_pec=True,
            )

            rc_color = (
                "\033[92m" if return_code == 0
                else "\033[93m" if return_code == 1
                else "\033[91m"
            )
            print(
                f"  \033[2m-> Queued response:\033[0m "
                f"opcode=0x{req.cci_opcode:04X} "
                f"rc={rc_color}{CCI_RETURN_CODE(return_code).name}\033[0m "
                f"bg={is_background} "
                f"payload={len(response_payload)}B "
                f"frame={len(resp_frame)}B\n"
            )

            # -- Step 6: Push to response queue then YIELD ---------------------
            # The 'await asyncio.sleep(0)' explicitly yields control to the event
            # loop after putting the frame in the queue.  Without this yield,
            # the _handle_master coroutine may not get scheduled until _process_slave
            # loops back to 'await read_smbus_frame()'.  On a slow/loaded VDI the
            # event loop may take many milliseconds to reschedule, causing the
            # test's receive timeout to fire before the frame reaches the Master.
            await self._response_queue.put(resp_frame)
            await asyncio.sleep(0)   # yield -> let _process_master drain the queue

    # -- Response Server (port 8302) -------------------------------------------

    async def _handle_master(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Called for each SMBus Master connection on port 8302."""
        peer = writer.get_extra_info("peername", "unknown")
        logger.info(self._create_message(f"SMBus Master connected: {peer}"))
        try:
            await self._process_master(writer)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.warning(self._create_message(f"SMBus Master {peer} error: {exc}"))
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass
            logger.info(self._create_message(f"SMBus Master session closed: {peer}"))

    async def _process_master(self, writer: asyncio.StreamWriter) -> None:
        """
        Main loop for the Response Server.

        Blocks on the shared response queue. Each frame popped from the
        queue is a complete DSP0237 response frame ready to be sent.
        An empty bytes sentinel (b"") signals shutdown.
        """
        while True:
            resp_frame = await self._response_queue.get()
            if not resp_frame:   # shutdown sentinel
                break
            writer.write(resp_frame)
            await writer.drain()
            logger.debug(self._create_message(
                f"Sent {len(resp_frame)}-byte response to SMBus Master"
            ))

    # -- FM CLI forwarding -----------------------------------------------------

    async def _forward_to_cli(
        self,
        opcode: int,
        payload: bytes,
    ) -> tuple[int, bytes, bool]:
        """
        Forward a CCI command to the FM CLI path (MctpCciApiClient).

        Returns (return_code, response_payload, is_background).
        Returns UNSUPPORTED if no mctp_client is bound yet.
        """
        if self._mctp_client is None:
            logger.warning(self._create_message(
                "No MctpCciApiClient bound -- returning UNSUPPORTED"
            ))
            return int(CCI_RETURN_CODE.UNSUPPORTED), b"", False

        try:
            return await self._mctp_client.send_raw_cci(opcode, payload)
        except Exception as exc:
            logger.error(self._create_message(
                f"send_raw_cci failed: opcode=0x{opcode:04X} error={exc}"
            ))
            return int(CCI_RETURN_CODE.INTERNAL_ERROR), b"", False

    # -- Packet printer --------------------------------------------------------

    @staticmethod
    def _hex_dump(data: bytes, indent: str = "    ") -> str:
        if not data:
            return f"{indent}(empty)"
        lines = []
        for i in range(0, len(data), 16):
            chunk = data[i:i + 16]
            hex_part = " ".join(f"{b:02X}" for b in chunk)
            asc_part = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
            lines.append(f"{indent}{i:04X}  {hex_part:<47}  |{asc_part}|")
        return "\n".join(lines)

    def _print_rx_packet(
        self,
        raw_frame: bytes,
        req: Optional[SmbusMctpRequest],
        parse_error: str = "",
    ) -> None:
        """Print full packet breakdown to stdout BEFORE any processing."""
        sep = "=" * 62
        print(f"\n\033[1m\033[96m{sep}")
        print(f"  SMBus+MCTP RX  [{len(raw_frame)} bytes]  req-port {self._req_port}")
        print(f"{sep}\033[0m")
        print("\033[2m  Raw bytes:\033[0m")
        print(self._hex_dump(raw_frame))

        if parse_error:
            print(f"\033[91m  Parse ERROR: {parse_error}\033[0m")
            print(f"\033[1m{'-' * 62}\033[0m\n")
            return

        print("\033[93m  -- SMBus Header -----------------------------------------\033[0m")
        print(f"    dest_slave_addr : 0x{req.dest_slave_addr:02X}  "
              f"(i2c 0x{req.dest_slave_addr >> 1:02X}, "
              f"dir={'WRITE' if not (req.dest_slave_addr & 1) else 'READ'})")
        print(f"    command_code    : 0x{req.command_code:02X}  "
              f"({'MCTP' if req.command_code == 0x0F else 'UNKNOWN'})")
        print(f"    byte_count      : {req.byte_count}")
        print(f"    src_slave_addr  : 0x{req.src_slave_addr:02X}  "
              f"(i2c 0x{req.src_slave_addr >> 1:02X})")

        print("\033[93m  -- MCTP Transport Header --------------------------------\033[0m")
        print(f"    hdr_ver    : 0x{req.hdr_ver:02X}")
        print(f"    dest_eid   : 0x{req.dest_eid:02X}  (FM)")
        print(f"    src_eid    : 0x{req.src_eid:02X}  (device)")
        print(f"    SOM        : {req.som}  EOM: {req.eom}  "
              f"pkt_seq: {req.pkt_seq}  TO: {req.to}  msg_tag: {req.msg_tag}")

        msg_type_name = {
            0x00: "MCTP_CONTROL", 0x7E: "CXL_FM_API", 0x7F: "VENDOR_DEFINED",
        }.get(req.msg_type, f"UNKNOWN(0x{req.msg_type:02X})")
        print("\033[93m  -- MCTP Message / CCI Header ----------------------------\033[0m")
        print(f"    IC         : {req.ic}  msg_type: 0x{req.msg_type:02X} ({msg_type_name})")
        opcode_str = get_opcode_string(req.cci_opcode)
        print(f"    opcode     : \033[1m0x{req.cci_opcode:04X}\033[0m  ({opcode_str})")
        print(f"    cci_tag    : {req.cci_tag}")
        print(f"    payload    : {len(req.cci_payload)} bytes")

        pec_str = "\033[92mOK\033[0m" if req.pec_valid else "\033[91mBAD\033[0m"
        print(f"    pec        : 0x{req.pec:02X}  [{pec_str}]")

        if req.cci_payload:
            print("\033[93m  -- CCI Payload ------------------------------------------\033[0m")
            print(self._hex_dump(req.cci_payload))

        print(f"\033[1m{'-' * 62}\033[0m\n")

    # -- Error frame builder ---------------------------------------------------

    def _build_error_frame(self, raw_frame: bytes) -> bytes:
        """
        Build a best-effort SMBus+MCTP INVALID_INPUT error response from
        a frame that failed to parse. Returns b"" if frame is too short.
        """
        if len(raw_frame) < SMBUS_REQ_HDR_SIZE:
            return b""

        src_slave_addr = raw_frame[3]
        dest_eid       = raw_frame[5]
        src_eid        = raw_frame[6]
        flags          = raw_frame[7]
        msg_tag        = flags & 0x7
        msg_type_byte  = raw_frame[8]
        fm_src         = (self._fm_i2c_addr << 1) | 0x01

        cci_hdr = bytearray(12)
        cci_hdr[0] = 0x01                                    # RESPONSE
        cci_hdr[8] = CCI_RETURN_CODE.INVALID_INPUT & 0xFF
        cci_hdr[9] = (CCI_RETURN_CODE.INVALID_INPUT >> 8) & 0xFF

        resp_flags = 0xC0 | (msg_tag & 0x7)
        body = bytes([
            fm_src, MCTP_HDR_VERSION,
            src_eid, dest_eid,
            resp_flags, msg_type_byte,
        ]) + bytes(cci_hdr)
        frame = bytes([len(body)]) + body
        frame += bytes([crc8_smbus(frame)])
        return frame
