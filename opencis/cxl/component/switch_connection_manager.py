"""
 Copyright (c) 2024, Eeum, Inc.

 This software is licensed under the terms of the Revised BSD License.
 See LICENSE for details.
"""

import asyncio
from asyncio import CancelledError, create_task, gather
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
        self._server_task = None
        self._event_handler = None
        self._clients = set()

    async def _run(self):
        try:
            logger.info(self._create_message("Creating TCP server"))
            server = await self._create_server()
            self._server_task = asyncio.create_task(server.serve_forever())
            logger.info(self._create_message("Starting TCP server task"))
            while not server.is_serving():
                await asyncio.sleep(0.1)
            await self._change_status_to_running()
            await self._server_task
        except Exception as e:
            logger.error(
                self._create_message(
                    f"{self.__class__.__name__} error: {str(e)}, {traceback.format_exc()}"
                )
            )
        except CancelledError:
            logger.info(self._create_message("Stopped TCP server"))

    async def _stop(self):
        logger.info(self._create_message("Cancelling TCP server task"))
        self._server_task.cancel()
        for transport in self._clients:
            transport.close()
        self._clients.clear()
        try:
            await self._server_task
        except CancelledError:
            logger.info(self._create_message("Cancelled TCP server"))

    async def _create_server(self):
        async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
            self._clients.add(writer.transport)
            port_index = None
            try:
                logger.info(self._create_message("Found a new socket connection"))
                port_index = await self._wait_for_connection_request(reader)
                await self._send_confirmation(writer)
                logger.info(
                    self._create_message(f"Binding incoming connection to port {port_index}")
                )
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
            else:
                await self._update_connection_status(port_index, connected=False)
            await self._close_connection(writer, port_index)

        logger.info(self._create_message(f"Listening to port {self._port}"))
        server = await asyncio.start_server(handle_client, self._host, self._port)
        return server

    async def _update_connection_status(self, port_id: int, connected: bool):
        self._ports[port_id].connected = connected
        if not self._event_handler:
            return
        await self._event_handler(PortUpdateEvent(port_id=port_id, connected=connected))

    async def _close_connection(
        self, writer: asyncio.StreamWriter, port_index: Optional[int] = None
    ):
        self._clients.discard(writer.transport)
        writer.transport.close()
        writer.close()
        try:
            await writer.wait_closed()
        except Exception as e:
            logger.error(
                self._create_message(
                    f"{self.__class__.__name__} error: {str(e)}, {traceback.format_exc()}"
                )
            )

        if port_index is None:
            logger.info(self._create_message("Closed connection"))
        else:
            logger.info(self._create_message(f"Closed connection for port {port_index}"))

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
