"""
 Copyright (c) 2024, Eeum, Inc.

 This software is licensed under the terms of the Revised BSD License.
 See LICENSE for details.
"""

import asyncio
from opencis.cxl.component.mctp.mctp_connection import MctpConnection
from opencis.cxl.component.mctp.mctp_packet_processor import (
    MctpPacketProcessor,
    MCTP_PACKET_PROCESSOR_TYPE,
)
from opencis.util.component import RunnableComponent
from opencis.util.logger import logger


class MctpConnectionClient(RunnableComponent):
    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 8100,
        auto_reconnect: bool = True,
        reconnect_delay: float = 0.1,
    ):
        super().__init__()
        self._host = host
        self._port = port
        self._auto_reconnect = auto_reconnect
        self._reconnect_delay = reconnect_delay
        self._mctp_connection = MctpConnection()
        self._packet_processor = None
        self._running = False

    async def _connect(self):
        return await asyncio.open_connection(self._host, self._port)

    def get_mctp_connection(self):
        return self._mctp_connection

    async def _run(self):
        self._running = True
        if self._auto_reconnect:
            logger.debug(self._create_message("Enabled auto-reconnect"))

        while self._running:
            try:
                (reader, writer) = await self._connect()
                self._packet_processor = MctpPacketProcessor(
                    reader,
                    writer,
                    self._mctp_connection,
                    MCTP_PACKET_PROCESSOR_TYPE.ENDPOINT,
                )
                await self._change_status_to_running()
                await self._packet_processor.run()
                self._packet_processor = None
            except Exception as e:
                if not self._auto_reconnect:
                    logger.warning(self._create_message(str(e)))

            if self._packet_processor is not None:
                break  # Normal termination

            if not self._auto_reconnect:
                logger.error(self._create_message("Connection attempt failed"))
                break

            logger.warning(self._create_message("Attempting to reconnect"))
            await asyncio.sleep(self._reconnect_delay)

    async def _stop(self):
        self._running = False
        if self._packet_processor:
            await self._packet_processor.stop()
