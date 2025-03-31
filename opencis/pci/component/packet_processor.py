"""
Copyright (c) 2024, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from asyncio import create_task, gather
from typing import Optional, Union, Callable

from opencis.util.logger import logger
from opencis.pci.component.fifo_pair import FifoPair
from opencis.util.component import RunnableComponent


# PacketProcessor can be used a relay between two FifoPairs when it is used as is.
# PacketProcessor can be inherited by another class when customized processing logics are needed.


class PacketProcessor(RunnableComponent):
    def __init__(
        self,
        upstream_fifo: FifoPair,
        downstream_fifo: Optional[FifoPair] = None,
        label: Optional[Union[str, Callable]] = None,
    ):
        super().__init__(label)
        self._upstream_fifo = upstream_fifo
        self._downstream_fifo = downstream_fifo

    async def _process_host_to_target(self):
        if self._downstream_fifo is None:
            logger.debug(self._create_message("Skipped processing host to target packets"))
            return
        logger.debug(self._create_message("Started processing host to target packets"))
        while True:
            packet = await self._upstream_fifo.host_to_target.get()
            if packet is None:
                logger.debug(self._create_message("Stopped host to target packets"))
                break
            logger.debug(self._create_message("Received host to target Packet"))
            await self._downstream_fifo.host_to_target.put(packet)

    async def _process_target_to_host(self):
        if self._downstream_fifo is None:
            logger.debug(self._create_message("Skipped processing target to host packets"))
            return
        logger.debug(self._create_message("Started processing target to host packets"))
        while True:
            packet = await self._downstream_fifo.target_to_host.get()
            if packet is None:
                logger.debug(self._create_message("Stopped target to host packets"))
                break
            logger.debug(self._create_message("Received target to host Packet"))
            await self._upstream_fifo.target_to_host.put(packet)

    async def _run(self):
        tasks = [
            create_task(self._process_host_to_target()),
            create_task(self._process_target_to_host()),
        ]
        await self._change_status_to_running()
        await gather(*tasks)

    async def _stop(self):
        if self._downstream_fifo is not None:
            await self._downstream_fifo.target_to_host.put(None)
        await self._upstream_fifo.host_to_target.put(None)
