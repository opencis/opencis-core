"""
 Copyright (c) 2024, Eeum, Inc.

 This software is licensed under the terms of the Revised BSD License.
 See LICENSE for details.
"""

import asyncio
from typing import cast, Tuple, Optional
from enum import Enum, auto

from opencis.util.logger import logger
from opencis.cxl.transport.transaction import (
    SIDEBAND_TYPES,
    SidebandConnectionRequestPacket,
    BaseSidebandPacket,
    CxlIoCfgRdPacket,
)
from opencis.cxl.component.common import CXL_COMPONENT_TYPE
from opencis.cxl.component.packet_reader import PacketReader
from opencis.cxl.component.cxl_connection import CxlConnection
from opencis.cxl.component.cxl_packet_processor import CxlPacketProcessor
from opencis.util.component import RunnableComponent
from opencis.util.pci import create_bdf


class INJECTED_ERRORS(Enum):
    NON_SIDEBAND = auto()
    NON_CONNNECTION_REQUEST = auto()


class SwitchConnectionClient(RunnableComponent):
    def __init__(
        self,
        port_index: int,
        component_type: CXL_COMPONENT_TYPE,
        ld_count: int = 0,
        host: str = "0.0.0.0",
        port: int = 8000,
        retry: bool = True,
        parent_name: Optional[str] = None,
    ):
        label_prefix = parent_name + ":" if parent_name else ""
        super().__init__(lambda class_name: f"{label_prefix}{class_name}:Port{port_index}")
        self._host = host
        self._port = port
        self._port_index = port_index
        self._component_type = component_type
        if ld_count != 0:
            self._cxl_connection = [CxlConnection() for _ in range(ld_count)]
        else:
            self._cxl_connection = CxlConnection()
        self._packet_processor = None
        self._injected_error = None
        self._retry = retry
        self._stop_signal = False

    async def _connect(self) -> Tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        reader, writer = await asyncio.open_connection(self._host, self._port)
        if self._injected_error is None:
            request = SidebandConnectionRequestPacket.create(self._port_index)
        elif self._injected_error == INJECTED_ERRORS.NON_SIDEBAND:
            request = CxlIoCfgRdPacket.create(create_bdf(0, 0, 0), 0, 4)
        elif self._injected_error == INJECTED_ERRORS.NON_CONNNECTION_REQUEST:
            request = BaseSidebandPacket.create(SIDEBAND_TYPES.CONNECTION_REJECT)

        logger.debug(self._create_message("Sending Connection Request Packet"))
        writer.write(bytes(request))
        await writer.drain()

        logger.debug(self._create_message("Waiting for Connection Accept"))
        packet_reader = PacketReader(reader, parent_name=self.get_message_label())
        response = await packet_reader.get_packet()

        if not response.is_sideband():
            message = "Received unexpected packet"
            logger.warning(self._create_message(message))
            raise Exception(message)
        sideband_response = cast(BaseSidebandPacket, response)
        if sideband_response.is_connection_reject():
            message = "Connection rejected"
            logger.warning(self._create_message(message))
            raise Exception(message)
        if not sideband_response.is_connection_accept():
            message = "Received unexpected sideband packet"
            logger.warning(self._create_message(message))
            raise Exception(message)
        logger.debug(self._create_message("Client Connected"))

        return (reader, writer)

    def inject_error(self, injected_error: INJECTED_ERRORS):
        self._injected_error = injected_error

    def get_cxl_connection(self):
        return self._cxl_connection

    def get_port_index(self):
        return self._port_index

    async def _run(self):
        if self._retry:
            time_out = 120
            loop = asyncio.get_running_loop()
            end_time = loop.time() + time_out
            print_time = loop.time() + 5
            elapsed = 0
            while True:
                if self._stop_signal:
                    break
                try:
                    (reader, writer) = await self._connect()
                    break
                except Exception as e:
                    if loop.time() >= end_time:
                        raise Exception(
                            self._create_message("Timed out waiting for CXL-Switch")
                        ) from e
                    if loop.time() >= print_time:
                        elapsed += 5
                        logger.info(
                            self._create_message(f"Awaiting CXL-Switch Ready... {elapsed}s")
                        )
                        print_time = loop.time() + 5
                    await asyncio.sleep(1)
        else:
            (reader, writer) = await self._connect()

        _, local_port = writer.get_extra_info("sockname")
        logger.info(self._create_message(f"Connected to switch using local port {local_port}"))

        self._packet_processor = CxlPacketProcessor(
            reader,
            writer,
            self._cxl_connection,
            self._component_type,
            label=f"ClientPort{self._port_index}",
        )
        tasks = [asyncio.create_task(self._packet_processor.run())]
        await self._packet_processor.wait_for_ready()
        await self._change_status_to_running()
        await asyncio.gather(*tasks)

    async def _stop(self):
        self._stop_signal = True
        await self._packet_processor.stop()
