"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.

FmMctpCciServer — External MCTP CCI port for CxlFabricManager
==============================================================

Opens a dedicated TCP port (default 8300) on the Fabric Manager that accepts
raw MCTP-over-TCP connections from external clients (tools, test scripts,
remote FMs, etc.) and bridges them to the existing FM CLI path.

Protocol flow per connection:
  Client ──── CciPayloadPacket (MCTP REQUEST opcode + payload) ───► Server
  Server ─── depacketize ──► MctpCciApiClient.send_raw_cci() ──► Switch
  Switch ─── CCI response ──►  Server ──── CciPayloadPacket (RESPONSE) ──► Client

Design — pure MCTP adapter:
  This server contains ZERO switch-programming logic and ZERO local state.
  It is a transparent bridge:

    incoming MCTP bytes
        │  (MctpPacketProcessor depacketizes)
        ▼
    FmMctpCciServer._process_client()
        │  extracts (opcode, raw_payload_bytes)
        ▼
    MctpCciApiClient.send_raw_cci(opcode, raw_payload_bytes)
        │  ← this IS the FM CLI path (same api_client socketio_server uses)
        │  sends CCI to switch on port 8100, returns (rc, response_bytes)
        ▼
    FmMctpCciServer builds MCTP response from (rc, response_bytes)
        │  (MctpPacketProcessor repacketizes)
        ▼
    outgoing MCTP bytes → client

Reused infrastructure:
  - MctpPacketProcessor  : bidirectional TCP ↔ asyncio.Queue framing
  - MctpConnection       : two-queue bridge (controller_to_ep / ep_to_controller)
  - CciMessagePacket     : wire format for CCI request/response
  - CciPayloadPacket     : outer MCTP envelope
  - MctpCciApiClient     : FM CLI path (same instance used by socketio_server)
  - ServerComponent      : asyncio TCP server with multi-client support
"""

import asyncio
from asyncio import create_task, gather
from typing import Optional, TYPE_CHECKING

from opencis.util.component import RunnableComponent
from opencis.util.logger import logger
from opencis.util.server import ServerComponent

from opencis.cxl.component.mctp.mctp_connection import MctpConnection
from opencis.cxl.component.mctp.mctp_packet_processor import (
    MctpPacketProcessor,
    MCTP_PACKET_PROCESSOR_TYPE,
)
from opencis.cxl.transport.cci_packets import CciMessagePacket, CciPayloadPacket
from opencis.cxl.transport.packet_constants import CCI_MCTP_MESSAGE_CATEGORY
from opencis.cxl.cci.common import CCI_RETURN_CODE, get_opcode_string

if TYPE_CHECKING:
    from opencis.cxl.component.mctp.mctp_cci_api_client import MctpCciApiClient


class FmMctpCciServer(RunnableComponent):
    """
    Fabric Manager external MCTP CCI port — pure adapter.

    Accepts MCTP-over-TCP connections.  For each connection the server:
      1. Spawns a MctpPacketProcessor to handle byte framing.
      2. Reads CciPayloadPackets from the processor's output queue.
      3. Extracts (opcode, raw_payload_bytes) from the inner CciMessagePacket.
      4. Calls MctpCciApiClient.send_raw_cci(opcode, raw_payload_bytes).
         ← This IS the existing FM CLI path (same api_client that
           FabricManagerSocketIoServer uses to talk to the switch).
      5. Gets back (return_code, response_bytes, is_background).
      6. Wraps into a CciMessagePacket response and sends back to the caller.

    No CciExecutor, no PbrSwitchManager, no local state.
    All CCI logic lives in the switch and is accessed via the shared api_client.
    """

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 8300,
        mctp_client: Optional["MctpCciApiClient"] = None,
        label: Optional[str] = None,
    ):
        super().__init__(label or "FmMctpCciServer")
        self._host = host
        self._port = port

        # The FM CLI path — same MctpCciApiClient instance used by
        # FabricManagerSocketIoServer to talk to the switch on port 8100.
        # When None the server still accepts connections but returns
        # UNSUPPORTED for every command (useful for unit tests).
        self._mctp_client: Optional["MctpCciApiClient"] = mctp_client

        self._server = ServerComponent(
            handle_client=self._handle_client,
            host=self._host,
            port=self._port,
            stop_callback=self._on_server_stop,
            label="FmMctpCciServer",
        )

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def get_port(self) -> int:
        """Return the actual TCP port (useful when port=0 was requested)."""
        return self._server.get_port()

    def bind_mctp_client(self, client: "MctpCciApiClient") -> None:
        """
        Late-bind the FM CLI api_client after construction.

        Call this once the switch has connected on port 8100 and the
        MctpCciApiClient is running.  All subsequent MCTP requests on
        port 8300 will be forwarded to the switch via send_raw_cci().
        """
        self._mctp_client = client
        logger.info(self._create_message(
            "MctpCciApiClient bound — port 8300 now bridges to FM CLI path"
        ))

    # ------------------------------------------------------------------
    # Per-connection handler
    # ------------------------------------------------------------------

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        peer = writer.get_extra_info("peername")
        logger.info(self._create_message(f"Client connected: {peer}"))

        conn = MctpConnection()
        processor = MctpPacketProcessor(
            reader,
            writer,
            conn,
            MCTP_PACKET_PROCESSOR_TYPE.ENDPOINT,
            label=self._label,
            parent_name=self.get_message_label(),
        )
        processor_task = create_task(processor.run())
        await asyncio.sleep(0)

        try:
            await self._process_client(conn)
        except Exception as exc:
            logger.warning(self._create_message(f"Client {peer} error: {exc}"))
        finally:
            await conn.ep_to_controller.put(None)
            processor.abort() if hasattr(processor, "abort") else await processor.stop()
            try:
                await asyncio.wait_for(processor_task, timeout=2.0)
            except (asyncio.TimeoutError, Exception):
                processor_task.cancel()
            logger.info(self._create_message(f"Client disconnected: {peer}"))

    async def _process_client(self, conn: MctpConnection) -> None:
        """
        Request/response loop — pure MCTP adapter.

        For every incoming CCI request:
          1. Extract (opcode, raw_payload) from the MCTP packet.
          2. Forward to the FM CLI path via send_raw_cci().
          3. Build the MCTP response from the raw bytes returned.

        The switch does all command processing.  This server is stateless.
        """
        while True:
            raw = await conn.controller_to_ep.get()
            if raw is None:
                logger.debug(self._create_message("Client queue closed — exiting loop"))
                break

            # Step 1 — depacketize MCTP → extract (opcode, tag, payload_bytes)
            cci_msg: CciMessagePacket = raw.get_cci_message()
            opcode      = cci_msg.cci_msg_header.command_opcode
            tag         = cci_msg.cci_msg_header.message_tag
            raw_payload = cci_msg.get_payload() or b""
            opcode_str  = get_opcode_string(opcode)

            logger.debug(self._create_message(
                f"RX opcode={opcode_str}({opcode:#06x}) tag={tag} "
                f"payload_len={len(raw_payload)}"
            ))

            # Step 2 — forward to FM CLI path (MctpCciApiClient → switch)
            return_code, response_bytes, is_background = \
                await self._forward_to_cli(opcode, raw_payload)

            logger.debug(self._create_message(
                f"TX opcode={opcode_str} tag={tag} "
                f"rc={CCI_RETURN_CODE(return_code).name} "
                f"bg={is_background} resp_len={len(response_bytes)}"
            ))

            # Step 3 — repacketize response → send back to caller
            resp_msg = CciMessagePacket.create(
                message_category=CCI_MCTP_MESSAGE_CATEGORY.RESPONSE,
                opcode=opcode,
                data=response_bytes,
                message_tag=tag,
                return_code=int(return_code),
                background_operation=int(is_background),
                vendor_specific_extended_status=0,
            )
            await conn.ep_to_controller.put(CciPayloadPacket.create(resp_msg))

    async def _forward_to_cli(
        self, opcode: int, payload: bytes
    ) -> "tuple[CCI_RETURN_CODE, bytes, bool]":
        """
        Bridge to the FM CLI path via MctpCciApiClient.send_raw_cci().

        If no client is bound (unit-test mode), returns UNSUPPORTED.
        If the client throws an exception, returns INTERNAL_ERROR.
        """
        if self._mctp_client is None:
            logger.warning(self._create_message(
                f"No mctp_client — returning UNSUPPORTED for opcode {opcode:#06x}"
            ))
            return (CCI_RETURN_CODE.UNSUPPORTED, b"", False)

        try:
            return await self._mctp_client.send_raw_cci(opcode, payload)
        except Exception as exc:
            logger.error(self._create_message(
                f"FM CLI path error for opcode {opcode:#06x}: {exc}"
            ))
            return (CCI_RETURN_CODE.INTERNAL_ERROR, b"", False)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def _on_server_stop(self) -> None:
        logger.info(self._create_message("TCP server stopped"))

    async def _run(self) -> None:
        server_task = create_task(self._server.run())
        await self._server.wait_for_ready()
        self._port = self._server.get_port()
        logger.info(self._create_message(
            f"FM MCTP CCI server listening on {self._host}:{self._port} "
            "(pure adapter -> FM CLI path)"
        ))
        await self._change_status_to_running()
        await gather(server_task)

    async def _stop(self) -> None:
        await self._server.stop()
