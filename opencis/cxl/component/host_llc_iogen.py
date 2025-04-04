"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

# pylint: disable=duplicate-code
from asyncio import create_task, gather, sleep
from dataclasses import dataclass
from random import randrange

from opencis.util.logger import logger
from opencis.util.component import RunnableComponent
from opencis.cxl.transport.memory_fifo import (
    MemoryFifoPair,
    MemoryRequest,
    MemoryResponse,
    MEMORY_REQUEST_TYPE,
    MEMORY_RESPONSE_STATUS,
)


@dataclass
class HostLlcIoGenConfig:
    host_name: str
    processor_to_cache_fifo: MemoryFifoPair
    memory_size: int


class HostLlcIoGen(RunnableComponent):
    def __init__(self, config: HostLlcIoGenConfig):
        super().__init__(lambda class_name: f"{config.host_name}:{class_name}")
        self._host_name = config.host_name
        self._processor_to_cache_fifo = config.processor_to_cache_fifo
        self._memory_line = config.memory_size // 0x40

        self._internal_iogen = False

    # pylint: disable=duplicate-code
    async def load(self, address: int, size: int) -> MemoryResponse:
        packet = MemoryRequest(MEMORY_REQUEST_TYPE.READ, address, size)
        await self._processor_to_cache_fifo.request.put(packet)
        packet = await self._processor_to_cache_fifo.response.get()
        return packet

    async def store(self, address: int, size: int, value: int) -> MemoryResponse:
        packet = MemoryRequest(MEMORY_REQUEST_TYPE.WRITE, address, size, value)
        await self._processor_to_cache_fifo.request.put(packet)
        packet = await self._processor_to_cache_fifo.response.get()
        return packet

    async def _host_process_llc_iogen(self):
        await sleep(5)
        stop_process = False

        while not stop_process:
            if self._internal_iogen is True:
                valid_addr = set()
                for _ in range(10000):
                    addr = randrange(0, self._memory_line) * 0x40
                    written_data = addr
                    valid_addr.add(addr)

                    logger.debug(f"[{self._host_name}] Write 0x{written_data:X} at 0x{addr:x}")
                    packet = await self.store(addr, 0x40, written_data)
                    if packet is None:
                        logger.debug(self._create_message("Stop processing host llc iogen"))
                        stop_process = True
                    assert packet.status == MEMORY_RESPONSE_STATUS.OK

                logger.info(f"[{self._host_name}] Written Counts {len(valid_addr)}")

                for _, addr in enumerate(valid_addr):
                    packet = await self.load(addr, 0x40)
                    if packet is None:
                        logger.debug(self._create_message("Stop processing host llc iogen"))
                        stop_process = True
                    assert packet.status == MEMORY_RESPONSE_STATUS.OK

                    read_data = packet.data
                    logger.debug(f"[{self._host_name}] Read 0x{read_data:X} from 0x{addr:x}")
                    assert addr == read_data, f"addr={hex(addr)}:data={hex(read_data)}"

                logger.info(f"[{self._host_name}] Simple Test Done")

            else:
                packet = await self._processor_to_cache_fifo.response.get()
                if packet is None:
                    logger.debug(self._create_message("Stop processing host llc iogen"))
                    stop_process = True

    async def _run(self):
        tasks = [
            create_task(self._host_process_llc_iogen()),
        ]
        await self._change_status_to_running()
        await gather(*tasks)

    async def _stop(self):
        await self._processor_to_cache_fifo.response.put(None)
