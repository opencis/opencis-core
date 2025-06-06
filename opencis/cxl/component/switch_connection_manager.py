"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

import asyncio
from asyncio import create_task, gather
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional, List, Callable, Coroutine, Any, cast
import traceback

from opencis.cxl.component.cxl_connection import CxlConnection
from opencis.cxl.transport.transaction import (
    BasePacket,
    SidebandConnectionRequestPacket,
    BaseSidebandPacket,
    PAYLOAD_TYPE,
    SIDEBAND_TYPES,
)
from opencis.cxl.component.packet_reader import PacketReader
from opencis.cxl.component.cxl_packet_processor import CxlPacketProcessor
from opencis.cxl.component.cxl_component import (
    PortConfig,
    PORT_TYPE,
)
from opencis.cxl.component.common import CXL_COMPONENT_TYPE
from opencis.util.component import RunnableComponent
from opencis.util.logger import logger
from opencis.util.server import ServerComponent


@dataclass
class SwitchPort:
    port_config: PortConfig
    connected: bool = False
    cxl_connection: CxlConnection = field(default_factory=CxlConnection)
    packet_processor: Optional[CxlPacketProcessor] = None


@dataclass
class PortUpdateEvent:
    port_id: int
    connected: bool


AsyncEventHandlerType = Callable[[PortUpdateEvent], Coroutine[Any, Any, None]]


class CONNECTION_STATUS(Enum):
    OK = auto()
    DISCONNECTED = auto()
    HANDSHAKE_ERROR = auto()


class SwitchConnectionManager(RunnableComponent):
    def __init__(
        self,
        port_configs: List[PortConfig],
        host: str = "0.0.0.0",
        port: int = 8000,
        connection_timeout_ms: int = 5000,
    ):
        super().__init__()
        self._port_configs = port_configs
        self._host = host
        self._port = port
        self._connection_timeout_ms = connection_timeout_ms
        self._ports = [SwitchPort(port_config=port_config) for port_config in port_configs]
        self._server_component = ServerComponent(
            handle_client=self._handle_client,
            host=self._host,
            port=self._port,
        )
        self._event_handler = None

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        port_index = None
        try:
            logger.info(self._create_message("Found a new socket connection"))
            port_index = await self._wait_for_connection_request(reader)
            await self._send_confirmation(writer)
            logger.info(self._create_message(f"Binding incoming connection to port {port_index}"))
            await self._update_connection_status(port_index, connected=True)
            await self._start_packet_processor(reader, writer, port_index)
        except Exception as e:
            logger.error(
                self._create_message(
                    f"{self.__class__.__name__} error: {str(e)}, {traceback.format_exc()}"
                )
            )

        if port_index is None:
            await self._send_rejection(writer)
            # Connection closed log printed from ServerComponent
        else:
            await self._update_connection_status(port_index, connected=False)
            logger.info(self._create_message(f"Closed client connection for port {port_index}"))

    async def _update_connection_status(self, port_id: int, connected: bool):
        self._ports[port_id].connected = connected
        if not self._event_handler:
            return
        await self._event_handler(PortUpdateEvent(port_id=port_id, connected=connected))

    async def _send_confirmation(self, writer: asyncio.StreamWriter):
        sideband_response = BaseSidebandPacket.create(SIDEBAND_TYPES.CONNECTION_ACCEPT)
        writer.write(bytes(sideband_response))
        await writer.drain()

    async def _send_rejection(self, writer: asyncio.StreamWriter):
        sideband_response = BaseSidebandPacket.create(SIDEBAND_TYPES.CONNECTION_REJECT)
        writer.write(bytes(sideband_response))
        await writer.drain()

    async def _wait_for_connection_request(self, reader: asyncio.StreamReader) -> int:
        # TODO: Use _connection_timeout_ms to check timeout

        logger.debug(self._create_message("Waiting for a connection request"))

        packet_reader = PacketReader(reader, "SwitchConnectionManager")
        packet = await packet_reader.get_packet()
        base_packet = cast(BasePacket, packet)

        logger.debug(self._create_message("Received a packet"))
        if base_packet.system_header.payload_type != PAYLOAD_TYPE.SIDEBAND:
            message = "Handshake Error"
            logger.debug(self._create_message(message))
            logger.debug(self._create_message(base_packet.get_pretty_string()))
            raise Exception(message)

        base_sideband_packet = cast(BaseSidebandPacket, packet)
        if base_sideband_packet.sideband_header.type != SIDEBAND_TYPES.CONNECTION_REQUEST:
            message = "Handshake Error"
            logger.debug(self._create_message(message))
            logger.debug(self._create_message(base_packet.get_pretty_string()))
            raise Exception(message)

        connection_request = cast(SidebandConnectionRequestPacket, packet)
        port_index = connection_request.port

        # TODO: CE-32, ensure incoming device is connected to a correct port.
        logger.debug(
            self._create_message("Checking if the connection request had a valid port index")
        )
        if port_index < 0 or port_index >= len(self._ports):
            raise Exception(f"Invalid port number: {port_index}")
        if self._ports[port_index].connected:
            raise Exception(f"Connection already exists for port {port_index}")

        return port_index

    async def _start_packet_processor(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        port_index: int,
    ):
        logger.info(self._create_message(f"Starting PacketProcessor for port {port_index}"))
        cxl_connection = self._ports[port_index].cxl_connection
        port_config = self._ports[port_index].port_config
        component_type = (
            CXL_COMPONENT_TYPE.USP if port_config.type == PORT_TYPE.USP else CXL_COMPONENT_TYPE.DSP
        )
        packet_processor = CxlPacketProcessor(
            reader,
            writer,
            cxl_connection,
            component_type,
            label=f"SwitchPort{port_index}",
        )
        self._ports[port_index].packet_processor = packet_processor
        tasks = [create_task(packet_processor.run())]
        await packet_processor.wait_for_ready()
        await gather(*tasks)
        self._ports[port_index].packet_processor = None

    def get_cxl_connection(self, port: int) -> CxlConnection:
        if port >= len(self._ports):
            raise Exception(f"Port {port} is unsupported.")
        return self._ports[port].cxl_connection

    def get_switch_ports(self) -> List[SwitchPort]:
        return self._ports

    def register_event_handler(self, event_handler: AsyncEventHandlerType):
        self._event_handler = event_handler

    def get_port(self):
        return self._port

    async def _run(self):
        server_task = create_task(self._server_component.run())
        await self._server_component.wait_for_ready()
        self._port = self._server_component.get_port()
        await self._change_status_to_running()
        await server_task

    async def _stop(self):
        await self._server_component.stop()
