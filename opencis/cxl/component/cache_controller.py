"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

import time
from typing import Optional, Tuple, List
from asyncio import create_task, gather, sleep
from dataclasses import dataclass, field
from enum import Enum, auto
from math import log2
import copy

from click import pause

from opencis.cxl.transport.transaction import CXL_CACHE_D2HRSP_OPCODE
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


MAX_INT = pow(2, (8 * 64)) - 1


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

    def __hash__(self):
        return hash((self.base_addr, self.size, self.addr_type))


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
    cxl_rsp: CXL_CACHE_D2HRSP_OPCODE
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
    priority: float = 0
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
    cache_num_assoc: List[int] = field(default_factory=list)
    cache_num_set: List[int] = field(default_factory=list)


class CacheController(RunnableComponent):
    def __init__(self, config: CacheControllerConfig):
        self._component_name = config.component_name
        super().__init__(lambda class_name: f"{config.component_name}:{class_name}")

        # General, 64-byte cache lines for all cache levels
        self._cache_blk_bit = 6
        self._cache_blk_size = 1 << self._cache_blk_bit

        self._cache_assoc_size = config.cache_num_assoc
        self._cache_assoc_bit = [int(log2(s)) for s in self._cache_assoc_size]
        for i in range(len(self._cache_assoc_bit)):
            assert self._cache_assoc_size[i] == (1 << self._cache_assoc_bit[i])

        self._cache_set_size = config.cache_num_set
        self._cache_set_bit = [int(log2(s)) for s in self._cache_set_size]
        for i in range(len(self._cache_set_bit)):
            assert self._cache_set_size[i] == (1 << self._cache_set_bit[i])

        assert len(self._cache_assoc_size) == len(self._cache_set_size)

        self._total_cache_level = len(self._cache_assoc_size)

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
        # L1 cache
        self._cache = [
            [
                [CacheBlock() for assoc in range(self._cache_assoc_size[i])]
                for set in range(self._cache_set_size[i])
            ]
            for i in range(len(self._cache_assoc_size))
        ]
        print((self._cache_assoc_size))
        # for cache block eviction algorithm
        self._setcnt = [
            [SetCounter() for set in range(self._cache_set_size[i])]
            for i in range(len(self._cache_set_size))
        ]
        print((self._cache_set_size))

        self._blk_mask = self._cache_blk_size - 1
        self._set_mask = [
            (self._cache_set_size[i] - 1) << self._cache_blk_bit
            for i in range(len(self._cache_set_size))
        ]
        self._tag_mask = [~(self._set_mask[i] | self._blk_mask) for i in range(len(self._set_mask))]

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

    def _cache_priority_update(self, level: int, set: int, blk: int) -> None:
        # self._cache[level][set][blk].priority = self._setcnt[level][set].counter
        # self._setcnt[level][set].counter += 1
        # Now use LRU, used to be LFU - easier for promote/demote
        self._cache[level][set][blk].priority = float(time.time())

    def _cache_extract_tag(self, level: int, addr: int) -> int:
        return (addr & self._tag_mask[level]) >> (self._cache_set_bit[level] + self._cache_blk_bit)

    def _cache_extract_set(self, level: int, addr: int) -> int:
        return (addr & self._set_mask[level]) >> self._cache_blk_bit

    def _cache_extract_block_state(self, level: int, set: int, blk: int) -> CacheState:
        return self._cache[level][set][blk].state

    def _cache_assem_addr(self, level: int, set: int, blk: int) -> int:
        tag = self._cache[level][set][blk].tag
        assert self._cache[level][set][blk].state != CacheState.CACHE_INVALID

        return (
            tag << (self._cache_set_bit[level] + self._cache_blk_bit) | set << self._cache_blk_bit
        )

    def _cache_update_block_state(
        self, level: int, tag: int, set: int, blk: int, state: CacheState
    ) -> None:
        if state != CacheState.CACHE_INVALID:
            self._cache_priority_update(level, set, blk)

        self._cache[level][set][blk].tag = tag
        self._cache[level][set][blk].state = state

    def _cache_find_replace_block(self, level: int, set: int) -> Tuple[int, CacheState]:
        min_priority = self._cache[level][set][0].priority
        min_idx = 0

        for idx in range(1, self._cache_assoc_size[level]):
            if self._cache[level][set][idx].priority < min_priority:
                min_priority = self._cache[level][set][idx].priority
                min_idx = idx

        return min_idx, self._cache[level][set][min_idx].state

    def _cache_find_invalid_block(self, level: int, set: int) -> int:
        for blk in range(self._cache_assoc_size[level]):
            if self._cache[level][set][blk].state == CacheState.CACHE_INVALID:
                return blk

        return None

    def _cache_find_valid_block(self, level: int, tag: int, set: int) -> int:
        for blk in range(self._cache_assoc_size[level]):
            if (self._cache[level][set][blk].tag == tag) and (
                self._cache[level][set][blk].state != CacheState.CACHE_INVALID
            ):
                return blk

        return None

    def _cache_check_block_state(self, level: int, set: int, blk: int) -> CacheState:
        return self._cache[level][set][blk].state

    def _cache_data_read(self, level: int, set: int, blk: int) -> int:
        self._cache_priority_update(level, set, blk)

        return self._cache[level][set][blk].data

    def _cache_data_write(self, level: int, set: int, blk: int, data: int) -> None:
        self._cache_priority_update(level, set, blk)
        self._cache[level][set][blk].data = data

    async def _cache_data_promote_to_l1(self, addr: int, level: int, blk: int):
        if level == 0:
            return blk
        set_l1 = self._cache_extract_set(0, addr)
        set_level = self._cache_extract_set(level, addr)

        # Invalid original data so we have free space in that level
        # Reduce possible memory write backs
        source_info = copy.deepcopy(self._cache[level][set_level][blk])
        self._cache_update_block_state(level, 0, set_level, blk, CacheState.CACHE_INVALID)

        target = self._cache_find_invalid_block(0, set_l1)
        if target is None:
            await self._cache_data_demote(0, addr)
            target = self._cache_find_invalid_block(0, set_l1)
            assert target is not None
        self._cache[0][set_l1][target] = source_info
        # Update tag
        tag = self._cache_extract_tag(0, addr)
        self._cache_update_block_state(0, tag, set_l1, target, source_info.state)
        return target

    async def _cache_data_demote(self, level: int, addr: int):
        if level >= self._total_cache_level:
            raise Exception(f"No {level + 1} level cache!")

        set_level = self._cache_extract_set(level, addr)
        cache_blk = self._cache_find_invalid_block(level, set_level)
        if cache_blk is not None:
            return

        cache_blk, prev_state = self._cache_find_replace_block(level, set_level)
        assem_addr = self._cache_assem_addr(level, set_level, cache_blk)
        cached_data = self._cache_data_read(level, set_level, cache_blk)

        if level + 1 == self._total_cache_level:
            # cacheline flush to secure space
            await self._memory_store(assem_addr, 64, prev_state, cached_data)
        else:
            set_level_plus_one = self._cache_extract_set(level + 1, addr)
            await self._cache_data_demote(level + 1, addr)
            target = self._cache_find_invalid_block(level + 1, set_level_plus_one)
            assert target is not None

            self._cache[level + 1][set_level_plus_one][target] = copy.deepcopy(
                self._cache[level][set_level][cache_blk]
            )
            # Update tag
            tag = self._cache_extract_tag(level + 1, addr)
            self._cache[level + 1][set_level_plus_one][target].tag = tag
        self._cache_update_block_state(level, 0, set_level, cache_blk, CacheState.CACHE_INVALID)
        return

    def _cache_rsp_state_lookup(self, packet: CacheResponse) -> CacheState:
        if packet.status == CACHE_RESPONSE_STATUS.OK:
            cache_state = CacheState.CACHE_EXCLUSIVE
        elif packet.status == CACHE_RESPONSE_STATUS.RSP_S:
            cache_state = CacheState.CACHE_SHARED
        elif packet.status == CACHE_RESPONSE_STATUS.RSP_E:
            cache_state = CacheState.CACHE_EXCLUSIVE
        elif packet.status == CACHE_RESPONSE_STATUS.RSP_I:
            cache_state = CacheState.CACHE_INVALID
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
    async def _cache_to_coh_state_lookup(self, addr: int, op=CACHE_REQUEST_TYPE.SNP_INV):
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

        packet = CacheRequest(op, addr)
        await cache_fifo.request.put(packet)
        # print("Received Response Packet!!!")
        packet = await cache_fifo.response.get()
        # # print(f"Packet received data: {packet.data:0128x}")
        # assert packet.status == CACHE_RESPONSE_STATUS.RSP_I

        return packet.status, packet.data

    # For response: coherency tasks from coh module to cache controller
    async def _coh_to_cache_state_lookup(
        self, type: CACHE_REQUEST_TYPE, addr: int
    ) -> Tuple[int, int, CacheState, int]:
        data = 0
        level = 0

        for l in range(self._total_cache_level):
            level = l
            tag = self._cache_extract_tag(level, addr)
            set = self._cache_extract_set(level, addr)

            cache_blk = self._cache_find_valid_block(level, tag, set)

        prev_state = None
        if cache_blk is not None:
            prev_state = self._cache_check_block_state(level, set, cache_blk)
            # print(f"state lookup for {self._component_name}")
            # while prev_state == CacheState.CACHE_WAITING:
            #     await sleep(0)
            data = self._cache_data_read(level, set, cache_blk)
            if type == CACHE_REQUEST_TYPE.SNP_DATA:
                self._cache_update_block_state(level, tag, set, cache_blk, CacheState.CACHE_SHARED)
            elif type == CACHE_REQUEST_TYPE.SNP_INV:
                # print(f"{self._component_name} Invalidating...")
                self._cache_update_block_state(level, tag, set, cache_blk, CacheState.CACHE_INVALID)
            elif type == CACHE_REQUEST_TYPE.SNP_CUR:
                pass
            elif type == CACHE_REQUEST_TYPE.WRITE_BACK:
                assert (
                    self._cache_extract_block_state(level, set, cache_blk)
                    == CacheState.CACHE_SHARED
                )

        return cache_blk, data, prev_state, level

    # cache access for read
    async def cache_coherent_load(self, addr: int, size: int) -> int:
        assert size == self._cache_blk_size

        level = 0
        for l in range(self._total_cache_level):
            level = l
            tag = self._cache_extract_tag(level, addr)
            set = self._cache_extract_set(level, addr)
            cache_blk = self._cache_find_valid_block(level, tag, set)

        if cache_blk is not None:
            # cache hit
            cache_blk = await self._cache_data_promote_to_l1(addr, level, cache_blk)
            set = self._cache_extract_set(0, addr)
            data = self._cache_data_read(0, set, cache_blk)
        else:
            # cache miss
            tag = self._cache_extract_tag(0, addr)
            set = self._cache_extract_set(0, addr)
            await self._cache_data_demote(0, addr)

            # coherency check whenever inserting a cache block
            # snoop_data to get mesi response
            packet = await self._memory_load(addr, size)
            data = packet.data

            cache_state = self._cache_rsp_state_lookup(packet)
            if cache_state == CacheState.CACHE_INVALID:
                return data

            cache_blk = self._cache_find_invalid_block(0, set)

            assert self._cache_extract_block_state(0, set, cache_blk) == CacheState.CACHE_INVALID
            self._cache_update_block_state(0, tag, set, cache_blk, cache_state)
            self._cache_data_write(0, set, cache_blk, data)

        return data

    async def cache_coherent_partial_store(self, addr: int, size: int, data: int):
        # # print(f"{self._component_name} start cache_coherent_partial_store 1")
        # mask_offset = (64 - (addr % 64) - size) * 8
        mask_offset = (addr % 64) * 8
        # # print(f"{self._component_name} start cache_coherent_partial_store 2")

        mask = (pow(2, (size * 8)) - 1) << mask_offset
        # print(f"size = {size}, mask_offset = {mask_offset}, mask = {mask:0128x}")
        # # print(f"{self._component_name} start cache_coherent_partial_store 3")
        data = (data << mask_offset) & mask
        # # print(f"{self._component_name} start cache_coherent_partial_store 4")
        aligned_addr = addr - (addr % 64)
        # # print(f"{self._component_name} start cache_coherent_partial_store 5")
        await self.cache_coherent_store(aligned_addr, 64, data, mask)
        # # print(f"{self._component_name} Finished cache_coherent_partial_store")
        # Allows partial store to a cache block

    # cache access for write
    async def cache_coherent_store(
        self, addr: int, size: int, data: int, mask: int = MAX_INT
    ) -> None:
        revert_mask = MAX_INT - mask
        # print(
        #     f"Dev {self._component_name} Doing cache_coherent_store at 0x{addr:08x}, data: 0x{data:0128x}"
        # )
        assert size == self._cache_blk_size

        request_opcode = CACHE_REQUEST_TYPE.RD_OWN
        if mask == MAX_INT:
            # RD_OWN for partial cache line updates
            # RD_OWN_NO_DATA for full updates (overwriting anyway)
            # See 3.2.4.2.10 (Note)
            request_opcode = CACHE_REQUEST_TYPE.RD_OWN_NO_DATA

        level = 0
        for l in range(self._total_cache_level):
            level = l
            tag = self._cache_extract_tag(level, addr)
            set = self._cache_extract_set(level, addr)
            cache_blk = self._cache_find_valid_block(level, tag, set)

        remote_data = None
        if cache_blk is not None:
            # print("Cache hit")
            # cache hit
            cache_blk = await self._cache_data_promote_to_l1(addr, level, cache_blk)
            level = 0  # Now promoted to L1 Cache
            tag = self._cache_extract_tag(0, addr)
            set = self._cache_extract_set(0, addr)
            cache_state = self._cache_extract_block_state(level, set, cache_blk)
            assert cache_state != CacheState.CACHE_INVALID
            if cache_state == CacheState.CACHE_SHARED:
                # can be real shared or exclusive-shared
                # print(f"{self._component_name} getting new state")
                new_state, remote_data = await self._cache_to_coh_state_lookup(addr, request_opcode)
                if remote_data is not None:
                    self._cache_data_write(level, set, cache_blk, remote_data)
                else:
                    remote_data = self._cache_data_read(level, set, cache_blk)

                cache_state = self._cache_extract_block_state(level, set, cache_blk)
                # print(f"{self._component_name} Returned cache state: {new_state}")
                # print(f"Middle cache state: {cache_state}")
                self._cache_update_block_state(
                    level, tag, set, cache_blk, CacheState.CACHE_EXCLUSIVE
                )
            else:
                if mask != MAX_INT:
                    remote_data = self._cache_data_read(level, set, cache_blk)

            # Update data base on mask

            self._cache_update_block_state(level, tag, set, cache_blk, CacheState.CACHE_MODIFIED)
            cache_state = self._cache_extract_block_state(level, set, cache_blk)

            if remote_data is not None:
                # print(f"remote data: 0x{remote_data:0128x}")
                # print(f"mask: {mask:0128x}")
                # print(f"revert mask: {revert_mask:0128x}")
                # print(f"masked: {(remote_data & revert_mask):0128x}")
                data = (remote_data & revert_mask) | (data & mask)
            # print(f"new data: 0x{data:0128x}")

            self._cache_data_write(level, set, cache_blk, data)
        else:
            # print("Cache miss")
            # cache miss
            await self._cache_data_demote(0, addr)
            tag = self._cache_extract_tag(0, addr)
            set = self._cache_extract_set(0, addr)
            cache_blk = self._cache_find_invalid_block(0, set)
            assert cache_blk is not None
            # coherency check whenever inserting a cache block
            new_state, remote_data = await self._cache_to_coh_state_lookup(addr, request_opcode)

            # todo: read memory if partial update is supported
            self._cache_update_block_state(0, tag, set, cache_blk, CacheState.CACHE_MODIFIED)
            if remote_data is not None:
                data = (remote_data & revert_mask) | (data & mask)
                # print(f"old remote data: 0x{remote_data:0128x}")
            # print(f"new data: 0x{data:0128x}")
            self._cache_data_write(0, set, cache_blk, data)
        # print(
        #     f"Dev {self._component_name} Finished cache_coherent_store at 0x{addr:08x}, data: 0x{data:0128x}"
        # )

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
        cache_blk, data, prev_state, level = await self._coh_to_cache_state_lookup(
            packet.type, packet.addr
        )
        if cache_blk is None:
            packet = CacheResponse(CACHE_RESPONSE_STATUS.RSP_MISS, data)
        elif packet.type == CACHE_REQUEST_TYPE.SNP_DATA:
            rsp_status = CACHE_RESPONSE_STATUS.RSP_S
            packet = CacheResponse(rsp_status, data, prev_state)
        elif packet.type == CACHE_REQUEST_TYPE.SNP_INV:
            packet = CacheResponse(CACHE_RESPONSE_STATUS.RSP_I, data, prev_state)
        elif packet.type == CACHE_REQUEST_TYPE.SNP_CUR:
            packet = CacheResponse(prev_state, data, prev_state)
        elif packet.type == CACHE_REQUEST_TYPE.WRITE_BACK:
            # 3.2.4.2.14 ~ 3.2.4.2.16
            # guarantee to the Host that the device no longer contains any cached copies of this line
            packet = CacheResponse(CACHE_RESPONSE_STATUS.RSP_I, data, prev_state)
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
