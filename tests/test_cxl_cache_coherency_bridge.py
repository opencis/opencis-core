"""
 Copyright (c) 2024, Eeum, Inc.

 This software is licensed under the terms of the Revised BSD License.
 See LICENSE for details.
"""

import asyncio
import pytest

from opencis.cxl.transport.transaction import (
    BasePacket,
    BaseSidebandPacket,
    CxlCacheBasePacket,
    CxlCacheD2HDataPacket,
    CxlCacheD2HReqPacket,
    CxlCacheD2HRspPacket,
    CxlCacheH2DDataPacket,
    CxlCacheH2DReqPacket,
    CxlCacheH2DRspPacket,
    CxlCacheCacheD2HReqPacket,
    CxlCacheCacheD2HRspPacket,
    CXL_CACHE_H2DREQ_OPCODE,
    CXL_CACHE_H2DRSP_OPCODE,
    CXL_CACHE_H2DRSP_CACHE_STATE,
    CXL_CACHE_D2HREQ_OPCODE,
    CXL_CACHE_D2HRSP_OPCODE,
)
from opencis.cxl.component.root_complex.cache_coherency_bridge import (
    CacheCoherencyBridge,
    CacheCoherencyBridgeConfig,
)
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
from opencis.pci.component.fifo_pair import FifoPair

# pylint: disable=protected-access, redefined-outer-name


@pytest.fixture
def cxl_cache_coh_bridge():
    # Define the necessary configuration for the CacheCoherencyBridge
    config = CacheCoherencyBridgeConfig(
        host_name="MyDevice",
        memory_producer_fifos=MemoryFifoPair(),
        upstream_cache_to_coh_bridge_fifo=CacheFifoPair(),
        upstream_coh_bridge_to_cache_fifo=CacheFifoPair(),
        downstream_cxl_cache_fifos=FifoPair(),
    )
    return CacheCoherencyBridge(config)


async def send_cache_req_read(
    ccb: CacheCoherencyBridge,
    req: CacheRequest,
) -> MemoryResponse:
    data = 0xDEADBEEF
    await ccb._upstream_cache_to_coh_bridge_fifo.request.put(req)

    mem_req = await ccb._memory_producer_fifos.request.get()
    assert mem_req.type == MEMORY_REQUEST_TYPE.READ

    mem_resp = MemoryResponse(MEMORY_RESPONSE_STATUS.OK, data)
    await ccb._memory_producer_fifos.response.put(mem_resp)

    resp = await ccb._upstream_cache_to_coh_bridge_fifo.response.get()
    assert resp.data == data
    return resp


async def send_cache_req_read_no_mem(
    ccb: CacheCoherencyBridge,
    req: CacheRequest,
) -> MemoryResponse:
    await ccb._upstream_cache_to_coh_bridge_fifo.request.put(req)
    resp = await ccb._upstream_cache_to_coh_bridge_fifo.response.get()
    # assert resp.data == data
    return resp


async def send_cache_req_write(
    ccb: CacheCoherencyBridge,
    req: CacheRequest,
) -> MemoryResponse:
    data = 0xDEADBEEF
    await ccb._upstream_cache_to_coh_bridge_fifo.request.put(req)

    mem_req = await ccb._memory_producer_fifos.request.get()
    assert mem_req.type == MEMORY_REQUEST_TYPE.WRITE

    mem_resp = MemoryResponse(MEMORY_RESPONSE_STATUS.OK, data)
    await ccb._memory_producer_fifos.response.put(mem_resp)

    resp = await ccb._upstream_cache_to_coh_bridge_fifo.response.get()
    return resp


async def send_cache_req_write_no_mem(
    ccb: CacheCoherencyBridge,
    req: CacheRequest,
) -> MemoryResponse:
    await ccb._upstream_cache_to_coh_bridge_fifo.request.put(req)
    resp = await ccb._upstream_cache_to_coh_bridge_fifo.response.get()
    return resp


@pytest.mark.asyncio
async def test_cache_coh_bridge_mem_req(cxl_cache_coh_bridge):
    ccb: CacheCoherencyBridge
    ccb = cxl_cache_coh_bridge
    run_task = await ccb.run_wait_ready()

    ccb.set_cache_coh_dev_count(2)

    # SNP_DATA
    req = CacheRequest(CACHE_REQUEST_TYPE.SNP_DATA, 0, 0x40)
    resp = await send_cache_req_read(ccb, req)
    assert resp.status == CACHE_RESPONSE_STATUS.RSP_S

    # SNP_CUR
    req = CacheRequest(CACHE_REQUEST_TYPE.SNP_CUR, 0, 0x40)
    resp = await send_cache_req_read(ccb, req)
    assert resp.status == CACHE_RESPONSE_STATUS.RSP_V

    # WRITE_BACK
    req = CacheRequest(CACHE_REQUEST_TYPE.WRITE_BACK, 0, 0x40)
    resp = await send_cache_req_write(ccb, req)
    assert resp.status == CACHE_RESPONSE_STATUS.OK

    # SNP_INV
    req = CacheRequest(CACHE_REQUEST_TYPE.SNP_INV, 0, 0x40)
    resp = await send_cache_req_read_no_mem(ccb, req)
    assert resp.status == CACHE_RESPONSE_STATUS.RSP_I

    await ccb.stop()
    asyncio.gather(run_task)


@pytest.mark.asyncio
async def test_cache_coh_bridge_d2h_req(cxl_cache_coh_bridge):
    ccb: CacheCoherencyBridge
    ccb = cxl_cache_coh_bridge
    run_task = await ccb.run_wait_ready()

    ccb.set_cache_coh_dev_count(2)

    # setup with WRITE_BACK
    # req = CacheRequest(CACHE_REQUEST_TYPE.WRITE_BACK, 0, 0x40)
    # resp = await send_cache_req_write(ccb, req)
    # assert resp.status == CACHE_RESPONSE_STATUS.OK

    # D2H request

    # D2H request: device cache snoop filter miss
    req = CxlCacheCacheD2HReqPacket.create(
        addr=0, cache_id=0, opcode=CXL_CACHE_D2HREQ_OPCODE.CACHE_RD_SHARED
    )
    await ccb._downstream_cxl_cache_fifos.target_to_host.put(req)
    resp = await ccb._downstream_cxl_cache_fifos.host_to_target.get()

    req = CxlCacheCacheD2HReqPacket.create(
        addr=0, cache_id=0, opcode=CXL_CACHE_D2HREQ_OPCODE.CACHE_DIRTY_EVICT
    )
    await ccb._downstream_cxl_cache_fifos.target_to_host.put(req)
    resp = await ccb._downstream_cxl_cache_fifos.host_to_target.get()

    # p = await ccb._upstream_coh_bridge_to_cache_fifo.request.get()

    for i in range(100):
        await asyncio.sleep(0)

    # # cache miss write: write-back only
    # addr = CACHE_NUM_ASSOC * 0x40
    # mem_req = MemoryRequest(MEMORY_REQUEST_TYPE.WRITE, addr, 0x40, 0xDEADBEEFDEADBEEF)
    # resp = await send_cached_mem_request(cc, mem_req, True)

    # # cache hit read
    # addr = CACHE_NUM_ASSOC * 0x40
    # req = MemoryRequest(MEMORY_REQUEST_TYPE.READ, addr, 0x40)
    # resp = await send_cached_mem_request(cc, req, False, False)
    # assert resp.data == 0xDEADBEEFDEADBEEF

    # # cache miss read: write-back and snoop
    # addr = 0
    # req = MemoryRequest(MEMORY_REQUEST_TYPE.READ, addr, 0x40)
    # resp = await send_cached_mem_request(cc, req, True, True)
    # # assert resp.data == 0x1111111111111111

    # # cache hit write
    # addr = 0
    # mem_req = MemoryRequest(MEMORY_REQUEST_TYPE.WRITE, addr, 0x40, 0xDEADBEEFDEADBEEF)
    # resp = await send_cached_mem_request(cc, mem_req, False, False)

    await ccb.stop()
    asyncio.gather(run_task)


# @pytest.mark.asyncio
# async def test_cxl_host_cc_cache_invalid(cxl_host_cache_controller):
#     cc: CacheController
#     cc = cxl_host_cache_controller
#     tasks = []
#     tasks.append(asyncio.create_task(cc.run_wait_ready()))

#     cc.add_mem_range(0, 0x1000, MEM_ADDR_TYPE.DRAM)
#     cc.add_mem_range(0x1000, 0x1000, MEM_ADDR_TYPE.CXL_CACHED_BI)

#     addr = 0
#     mem_req = MemoryRequest(MEMORY_REQUEST_TYPE.WRITE, addr, 0x40, 0xDEADBEEFDEADBEEF)
#     await cc._processor_to_cache_fifo.request.put(mem_req)
#     cache_req = await cc._cache_to_coh_bridge_fifo.request.get()
#     await cc._cache_to_coh_bridge_fifo.response.put(CacheResponse(CACHE_RESPONSE_STATUS.RSP_I))
#     assert cache_req.type == CACHE_REQUEST_TYPE.SNP_INV
#     await cc._processor_to_cache_fifo.response.get()

#     addr = 0x1000
#     mem_req = MemoryRequest(MEMORY_REQUEST_TYPE.WRITE, addr, 0x40, 0xDEADBEEFDEADBEEF)
#     await cc._processor_to_cache_fifo.request.put(mem_req)
#     cache_req = await cc._cache_to_coh_agent_fifo.request.get()
#     await cc._cache_to_coh_agent_fifo.response.put(CacheResponse(CACHE_RESPONSE_STATUS.RSP_I))
#     assert cache_req.type == CACHE_REQUEST_TYPE.SNP_INV
#     await cc._processor_to_cache_fifo.response.get()

#     await cc.stop()
#     asyncio.gather(*tasks)


# @pytest.mark.asyncio
# async def test_cxl_host_cc_cache_req(cxl_host_cache_controller):
#     cc: CacheController
#     cc = cxl_host_cache_controller
#     tasks = []
#     tasks.append(asyncio.create_task(cc.run_wait_ready()))

#     cc.add_mem_range(0x0, 0x1000, MEM_ADDR_TYPE.CXL_CACHED)

#     # Fill cache blocks
#     for i in range(CACHE_NUM_ASSOC):
#         addr = i * 0x40
#         req = MemoryRequest(MEMORY_REQUEST_TYPE.WRITE, addr, 0x40, 0x1111111111111111)
#         await send_cached_mem_request(cc, req, False)

#     # SNP_DATA
#     req = CacheRequest(CACHE_REQUEST_TYPE.SNP_DATA, 0, 0x40)
#     resp = await send_cache_req(cc, req)
#     assert resp.status == CACHE_RESPONSE_STATUS.RSP_S

#     # SNP_CUR
#     req = CacheRequest(CACHE_REQUEST_TYPE.SNP_CUR, 0, 0x40)
#     resp = await send_cache_req(cc, req)
#     assert resp.status == CACHE_RESPONSE_STATUS.RSP_V

#     # WRITE_BACK
#     req = CacheRequest(CACHE_REQUEST_TYPE.WRITE_BACK, 0, 0x40)
#     resp = await send_cache_req(cc, req)
#     assert resp.status == CACHE_RESPONSE_STATUS.RSP_V

#     # SNP_INV
#     req = CacheRequest(CACHE_REQUEST_TYPE.SNP_INV, 0, 0x40)
#     resp = await send_cache_req(cc, req)
#     assert resp.status == CACHE_RESPONSE_STATUS.RSP_I

#     # cache miss
#     req = CacheRequest(CACHE_REQUEST_TYPE.SNP_DATA, 0x1000, 0x40)
#     resp = await send_cache_req(cc, req)
#     assert resp.status == CACHE_RESPONSE_STATUS.RSP_MISS

#     await cc.stop()
#     asyncio.gather(*tasks)


# @pytest.mark.asyncio
# async def test_cxl_host_cc_cxl_uncached(cxl_host_cache_controller):
#     cc: CacheController
#     cc = cxl_host_cache_controller
#     tasks = []
#     tasks.append(asyncio.create_task(cc.run_wait_ready()))

#     cc.add_mem_range(0x0, 0x1000, MEM_ADDR_TYPE.CXL_UNCACHED)

#     addr = 0
#     mem_req = MemoryRequest(MEMORY_REQUEST_TYPE.UNCACHED_WRITE, addr, 0x40, 0xDEADBEEFDEADBEEF)
#     await send_uncached_mem_request(cc, mem_req)

#     addr = 0
#     mem_req = MemoryRequest(MEMORY_REQUEST_TYPE.UNCACHED_READ, addr, 0x40)
#     await send_uncached_mem_request(cc, mem_req)

#     await cc.stop()
#     asyncio.gather(*tasks)


# @pytest.mark.asyncio
# async def test_cxl_dcoh_cc_cache_req(cxl_dcoh_cache_controller):
#     cc: CacheController
#     cc = cxl_dcoh_cache_controller
#     tasks = []
#     tasks.append(asyncio.create_task(cc.run_wait_ready()))

#     # SNP_DATA
#     req = CacheRequest(CACHE_REQUEST_TYPE.SNP_DATA, 0, 0x40)
#     resp = await send_cache_req(cc, req)
#     assert resp.status == CACHE_RESPONSE_STATUS.RSP_MISS

#     await cc.stop()
#     asyncio.gather(*tasks)


# @pytest.mark.asyncio
# async def test_cxl_cache_controller_mem_range(cxl_host_cache_controller):
#     cc: CacheController
#     cc = cxl_host_cache_controller

#     # add range and check not empty
#     cc.add_mem_range(0x0, 0x1000, MEM_ADDR_TYPE.CXL_CACHED)
#     assert cc.get_memory_ranges()

#     # valid + invalid "get"
#     r = cc.get_mem_range(0x40)
#     assert r.addr_type == MEM_ADDR_TYPE.CXL_CACHED
#     t = cc.get_mem_addr_type(0x40)
#     assert t == MEM_ADDR_TYPE.CXL_CACHED
#     cc.get_mem_range(0x2000)
#     t = cc.get_mem_addr_type(0x2000)
#     assert t == MEM_ADDR_TYPE.OOB

#     # valid + invalid "remove"
#     cc.remove_mem_range(0x0, 0x100, MEM_ADDR_TYPE.CXL_CACHED)
#     cc.remove_mem_range(0x0, 0x1000, MEM_ADDR_TYPE.CXL_CACHED)
