"""
 Copyright (c) 2024, Eeum, Inc.

 This software is licensed under the terms of the Revised BSD License.
 See LICENSE for details.
"""

from asyncio import StreamReader, StreamWriter, create_task, gather
from enum import Enum, auto
from typing import Optional

from opencis.util.logger import logger
from opencis.cxl.component.mctp.mctp_connection import MctpConnection
from opencis.cxl.component.mctp.mctp_packet_reader import (
    MctpPacketReader,
)
from opencis.util.component import RunnableComponent


class MCTP_PACKET_PROCESSOR_TYPE(Enum):
    CONTROLLER = auto()
    ENDPOINT = auto()


class MctpPacketProcessor(RunnableComponent):
    def __init__(
        self,
        reader: StreamReader,
        writer: StreamWriter,
        mctp_connection: MctpConnection,
        processor_type: MCTP_PACKET_PROCESSOR_TYPE,
        label: Optional[str] = None,
    ):
        super().__init__(label)
        self._reader = MctpPacketReader(reader, label=label)
        self._writer = writer
        self._mctp_connection = mctp_connection
        if processor_type == MCTP_PACKET_PROCESSOR_TYPE.CONTROLLER:
            self._incoming = self._mctp_connection.ep_to_controller
            self._outgoing = self._mctp_connection.controller_to_ep
        else:
            self._incoming = self._mctp_connection.controller_to_ep
            self._outgoing = self._mctp_connection.ep_to_controller

    async def _process_incoming_packets(self):
        logger.debug(self._create_message("Starting incoming packet processor"))
        while True:
            try:
                packet = await self._reader.get_packet()
                await self._incoming.put(packet)
            except Exception as e:
                logger.debug(self._create_message(str(e)))
                await self._stop_outgoing_processor()
                break
        logger.debug(self._create_message("Stopped incoming packet processor"))

    async def _stop_outgoing_processor(self):
        await self._outgoing.put(None)

    async def _process_outgoing_packets(self):
        logger.debug(self._create_message("Starting outgoing packet processor"))
        while True:
            packet = await self._outgoing.get()
            if packet is None:
                break
            self._writer.write(bytes(packet))
            await self._writer.drain()
        logger.debug(self._create_message("Stopped outgoing packet processor"))

    async def _run(self):
        tasks = [
            create_task(self._process_incoming_packets()),
            create_task(self._process_outgoing_packets()),
        ]
        await self._change_status_to_running()
        await gather(*tasks)

    async def _stop(self):
        self._reader.abort()
