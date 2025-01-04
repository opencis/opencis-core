"""
 Copyright (c) 2024, Eeum, Inc.

 This software is licensed under the terms of the Revised BSD License.
 See LICENSE for details.
"""

import asyncio
import pytest

from opencis.cxl.component.cache_controller import (
    CacheController,
    CacheControllerConfig,
    MEM_ADDR_TYPE,
)
from opencis.cxl.transport.memory_fifo import (
    MemoryFifoPair,
    MemoryRequest,
    MemoryResponse,
    MEMORY_REQUEST_TYPE,
    MEMORY_RESPONSE_STATUS,
)
from opencis.cxl.transport.cache_fifo import (
    CacheFifoPair,
    CacheRequest,
    CACHE_REQUEST_TYPE,
    CacheResponse,
    CACHE_RESPONSE_STATUS,
)

# pylint: disable=protected-access, redefined-outer-name

CACHE_NUM_ASSOC = 4
CACHE_NUM_SETS = 1


@pytest.fixture
def cxl_host_cache_controller():
    config = CacheControllerConfig(
        component_name="MyDevice",
        processor_to_cache_fifo=MemoryFifoPair(),
        cache_to_coh_agent_fifo=CacheFifoPair(),
        coh_agent_to_cache_fifo=CacheFifoPair(),
        cache_to_coh_bridge_fifo=CacheFifoPair(),
        coh_bridge_to_cache_fifo=CacheFifoPair(),
        cache_num_assoc=CACHE_NUM_ASSOC,
        cache_num_set=CACHE_NUM_SETS,
    )
    return CacheController(config)


@pytest.fixture
def cxl_dcoh_cache_controller():
    config = CacheControllerConfig(
        component_name="MyDevice",
        processor_to_cache_fifo=None,
        cache_to_coh_agent_fifo=CacheFifoPair(),
        coh_agent_to_cache_fifo=CacheFifoPair(),
        cache_to_coh_bridge_fifo=None,
        coh_bridge_to_cache_fifo=None,
        cache_num_assoc=CACHE_NUM_ASSOC,
        cache_num_set=CACHE_NUM_SETS,
    )
    return CacheController(config)


async def send_cache_req(
    cc: CacheController,
    req: CacheRequest,
) -> MemoryResponse:
    if cc._processor_to_cache_fifo is None:
        cache_fifo = cc._coh_agent_to_cache_fifo
    else:
        if cc.get_mem_addr_type(req.addr) == MEM_ADDR_TYPE.DRAM:
            cache_fifo = cc._coh_bridge_to_cache_fifo
        else:
            cache_fifo = cc._coh_agent_to_cache_fifo
    await cache_fifo.request.put(req)
    resp = await cache_fifo.response.get()
    return resp


async def send_cached_mem_request(
    cc: CacheController,
    req: MemoryRequest,
    is_cache_wb: bool,
    is_cache_snp: bool = False,
) -> MemoryResponse:
    await cc._processor_to_cache_fifo.request.put(req)
    if is_cache_wb:
        cache_req = await cc._cache_to_coh_agent_fifo.request.get()
        await cc._cache_to_coh_agent_fifo.response.put(CacheResponse(CACHE_RESPONSE_STATUS.OK))
        assert cache_req.type == CACHE_REQUEST_TYPE.WRITE_BACK
    if is_cache_snp:
        cache_req = await cc._cache_to_coh_agent_fifo.request.get()
        await cc._cache_to_coh_agent_fifo.response.put(CacheResponse(CACHE_RESPONSE_STATUS.OK))
        assert cache_req.type == CACHE_REQUEST_TYPE.SNP_DATA
    resp = await cc._processor_to_cache_fifo.response.get()
    assert resp.status == MEMORY_RESPONSE_STATUS.OK
    return resp


async def send_uncached_mem_request(
    cc: CacheController,
    req: MemoryRequest,
) -> MemoryResponse:
    await cc._processor_to_cache_fifo.request.put(req)
    cache_req = await cc._cache_to_coh_agent_fifo.request.get()
    await cc._cache_to_coh_agent_fifo.response.put(CacheResponse(CACHE_RESPONSE_STATUS.OK))
    assert cache_req.type in (CACHE_REQUEST_TYPE.UNCACHED_WRITE, CACHE_REQUEST_TYPE.UNCACHED_READ)
    resp = await cc._processor_to_cache_fifo.response.get()
    assert resp.status == MEMORY_RESPONSE_STATUS.OK
    return resp


@pytest.mark.asyncio
async def test_cxl_host_cc_mem_req(cxl_host_cache_controller):
    cc: CacheController
    cc = cxl_host_cache_controller
    tasks = []
    tasks.append(asyncio.create_task(cc.run_wait_ready()))

    cc.add_mem_range(0x0, 0x1000, MEM_ADDR_TYPE.CXL_CACHED)

    # Fill cache blocks
    for i in range(CACHE_NUM_ASSOC):
        addr = i * 0x40
        req = MemoryRequest(MEMORY_REQUEST_TYPE.WRITE, addr, 0x40, 0x1111111111111111)
        await send_cached_mem_request(cc, req, False)

    # cache miss write: write-back only
    addr = CACHE_NUM_ASSOC * 0x40
    mem_req = MemoryRequest(MEMORY_REQUEST_TYPE.WRITE, addr, 0x40, 0xDEADBEEFDEADBEEF)
    resp = await send_cached_mem_request(cc, mem_req, True)

    # cache hit read
    addr = CACHE_NUM_ASSOC * 0x40
    req = MemoryRequest(MEMORY_REQUEST_TYPE.READ, addr, 0x40)
    resp = await send_cached_mem_request(cc, req, False, False)
    assert resp.data == 0xDEADBEEFDEADBEEF

    # cache miss read: write-back and snoop
    addr = 0
    req = MemoryRequest(MEMORY_REQUEST_TYPE.READ, addr, 0x40)
    resp = await send_cached_mem_request(cc, req, True, True)
    # assert resp.data == 0x1111111111111111

    # cache hit write
    addr = 0
    mem_req = MemoryRequest(MEMORY_REQUEST_TYPE.WRITE, addr, 0x40, 0xDEADBEEFDEADBEEF)
    resp = await send_cached_mem_request(cc, mem_req, False, False)

    await cc.stop()
    asyncio.gather(*tasks)


@pytest.mark.asyncio
async def test_cxl_host_cc_cache_invalid(cxl_host_cache_controller):
    cc: CacheController
    cc = cxl_host_cache_controller
    tasks = []
    tasks.append(asyncio.create_task(cc.run_wait_ready()))

    cc.add_mem_range(0, 0x1000, MEM_ADDR_TYPE.DRAM)
    cc.add_mem_range(0x1000, 0x1000, MEM_ADDR_TYPE.CXL_CACHED_BI)

    addr = 0
    mem_req = MemoryRequest(MEMORY_REQUEST_TYPE.WRITE, addr, 0x40, 0xDEADBEEFDEADBEEF)
    await cc._processor_to_cache_fifo.request.put(mem_req)
    cache_req = await cc._cache_to_coh_bridge_fifo.request.get()
    await cc._cache_to_coh_bridge_fifo.response.put(CacheResponse(CACHE_RESPONSE_STATUS.RSP_I))
    assert cache_req.type == CACHE_REQUEST_TYPE.SNP_INV
    await cc._processor_to_cache_fifo.response.get()

    addr = 0x1000
    mem_req = MemoryRequest(MEMORY_REQUEST_TYPE.WRITE, addr, 0x40, 0xDEADBEEFDEADBEEF)
    await cc._processor_to_cache_fifo.request.put(mem_req)
    cache_req = await cc._cache_to_coh_agent_fifo.request.get()
    await cc._cache_to_coh_agent_fifo.response.put(CacheResponse(CACHE_RESPONSE_STATUS.RSP_I))
    assert cache_req.type == CACHE_REQUEST_TYPE.SNP_INV
    await cc._processor_to_cache_fifo.response.get()

    await cc.stop()
    asyncio.gather(*tasks)


@pytest.mark.asyncio
async def test_cxl_host_cc_cache_req(cxl_host_cache_controller):
    cc: CacheController
    cc = cxl_host_cache_controller
    tasks = []
    tasks.append(asyncio.create_task(cc.run_wait_ready()))

    cc.add_mem_range(0x0, 0x1000, MEM_ADDR_TYPE.CXL_CACHED)

    # Fill cache blocks
    for i in range(CACHE_NUM_ASSOC):
        addr = i * 0x40
        req = MemoryRequest(MEMORY_REQUEST_TYPE.WRITE, addr, 0x40, 0x1111111111111111)
        await send_cached_mem_request(cc, req, False)

    # SNP_DATA
    req = CacheRequest(CACHE_REQUEST_TYPE.SNP_DATA, 0, 0x40)
    resp = await send_cache_req(cc, req)
    assert resp.status == CACHE_RESPONSE_STATUS.RSP_S

    # SNP_CUR
    req = CacheRequest(CACHE_REQUEST_TYPE.SNP_CUR, 0, 0x40)
    resp = await send_cache_req(cc, req)
    assert resp.status == CACHE_RESPONSE_STATUS.RSP_V

    # WRITE_BACK
    req = CacheRequest(CACHE_REQUEST_TYPE.WRITE_BACK, 0, 0x40)
    resp = await send_cache_req(cc, req)
    assert resp.status == CACHE_RESPONSE_STATUS.RSP_V

    # SNP_INV
    req = CacheRequest(CACHE_REQUEST_TYPE.SNP_INV, 0, 0x40)
    resp = await send_cache_req(cc, req)
    assert resp.status == CACHE_RESPONSE_STATUS.RSP_I

    # cache miss
    req = CacheRequest(CACHE_REQUEST_TYPE.SNP_DATA, 0x1000, 0x40)
    resp = await send_cache_req(cc, req)
    assert resp.status == CACHE_RESPONSE_STATUS.RSP_MISS

    await cc.stop()
    asyncio.gather(*tasks)


@pytest.mark.asyncio
async def test_cxl_host_cc_cxl_uncached(cxl_host_cache_controller):
    cc: CacheController
    cc = cxl_host_cache_controller
    tasks = []
    tasks.append(asyncio.create_task(cc.run_wait_ready()))

    cc.add_mem_range(0x0, 0x1000, MEM_ADDR_TYPE.CXL_UNCACHED)

    addr = 0
    mem_req = MemoryRequest(MEMORY_REQUEST_TYPE.UNCACHED_WRITE, addr, 0x40, 0xDEADBEEFDEADBEEF)
    await send_uncached_mem_request(cc, mem_req)

    addr = 0
    mem_req = MemoryRequest(MEMORY_REQUEST_TYPE.UNCACHED_READ, addr, 0x40)
    await send_uncached_mem_request(cc, mem_req)

    await cc.stop()
    asyncio.gather(*tasks)


@pytest.mark.asyncio
async def test_cxl_dcoh_cc_cache_req(cxl_dcoh_cache_controller):
    cc: CacheController
    cc = cxl_dcoh_cache_controller
    tasks = []
    tasks.append(asyncio.create_task(cc.run_wait_ready()))

    # SNP_DATA
    req = CacheRequest(CACHE_REQUEST_TYPE.SNP_DATA, 0, 0x40)
    resp = await send_cache_req(cc, req)
    assert resp.status == CACHE_RESPONSE_STATUS.RSP_MISS

    await cc.stop()
    asyncio.gather(*tasks)


@pytest.mark.asyncio
async def test_cxl_cache_controller_mem_range(cxl_host_cache_controller):
    cc: CacheController
    cc = cxl_host_cache_controller

    # add range and check not empty
    cc.add_mem_range(0x0, 0x1000, MEM_ADDR_TYPE.CXL_CACHED)
    assert cc.get_memory_ranges()

    # valid + invalid "get"
    r = cc.get_mem_range(0x40)
    assert r.addr_type == MEM_ADDR_TYPE.CXL_CACHED
    t = cc.get_mem_addr_type(0x40)
    assert t == MEM_ADDR_TYPE.CXL_CACHED
    cc.get_mem_range(0x2000)
    t = cc.get_mem_addr_type(0x2000)
    assert t == MEM_ADDR_TYPE.OOB

    # valid + invalid "remove"
    cc.remove_mem_range(0x0, 0x100, MEM_ADDR_TYPE.CXL_CACHED)
    cc.remove_mem_range(0x0, 0x1000, MEM_ADDR_TYPE.CXL_CACHED)
