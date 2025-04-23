"""
Copyright (c) 2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

import asyncio
from asyncio import CancelledError
import sys
from typing import Callable
import traceback

from opencis.util.component import RunnableComponent
from opencis.util.logger import logger


class ServerComponent(RunnableComponent):
    def __init__(
        self,
        handle_client: Callable,
        host: str = "0.0.0.0",
        port: int = 0,
        stop_callback: Callable = None,
        label: str = None,
        leave_opened: bool = False,
    ):
        if label is None:
            # Get caller function name
            # pylint: disable=protected-access
            label = sys._getframe(1).f_locals["self"].__class__.__name__
        super().__init__(label)

        if handle_client is None:
            raise ValueError("handle_client must be provided")

        self._host = host
        self._port = port
        self._handle_client = handle_client
        self._stop_callback = stop_callback
        self._descriptor = f"TCP server ({label})"
        self._leave_opened = leave_opened
        self._server_task = None
        self._clients = set()

    def get_port(self):
        return self._port

    async def _create_server(self):
        async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
            self._clients.add(writer)
            logger.info(
                self._create_message(
                    f"Found a new socket connection: {writer.get_extra_info('peername')}"
                )
            )
            await self._handle_client(reader, writer)
            if not self._leave_opened:
                # Handled, now close the connection
                self._clients.discard(writer)
                description = writer.get_extra_info("peername")
                writer.close()
                try:
                    await writer.wait_closed()
                except Exception as e:
                    logger.error(
                        self._create_message(
                            f"Error while closing {description}: {str(e)}, {traceback.format_exc()}"
                        )
                    )
                logger.info(self._create_message(f"Closed client connection: {description}"))

        logger.info(self._create_message(f"Starting {self._descriptor} server"))
        server = await asyncio.start_server(handle_client, self._host, self._port)
        if self._port == 0:
            # Ephemeral port is chosen by the OS
            self._port = server.sockets[0].getsockname()[1]
        logger.info(
            self._create_message(f"{self._descriptor} listening on {self._host}:{self._port}")
        )
        return server

    async def _run(self):
        try:
            logger.info(self._create_message(f"Creating {self._descriptor}"))
            server = await self._create_server()
            self._server_task = asyncio.create_task(server.serve_forever())
            while not server.is_serving():
                await asyncio.sleep(0.1)
            await self._change_status_to_running()
            await self._server_task
        except Exception as e:
            logger.error(
                self._create_message(
                    f"{self._descriptor} error: {str(e)}, {traceback.format_exc()}"
                )
            )
        except CancelledError:
            logger.info(self._create_message(f"Stopped {self._descriptor}"))
            if self._stop_callback is not None:
                await self._stop_callback()

    async def _stop(self):
        logger.info(self._create_message(f"Cancelling {self._descriptor} task"))
        self._server_task.cancel()
        for client in self._clients.copy():
            logger.info(
                self._create_message(
                    f'Closing client connection: {client.get_extra_info("peername")}'
                )
            )
            client.close()
        for client in self._clients.copy():
            await client.wait_closed()
            logger.info(
                self._create_message(
                    f'Closed client connection: {client.get_extra_info("peername")}'
                )
            )
        self._clients.clear()
        try:
            await self._server_task
        except CancelledError:
            logger.info(self._create_message(f"Cancelled {self._descriptor}"))
