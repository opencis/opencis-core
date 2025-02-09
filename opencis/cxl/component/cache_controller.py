"""
 Copyright (c) 2024, Eeum, Inc.

 This software is licensed under the terms of the Revised BSD License.
 See LICENSE for details.
"""

from typing import Optional, Tuple, List
from asyncio import create_task, gather
from dataclasses import dataclass
from enum import Enum, auto
from math import log2

from opencis.util.logger import logger
from opencis.util.component import RunnableComponent
from opencis.cxl.transport.memory_fifo import (
    MemoryFifoPair,
    MEMORY_REQUEST_TYPE,
    MemoryResponse,
    MEMORY_RESPONSE_STATUS,
)
from opencis.cxl.transport.cache_fifo import (
    CacheFifoPair,
    CacheRequest,
    CACHE_REQUEST_TYPE,
    CacheResponse,
    CACHE_RESPONSE_STATUS,
)


class MEM_ADDR_TYPE(Enum):
    DRAM = auto()
    CFG = auto()
    MMIO = auto()
    CXL_CACHED = auto()
    CXL_CACHED_BI = auto()
    CXL_UNCACHED = auto()
    OOB = auto()


@dataclass
class MemoryRange:
    base_addr: int
    size: int
    addr_type: MEM_ADDR_TYPE


class COH_STATE_MACHINE(Enum):
    COH_STATE_INIT = auto()
    COH_STATE_START = auto()
    COH_STATE_WAIT = auto()
    COH_STATE_DONE = auto()


@dataclass
class CohStateMachine:
    state: COH_STATE_MACHINE
    packet: None
    cache_rsp: CACHE_RESPONSE_STATUS
    cache_list: list
    birsp_sched: bool


class CacheCheck(Enum):
    CACHE_HIT = auto()
    CACHE_MISS = auto()


class CacheState(Enum):
    CACHE_INVALID = auto()
    CACHE_SHARED = auto()
    CACHE_EXCLUSIVE = auto()
    CACHE_MODIFIED = auto()


@dataclass
class CacheBlock:
    state: CacheState = CacheState.CACHE_INVALID
    tag: int = 0
    priority: int = 0
    data: int = 0


@dataclass
class SetCounter:
    counter: int = 0


@dataclass
class CacheControllerConfig:
    component_name: str
    processor_to_cache_fifo: MemoryFifoPair
    cache_to_coh_agent_fifo: CacheFifoPair
    coh_agent_to_cache_fifo: CacheFifoPair
    cache_to_coh_bridge_fifo: CacheFifoPair = None
    coh_bridge_to_cache_fifo: CacheFifoPair = None
    cache_num_assoc: Optional[int] = 4
    cache_num_set: Optional[int] = 8


class CacheController(RunnableComponent):
    def __init__(self, config: CacheControllerConfig):
        self._component_name = config.component_name
        super().__init__(lambda class_name: f"{config.component_name}:{class_name}")

        self._cache_blk_bit = 6
        self._cache_blk_size = 1 << self._cache_blk_bit

        self._cache_assoc_size = config.cache_num_assoc
        self._cache_assoc_bit = int(log2(self._cache_assoc_size))
        assert self._cache_assoc_size == (1 << self._cache_assoc_bit)

        self._cache_set_size = config.cache_num_set
        self._cache_set_bit = int(log2(self._cache_set_size))
        assert self._cache_set_size == (1 << self._cache_set_bit)

        # cache controller connections within CXL complex host module
        self._processor_to_cache_fifo = config.processor_to_cache_fifo
        self._cache_to_coh_agent_fifo = config.cache_to_coh_agent_fifo
        self._coh_agent_to_cache_fifo = config.coh_agent_to_cache_fifo
        self._cache_to_coh_bridge_fifo = config.cache_to_coh_bridge_fifo
        self._coh_bridge_to_cache_fifo = config.coh_bridge_to_cache_fifo

        self._memory_ranges: List[MemoryRange] = []

        self.init_cache()
        logger.debug(self._create_message(f"{config.component_name} LLC Generated"))

    def init_cache(self) -> None:
        # simple cache structure
        self._cache = [
            [CacheBlock() for assoc in range(self._cache_assoc_size)]
            for set in range(self._cache_set_size)
        ]
        # for cache block eviction algorithm
        self._setcnt = [SetCounter() for set in range(self._cache_set_size)]

        self._blk_mask = self._cache_blk_size - 1
        self._set_mask = (self._cache_set_size - 1) << self._cache_blk_bit
        self._tag_mask = ~(self._set_mask | self._blk_mask)

    def get_memory_ranges(self):
        return self._memory_ranges

    def add_mem_range(self, addr: int, size: int, addr_type: MEM_ADDR_TYPE):
        logger.info(
            self._create_message(f"Adding MemoryRange addr: 0x{addr:x} addr_type: {addr_type.name}")
        )
        self._memory_ranges.append(MemoryRange(base_addr=addr, size=size, addr_type=addr_type))

    def remove_mem_range(self, base_addr: int, size: int, addr_type: MEM_ADDR_TYPE):
        r = MemoryRange(base_addr, size, addr_type)
        if r in self._memory_ranges:
            logger.info(
                self._create_message(
                    f"Removing MemoryRange addr: 0x{base_addr:x} addr_type: {addr_type.name}"
                )
            )
            self._memory_ranges.remove(r)
            return
        logger.error(
            self._create_message(f"MemoryRange addr:{base_addr} {addr_type.name} not found.")
        )

    def _get_mem_range(self, addr: int) -> MemoryRange:
        for range in self._memory_ranges:
            if range.base_addr <= addr < (range.base_addr + range.size):
                return range
        logger.warning(self._create_message(f"0x{addr:x} is OOB"))
        return None

    def get_mem_range(self, addr: int) -> MemoryRange:
        return self._get_mem_range(addr)

    def get_mem_addr_type(self, addr: int) -> MEM_ADDR_TYPE:
        r = self._get_mem_range(addr)
        if not r:
            return MEM_ADDR_TYPE.OOB
        return r.addr_type

    def _cache_priority_update(self, set: int, blk: int) -> None:
        self._cache[set][blk].priority = self._setcnt[set].counter
        self._setcnt[set].counter += 1

    def _cache_extract_tag(self, addr: int) -> int:
        return (addr & self._tag_mask) >> (self._cache_set_bit + self._cache_blk_bit)

    def _cache_extract_set(self, addr: int) -> int:
        return (addr & self._set_mask) >> self._cache_blk_bit

    def _cache_extract_block_state(self, set: int, blk: int) -> CacheState:
        return self._cache[set][blk].state

    def _cache_assem_addr(self, set: int, blk: int) -> int:
        tag = self._cache[set][blk].tag
        assert self._cache[set][blk].state != CacheState.CACHE_INVALID

        return tag << (self._cache_set_bit + self._cache_blk_bit) | set << self._cache_blk_bit

    def _cache_update_block_state(self, tag: int, set: int, blk: int, state: CacheState) -> None:
        if state != CacheState.CACHE_INVALID:
            self._cache_priority_update(set, blk)

        self._cache[set][blk].tag = tag
        self._cache[set][blk].state = state

    def _cache_find_replace_block(self, set: int) -> Tuple[int, CacheState]:
        min_priority = self._cache[set][0].priority
        min_idx = 0

        for idx in range(1, self._cache_assoc_size):
            if self._cache[set][idx].priority < min_priority:
                min_priority = self._cache[set][idx].priority
                min_idx = idx

        return min_idx, self._cache[set][min_idx].state

    def _cache_find_invalid_block(self, set: int) -> int:
        for blk in range(self._cache_assoc_size):
            if self._cache[set][blk].state == CacheState.CACHE_INVALID:
                return blk

        return None

    def _cache_find_valid_block(self, tag: int, set: int) -> Tuple[int, CacheState]:
        for blk in range(self._cache_assoc_size):
            if (self._cache[set][blk].tag == tag) and (
                self._cache[set][blk].state != CacheState.CACHE_INVALID
            ):
                return blk, self._cache[set][blk].state

        return None, None

    def _cache_data_read(self, set: int, blk: int) -> int:
        self._cache_priority_update(set, blk)

        return self._cache[set][blk].data

    def _cache_data_write(self, set: int, blk: int, data: int) -> None:
        self._cache_priority_update(set, blk)
        self._cache[set][blk].data = data

    def _cache_rsp_state_lookup(self, packet: CacheResponse) -> CacheState:
        if packet.status == CACHE_RESPONSE_STATUS.OK:
            cache_state = CacheState.CACHE_EXCLUSIVE
        elif packet.status == CACHE_RESPONSE_STATUS.RSP_S:
            cache_state = CacheState.CACHE_SHARED
        elif packet.status == CACHE_RESPONSE_STATUS.RSP_E:
            cache_state = CacheState.CACHE_EXCLUSIVE
        elif packet.status == CACHE_RESPONSE_STATUS.RSP_I:
            cache_state = CacheState.CACHE_EXCLUSIVE
        elif packet.status == CACHE_RESPONSE_STATUS.RSP_V:
            cache_state = CacheState.CACHE_INVALID
        elif packet.status == CACHE_RESPONSE_STATUS.RSP_M:
            cache_state = CacheState.CACHE_MODIFIED
        return cache_state

    def _get_cache_fifo(self, addr: int) -> CacheFifoPair:
        if self._processor_to_cache_fifo is None:
            # device-side cache controller
            return self._cache_to_coh_agent_fifo

        # host-side cache controller
        addr_type = self.get_mem_addr_type(addr)
        match addr_type:
            case MEM_ADDR_TYPE.DRAM:
                return self._cache_to_coh_bridge_fifo
            case MEM_ADDR_TYPE.CXL_CACHED | MEM_ADDR_TYPE.CXL_CACHED_BI:
                return self._cache_to_coh_agent_fifo
            case _:
                raise Exception(f"OOB Memory Address: 0x{addr:x}")

    async def _memory_load(self, addr: int, size: int) -> CacheResponse:
        cache_fifo = self._get_cache_fifo(addr)
        packet = CacheRequest(CACHE_REQUEST_TYPE.SNP_DATA, addr, size)
        await cache_fifo.request.put(packet)
        packet = await cache_fifo.response.get()
        return packet

    async def _memory_store(self, addr: int, size: int, prev_state: CacheState, value) -> None:
        cache_fifo = self._get_cache_fifo(addr)
        # Check for dirtiness, use WRITE_BACK_CLEAN if clean
        if prev_state == CacheState.CACHE_MODIFIED:
            packet = CacheRequest(CACHE_REQUEST_TYPE.WRITE_BACK, addr, size, value)
        else:
            packet = CacheRequest(CACHE_REQUEST_TYPE.WRITE_BACK_CLEAN, addr, size, value)
        await cache_fifo.request.put(packet)
        await cache_fifo.response.get()

    # For request: coherency tasks from cache controller to coh module
    async def _cache_to_coh_state_lookup(self, addr: int) -> None:
        if self._processor_to_cache_fifo is None:
            # device-side cache controller
            cache_fifo = self._cache_to_coh_agent_fifo
        else:
            # host-side cache controller
            addr_type = self.get_mem_addr_type(addr)
            if addr_type == MEM_ADDR_TYPE.DRAM:
                cache_fifo = self._cache_to_coh_bridge_fifo
            elif addr_type == MEM_ADDR_TYPE.CXL_CACHED_BI:
                cache_fifo = self._cache_to_coh_agent_fifo
            else:
                # no need to send SNP_INV
                return

        packet = CacheRequest(CACHE_REQUEST_TYPE.SNP_INV, addr)
        await cache_fifo.request.put(packet)
        packet = await cache_fifo.response.get()
        assert packet.status == CACHE_RESPONSE_STATUS.RSP_I

    # For response: coherency tasks from coh module to cache controller
    async def _coh_to_cache_state_lookup(
        self, type: CACHE_REQUEST_TYPE, addr: int
    ) -> Tuple[int, int, CacheState]:
        data = 0
        tag = self._cache_extract_tag(addr)
        set = self._cache_extract_set(addr)

        cache_blk, prev_state = self._cache_find_valid_block(tag, set)
        if cache_blk is not None:
            data = self._cache_data_read(set, cache_blk)
            if type == CACHE_REQUEST_TYPE.SNP_DATA:
                self._cache_update_block_state(tag, set, cache_blk, CacheState.CACHE_SHARED)
            elif type == CACHE_REQUEST_TYPE.SNP_INV:
                self._cache_update_block_state(tag, set, cache_blk, CacheState.CACHE_INVALID)
            elif type == CACHE_REQUEST_TYPE.SNP_CUR:
                pass
            elif type == CACHE_REQUEST_TYPE.WRITE_BACK:
                assert self._cache_extract_block_state(set, cache_blk) == CacheState.CACHE_SHARED

        return cache_blk, data, prev_state

    # cache access for read
    async def cache_coherent_load(self, addr: int, size: int) -> int:
        assert size == self._cache_blk_size

        tag = self._cache_extract_tag(addr)
        set = self._cache_extract_set(addr)

        cache_blk, _ = self._cache_find_valid_block(tag, set)
        if cache_blk is not None:
            # cache hit
            data = self._cache_data_read(set, cache_blk)
        else:
            # cache miss
            cache_blk = self._cache_find_invalid_block(set)

            # cache block full
            if cache_blk is None:
                cache_blk, prev_state = self._cache_find_replace_block(set)
                assem_addr = self._cache_assem_addr(set, cache_blk)
                cached_data = self._cache_data_read(set, cache_blk)

                # cacheline flush to secure space
                await self._memory_store(assem_addr, size, prev_state, cached_data)
                self._cache_update_block_state(tag, set, cache_blk, CacheState.CACHE_INVALID)

            # coherency check whenever inserting a cache block
            # snoop_data to get mesi response
            packet = await self._memory_load(addr, size)
            data = packet.data

            cache_state = self._cache_rsp_state_lookup(packet)
            if cache_state == CacheState.CACHE_INVALID:
                return data

            assert self._cache_extract_block_state(set, cache_blk) == CacheState.CACHE_INVALID
            self._cache_update_block_state(tag, set, cache_blk, cache_state)
            self._cache_data_write(set, cache_blk, data)

        return data

    # cache access for write
    async def cache_coherent_store(self, addr: int, size: int, data: int) -> None:
        assert size == self._cache_blk_size

        tag = self._cache_extract_tag(addr)
        set = self._cache_extract_set(addr)

        cache_blk, _ = self._cache_find_valid_block(tag, set)
        if cache_blk is not None:
            # cache hit
            cache_state = self._cache_extract_block_state(set, cache_blk)
            assert cache_state != CacheState.CACHE_INVALID

            if cache_state == CacheState.CACHE_SHARED:
                # can be real shared or exclusive-shared
                await self._cache_to_coh_state_lookup(addr)
                self._cache_update_block_state(tag, set, cache_blk, CacheState.CACHE_EXCLUSIVE)

            self._cache_update_block_state(tag, set, cache_blk, CacheState.CACHE_MODIFIED)
            self._cache_data_write(set, cache_blk, data)
        else:
            # cache miss
            cache_blk = self._cache_find_invalid_block(set)

            # cache block full
            if cache_blk is None:
                cache_blk, prev_state = self._cache_find_replace_block(set)
                assem_addr = self._cache_assem_addr(set, cache_blk)
                cached_data = self._cache_data_read(set, cache_blk)

                # cacheline flush to secure space
                await self._memory_store(assem_addr, size, prev_state, cached_data)
                self._cache_update_block_state(tag, set, cache_blk, CacheState.CACHE_INVALID)

            # coherency check whenever inserting a cache block
            # always snoop_invalidate for now
            await self._cache_to_coh_state_lookup(addr)

            # todo: read memory if partial update is supported
            self._cache_update_block_state(tag, set, cache_blk, CacheState.CACHE_MODIFIED)
            self._cache_data_write(set, cache_blk, data)

    async def _uncached_load(self, addr: int, size: int) -> int:
        packet = CacheRequest(CACHE_REQUEST_TYPE.UNCACHED_READ, addr, size)
        await self._cache_to_coh_agent_fifo.request.put(packet)
        resp = await self._cache_to_coh_agent_fifo.response.get()
        return resp.data

    async def _uncached_store(self, addr: int, size: int, data: int) -> int:
        packet = CacheRequest(CACHE_REQUEST_TYPE.UNCACHED_WRITE, addr, size, data)
        await self._cache_to_coh_agent_fifo.request.put(packet)
        await self._cache_to_coh_agent_fifo.response.get()

    # registered event loop for processor's cache load/store operations
    async def _processor_request_scheduler(self):
        while True:
            packet = await self._processor_to_cache_fifo.request.get()
            if packet is None:
                logger.debug(
                    self._create_message("Stop processing processor request scheduler fifo")
                )
                break

            match packet.type:
                case MEMORY_REQUEST_TYPE.READ:
                    data = await self.cache_coherent_load(packet.addr, packet.size)
                    packet = MemoryResponse(MEMORY_RESPONSE_STATUS.OK, data)
                    await self._processor_to_cache_fifo.response.put(packet)

                case MEMORY_REQUEST_TYPE.UNCACHED_READ:
                    data = await self._uncached_load(packet.addr, packet.size)
                    packet = MemoryResponse(MEMORY_RESPONSE_STATUS.OK, data)
                    await self._processor_to_cache_fifo.response.put(packet)

                case MEMORY_REQUEST_TYPE.WRITE:
                    await self.cache_coherent_store(packet.addr, packet.size, packet.data)
                    packet = MemoryResponse(MEMORY_RESPONSE_STATUS.OK)
                    await self._processor_to_cache_fifo.response.put(packet)

                case MEMORY_REQUEST_TYPE.UNCACHED_WRITE:
                    await self._uncached_store(packet.addr, packet.size, packet.data)
                    packet = MemoryResponse(MEMORY_RESPONSE_STATUS.OK)
                    await self._processor_to_cache_fifo.response.put(packet)

                case _:
                    assert False

    async def _run_coh_request(self, packet: CacheRequest, cache_fifo: CacheFifoPair):
        cache_blk, data, prev_state = await self._coh_to_cache_state_lookup(
            packet.type, packet.addr
        )
        if cache_blk is None:
            packet = CacheResponse(CACHE_RESPONSE_STATUS.RSP_MISS, data)
        elif packet.type == CACHE_REQUEST_TYPE.SNP_DATA:
            rsp_status = CACHE_RESPONSE_STATUS.RSP_S
            if prev_state == CacheState.CACHE_MODIFIED:
                rsp_status = CACHE_RESPONSE_STATUS.RSP_M
            elif prev_state == CacheState.CACHE_EXCLUSIVE:
                rsp_status = CACHE_RESPONSE_STATUS.RSP_E
            packet = CacheResponse(rsp_status, data)
        elif packet.type == CACHE_REQUEST_TYPE.SNP_INV:
            packet = CacheResponse(CACHE_RESPONSE_STATUS.RSP_I, data)
        elif packet.type == CACHE_REQUEST_TYPE.SNP_CUR:
            packet = CacheResponse(CACHE_RESPONSE_STATUS.RSP_V, data)
        elif packet.type == CACHE_REQUEST_TYPE.WRITE_BACK:
            packet = CacheResponse(CACHE_RESPONSE_STATUS.RSP_V, data)
        else:
            assert False
        await cache_fifo.response.put(packet)

    # registered event loop for coh module's cache loopup operations
    async def _coh_agent_request_scheduler(self):
        while True:
            packet = await self._coh_agent_to_cache_fifo.request.get()
            if packet is None:
                logger.debug(
                    self._create_message("Stop processing coh agent request scheduler fifo")
                )
                break
            await self._run_coh_request(packet, self._coh_agent_to_cache_fifo)

    async def _coh_bridge_request_scheduler(self):
        while True:
            packet = await self._coh_bridge_to_cache_fifo.request.get()
            if packet is None:
                logger.debug(
                    self._create_message("Stop processing coh bridge request scheduler fifo")
                )
                break
            await self._run_coh_request(packet, self._coh_bridge_to_cache_fifo)

    async def _run(self):
        tasks = [
            create_task(self._coh_agent_request_scheduler()),
        ]
        if self._processor_to_cache_fifo:
            tasks.append(create_task(self._processor_request_scheduler()))
        if self._cache_to_coh_bridge_fifo:
            tasks.append(create_task(self._coh_bridge_request_scheduler()))
        await self._change_status_to_running()
        await gather(*tasks)

    async def _stop(self):
        if self._processor_to_cache_fifo:
            await self._processor_to_cache_fifo.request.put(None)
        if self._coh_bridge_to_cache_fifo:
            await self._coh_bridge_to_cache_fifo.request.put(None)
        await self._coh_agent_to_cache_fifo.request.put(None)
