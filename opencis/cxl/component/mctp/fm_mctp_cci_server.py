"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.

FmMctpCciServer — External MCTP CCI port for CxlFabricManager
==============================================================

Opens a dedicated TCP port (default 8300) on the Fabric Manager that accepts
raw MCTP-over-TCP connections from external clients (tools, test scripts,
remote FMs, etc.).

Protocol flow per connection:
  Client ──── CciPayloadPacket (MCTP encapsulated CCI REQUEST) ───► Server
  Server ──── CciPayloadPacket (MCTP encapsulated CCI RESPONSE) ──► Client

Reused infrastructure (no new dependencies):
  - MctpPacketProcessor  : bidirectional TCP ↔ asyncio.Queue framing
  - MctpConnection       : two-queue bridge (controller_to_ep / ep_to_controller)
  - CciMessagePacket     : wire format for CCI request/response
  - CciPayloadPacket     : outer MCTP envelope
  - CciExecutor          : command dispatch and background-command management
  - ServerComponent      : asyncio TCP server with multi-client support

Architectural note:
  This server owns a standalone FM-side CciExecutor and PbrSwitchManager.
  The FM is the authoritative control plane; it tracks its own routing state
  independently of the switch hardware emulation.  Commands sent here update
  the FM's authoritative state.  An optional PbrCommandService handles
  mirroring write commands to the physical switch — no switch-programming
  logic lives in this file.
"""

import asyncio
from asyncio import create_task, gather
from typing import List, Optional

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
from opencis.cxl.component.cci_executor import CciExecutor, CciRequest, CciResponse, CciCommand
from opencis.cxl.cci.common import CCI_RETURN_CODE, get_opcode_string
from opencis.cxl.component.gae_manager import GaeManager
from opencis.cxl.cci.fabric_manager.gae import (
    IdentifyGaeCommand,
    GetPidAccessVectorsCommand,
    ProxyGfdMgmtCommand,
    GetProxyThreadStatusCommand,
    CancelProxyThreadCommand,
)
from opencis.cxl.component.fabric_manager.pbr_command_service import PbrCommandService



class FmMctpCciServer(RunnableComponent):
    """
    Fabric Manager external MCTP CCI port.

    Accepts MCTP-over-TCP connections.  For each connection the server:
      1. Spawns a MctpPacketProcessor to handle byte framing.
      2. Reads CciPayloadPackets from the processor's output queue.
      3. Extracts the inner CciMessagePacket (command + payload).
      4. Builds a CciRequest and dispatches it to the shared CciExecutor.
      5. Wraps the CciResponse in a CciMessagePacket and sends it back.

    Multiple simultaneous clients are supported.  They share a single
    CciExecutor instance — the background-command slot serialises any
    commands that require it (consistent with the CXL spec).
    """

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 8300,
        cci_commands: Optional[List[CciCommand]] = None,
        gae_manager: Optional[GaeManager] = None,
        pbr_service: Optional[PbrCommandService] = None,
        label: Optional[str] = None,
    ):
        super().__init__(label or "FmMctpCciServer")
        self._host = host
        self._port = port
        self._gae_manager = gae_manager

        # Shared PbrCommandService — when set, write commands received on
        # port 8300 are automatically mirrored to the physical switch.
        # All switch-programming logic lives in PbrCommandService; this
        # server only calls pbr_service.forward(opcode, payload).
        self._pbr_service: Optional[PbrCommandService] = pbr_service

        # Shared CCI executor — all registered commands land here
        self._cci_executor = CciExecutor(label="FmMctpCci")
        for cmd in (cci_commands or []):
            self._cci_executor.register_command(cmd.get_opcode(), cmd)

        # Register GAE commands if a GaeManager was supplied
        if gae_manager is not None:
            self._register_gae_commands(gae_manager)

        # TCP server — handle_client called per accepted connection.
        # NOTE: leave_opened=False (default) — the ServerComponent closes the
        # writer after _handle_client returns.  Our _handle_client is a long-
        # lived request/response loop that only returns when the client
        # disconnects, so this is correct.
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

    def register_command(self, command: CciCommand) -> None:
        """Register an additional CCI command after construction."""
        self._cci_executor.register_command(command.get_opcode(), command)

    def bind_pbr_service(self, service: PbrCommandService) -> None:
        """
        Bind the shared PbrCommandService after construction (late binding).

        Call this once the switch has connected and the PbrCommandService
        is ready.  Write commands received on port 8300 will then be
        automatically mirrored to the physical switch via the service.
        """
        self._pbr_service = service
        logger.info(self._create_message(
            "PbrCommandService bound — write commands will be mirrored to switch"
        ))

    def set_gfd_executor(self, gfd_executor) -> None:
        """
        Bind the GFD's CciExecutor to the GaeManager so that Proxy GFD
        Management Command (5809h) can forward CCI commands to the GFD.

        Call this once the GFD device has connected and its CciExecutor
        has been constructed (e.g. from the generic_fabric_device entrypoint
        or from a test fixture).
        """
        if self._gae_manager is not None:
            self._gae_manager.set_gfd_executor(gfd_executor)
            logger.info(self._create_message("GFD executor bound to GAE"))
        else:
            logger.warning(self._create_message(
                "set_gfd_executor called but no GaeManager configured"
            ))

    # ------------------------------------------------------------------
    # Private: GAE command registration
    # ------------------------------------------------------------------

    def _register_gae_commands(self, gae_manager: GaeManager) -> None:
        """Register the five minimal GAE commands on the shared CciExecutor."""
        gae_cmds = [
            IdentifyGaeCommand(gae_manager),
            GetPidAccessVectorsCommand(gae_manager),
            ProxyGfdMgmtCommand(gae_manager),
            GetProxyThreadStatusCommand(gae_manager),
            CancelProxyThreadCommand(gae_manager),
        ]
        for cmd in gae_cmds:
            self._cci_executor.register_command(cmd.get_opcode(), cmd)
        logger.debug(self._create_message(
            f"Registered {len(gae_cmds)} GAE commands on CciExecutor"
        ))

    # ------------------------------------------------------------------
    # Per-connection handler
    # ------------------------------------------------------------------

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        peer = writer.get_extra_info("peername")
        logger.info(self._create_message(f"Client connected: {peer}"))

        # Fresh MctpConnection (queue pair) per client.
        # ENDPOINT mode:
        #   TCP bytes in   → conn.controller_to_ep  (our _process_client reads)
        #   ep_to_controller → TCP bytes out         (outgoing pump writes)
        conn = MctpConnection()

        processor = MctpPacketProcessor(
            reader,
            writer,
            conn,
            MCTP_PACKET_PROCESSOR_TYPE.ENDPOINT,
            label=self._label,
            parent_name=self.get_message_label(),
        )

        # Run processor in background; it pumps bytes ↔ queues
        processor_task = create_task(processor.run())
        # Yield to the event loop so both incoming/outgoing pumps start
        # before we begin processing requests from the queue
        await asyncio.sleep(0)


        try:
            await self._process_client(conn)
        except Exception as exc:
            logger.warning(self._create_message(f"Client {peer} error: {exc}"))
        finally:
            # Signal the outgoing pump (ep_to_controller → TCP) to stop
            await conn.ep_to_controller.put(None)
            processor.abort() if hasattr(processor, "abort") else await processor.stop()
            try:
                await asyncio.wait_for(processor_task, timeout=2.0)
            except (asyncio.TimeoutError, Exception):
                processor_task.cancel()
            logger.info(self._create_message(f"Client disconnected: {peer}"))

    async def _process_client(self, conn: MctpConnection) -> None:
        """
        Request/response loop for one client connection.

        Reads CciPayloadPackets from controller_to_ep, dispatches the embedded
        CCI command through the executor, and sends the response back via
        ep_to_controller.

        If a PbrCommandService is bound, write commands are forwarded to the
        physical switch after successful local execution via
        pbr_service.forward(opcode, raw_payload).
        """
        while True:
            raw = await conn.controller_to_ep.get()
            if raw is None:
                logger.debug(self._create_message("Client queue closed — exiting loop"))
                break

            # Unwrap: CciPayloadPacket → CciMessagePacket
            payload_pkt = raw  # already a CciPayloadPacket (from MctpPacketProcessor)
            cci_msg: CciMessagePacket = payload_pkt.get_cci_message()
            opcode = cci_msg.cci_msg_header.command_opcode
            tag    = cci_msg.cci_msg_header.message_tag
            raw_payload = cci_msg.get_payload()
            opcode_str  = get_opcode_string(opcode)

            logger.debug(self._create_message(
                f"RX opcode={opcode_str}({opcode:#06x}) tag={tag}"
            ))

            # 1. Execute locally against FM-side PbrSwitchManager
            request  = CciRequest(opcode=opcode, payload=raw_payload)
            response: CciResponse = await self._cci_executor.execute_command(request)

            # 2. Mirror write commands to the physical switch via PbrCommandService
            if self._pbr_service is not None and response.return_code in (
                CCI_RETURN_CODE.SUCCESS,
                CCI_RETURN_CODE.BACKGROUND_COMMAND_STARTED,
            ):
                await self._pbr_service.forward(opcode, raw_payload)

            # 3. Build and send the MCTP response back to the caller
            resp_msg = CciMessagePacket.create(
                message_category=CCI_MCTP_MESSAGE_CATEGORY.RESPONSE,
                opcode=opcode,
                data=response.payload if response.payload else b"",
                message_tag=tag,
                return_code=int(response.return_code),
                background_operation=int(response.bo_flag),
                vendor_specific_extended_status=response.vendor_specific_status,
            )

            rc_str = CCI_RETURN_CODE(response.return_code).name
            logger.debug(self._create_message(
                f"TX opcode={opcode_str} tag={tag} rc={rc_str}"
            ))

            resp_pkt = CciPayloadPacket.create(resp_msg)
            await conn.ep_to_controller.put(resp_pkt)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def _on_server_stop(self) -> None:
        logger.info(self._create_message("TCP server stopped"))

    async def _run(self) -> None:
        server_task   = create_task(self._server.run())
        executor_task = create_task(self._cci_executor.run())

        await self._server.wait_for_ready()
        await self._cci_executor.wait_for_ready()

        # Update port in case OS picked an ephemeral one
        self._port = self._server.get_port()
        logger.info(self._create_message(
            f"FM MCTP CCI server listening on {self._host}:{self._port}"
        ))

        await self._change_status_to_running()
        await gather(server_task, executor_task)

    async def _stop(self) -> None:
        await self._server.stop()
        await self._cci_executor.stop()
