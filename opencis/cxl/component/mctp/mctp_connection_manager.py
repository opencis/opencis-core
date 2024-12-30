"""
 Copyright (c) 2024, Eeum, Inc.

 This software is licensed under the terms of the Revised BSD License.
 See LICENSE for details.
"""

import asyncio
from dataclasses import dataclass, field
from typing import Optional

from opencis.util.logger import logger
from opencis.cxl.component.mctp.mctp_connection import MctpConnection
from opencis.cxl.component.mctp.mctp_packet_processor import (
    MctpPacketProcessor,
    MCTP_PACKET_PROCESSOR_TYPE,
)
from opencis.util.component import RunnableComponent

# pylint: disable=duplicate-code


@dataclass
class MctpPort:
    connected: bool = False
    mctp_connection: MctpConnection = field(default_factory=MctpConnection)
    packet_processor: Optional[MctpPacketProcessor] = None


class MctpConnectionManager(RunnableComponent):
    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 8100,
        connection_timeout_ms: int = 5000,
    ):
        super().__init__()
        self._host = host
        self._port = port
        self._connection_timeout_ms = connection_timeout_ms
        # TODO: Support receiving connections from CXL Devices
        self._switch_port = MctpPort()
        self._server_task = None

    async def _run(self):
        # pylint: disable=bare-except
        try:
            logger.info(self._create_message(f"Creating TCP server at port {self._port}"))
            server = await self._create_server()
            self._server_task = asyncio.create_task(server.serve_forever())
            logger.info(self._create_message("Starting TCP server task"))
            while not server.is_serving():
                await asyncio.sleep(0.1)
            await self._change_status_to_running()
            await self._server_task
        except Exception as e:
            logger.debug(self._create_message(f"Exception: {str(e)}"))
        except:
            logger.info(self._create_message("Stopped TCP server"))
            if self._switch_port.packet_processor is not None:
                logger.info(self._create_message("Stopping PacketProcessor for Switch Port"))
                await self._switch_port.packet_processor.stop()
                logger.info(self._create_message("Stopped PacketProcessor for Switch Port"))

    async def _stop(self):
        logger.info(self._create_message("Canceling TCP server task"))
        self._server_task.cancel()

    async def _create_server(self):
        async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
            try:
                logger.info(self._create_message("Found a new socket connection"))
                if self._switch_port.connected:
                    logger.warning(
                        self._create_message("Connection already exists for Switch Port")
                    )
                else:
                    logger.info(self._create_message("Binding incoming connection to Switch Port"))
                    self._switch_port.connected = True
                    await self._start_packet_processor(reader, writer)
            except Exception as e:
                logger.warning(self._create_message(str(e)))

            self._switch_port.connected = False
            await self._close_connection(writer)

        server = await asyncio.start_server(handle_client, self._host, self._port)
        return server

    async def _close_connection(self, writer: asyncio.StreamWriter):
        writer.close()
        await writer.wait_closed()
        logger.info(self._create_message("Closed connnection"))

    async def _start_packet_processor(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ):
        logger.info(self._create_message("Starting PacketProcessor for Switch Port"))
        packet_processor = MctpPacketProcessor(
            reader,
            writer,
            self._switch_port.mctp_connection,
            MCTP_PACKET_PROCESSOR_TYPE.CONTROLLER,
        )
        self._switch_port.packet_processor = packet_processor
        await packet_processor.run()
        self._switch_port.packet_processor = None

    def get_mctp_connection(self) -> MctpConnection:
        return self._switch_port.mctp_connection
