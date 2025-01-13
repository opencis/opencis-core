"""
 Copyright (c) 2024, Eeum, Inc.

 This software is licensed under the terms of the Revised BSD License.
 See LICENSE for details.
"""

import asyncio
import pytest

from opencis.cxl.transport.transaction import (
    CxlCacheCacheH2DDataPacket,
    CxlCacheCacheD2HDataPacket,
    CxlCacheCacheD2HReqPacket,
    CxlCacheCacheD2HRspPacket,
    CXL_CACHE_H2DREQ_OPCODE,
    CXL_CACHE_H2DRSP_OPCODE,
    CXL_CACHE_D2HREQ_OPCODE,
    CXL_CACHE_D2HRSP_OPCODE,
)
from opencis.cxl.component.root_complex.cache_coherency_bridge import (
    CacheCoherencyBridge,
    CacheCoherencyBridgeConfig,
)
from opencis.cxl.transport.memory_fifo import (
    MemoryFifoPair,
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


async def flush_memory_read(ccb: CacheCoherencyBridge):
    mem_req = await ccb._memory_producer_fifos.request.get()
    assert mem_req.type == MEMORY_REQUEST_TYPE.READ
    mem_resp = MemoryResponse(MEMORY_RESPONSE_STATUS.OK, 0xDEADBEEF)
    await ccb._memory_producer_fifos.response.put(mem_resp)


async def flush_memory_write(ccb: CacheCoherencyBridge):
    mem_req = await ccb._memory_producer_fifos.request.get()
    assert mem_req.type == MEMORY_REQUEST_TYPE.WRITE
    mem_resp = MemoryResponse(MEMORY_RESPONSE_STATUS.OK)
    await ccb._memory_producer_fifos.response.put(mem_resp)


async def send_cache_req_read(
    ccb: CacheCoherencyBridge,
    req: CacheRequest,
) -> MemoryResponse:
    data = 0xDEADBEEF
    await ccb._upstream_cache_to_coh_bridge_fifo.request.put(req)
    await flush_memory_read(ccb)
    resp = await ccb._upstream_cache_to_coh_bridge_fifo.response.get()
    assert resp.data == data
    return resp


async def send_cache_req_read_no_mem(
    ccb: CacheCoherencyBridge,
    req: CacheRequest,
) -> MemoryResponse:
    await ccb._upstream_cache_to_coh_bridge_fifo.request.put(req)
    resp = await ccb._upstream_cache_to_coh_bridge_fifo.response.get()
    return resp


async def send_cache_req_write(
    ccb: CacheCoherencyBridge,
    req: CacheRequest,
) -> MemoryResponse:
    await ccb._upstream_cache_to_coh_bridge_fifo.request.put(req)
    await flush_memory_write(ccb)
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
async def test_cache_coh_bridge_d2h_req(cxl_cache_coh_bridge):
    ccb: CacheCoherencyBridge
    ccb = cxl_cache_coh_bridge
    run_task = await ccb.run_wait_ready()

    ccb.set_cache_coh_dev_count(2)

    # D2H request: CACHE_RD_SHARED
    addr = 0x40
    device_req = CxlCacheCacheD2HReqPacket.create(addr, 0, CXL_CACHE_D2HREQ_OPCODE.CACHE_RD_SHARED)
    await ccb._downstream_cxl_cache_fifos.target_to_host.put(device_req)
    cache_req = await ccb._upstream_coh_bridge_to_cache_fifo.request.get()
    assert cache_req.addr == addr
    await ccb._upstream_coh_bridge_to_cache_fifo.response.put(
        CacheResponse(CACHE_RESPONSE_STATUS.OK)
    )
    resp = await ccb._downstream_cxl_cache_fifos.host_to_target.get()
    assert resp.h2drsp_header.cache_opcode == CXL_CACHE_H2DRSP_OPCODE.GO
    resp = await ccb._downstream_cxl_cache_fifos.host_to_target.get()
    assert isinstance(resp, CxlCacheCacheH2DDataPacket) is True

    # D2H request: CACHE_DIRTY_EVICT
    addr = 0x80
    req = CxlCacheCacheD2HReqPacket.create(addr, 0, CXL_CACHE_D2HREQ_OPCODE.CACHE_DIRTY_EVICT)
    await ccb._downstream_cxl_cache_fifos.target_to_host.put(req)
    resp = await ccb._downstream_cxl_cache_fifos.host_to_target.get()
    assert resp.h2drsp_header.cache_opcode == CXL_CACHE_H2DRSP_OPCODE.GO_WRITE_PULL
    data_packet = CxlCacheCacheD2HDataPacket.create(0, 0xDEADBEEF)
    await ccb._downstream_cxl_cache_fifos.target_to_host.put(data_packet)
    req = await ccb._memory_producer_fifos.request.get()
    assert req.addr == addr

    # D2H request: CACHE_RD_OWN_NO_DATA
    addr = 0x100
    req = CxlCacheCacheD2HReqPacket.create(addr, 0, CXL_CACHE_D2HREQ_OPCODE.CACHE_RD_OWN_NO_DATA)
    await ccb._downstream_cxl_cache_fifos.target_to_host.put(req)
    req = await ccb._upstream_coh_bridge_to_cache_fifo.request.get()
    await ccb._upstream_coh_bridge_to_cache_fifo.response.put(
        CacheResponse(CACHE_RESPONSE_STATUS.OK)
    )
    resp = await ccb._downstream_cxl_cache_fifos.host_to_target.get()
    assert resp.h2drsp_header.cache_opcode == CXL_CACHE_H2DRSP_OPCODE.GO

    await ccb.stop()
    asyncio.gather(run_task)


async def setup_cacheline(ccb: CacheCoherencyBridge, addr: int, cache_id: int):
    device_req = CxlCacheCacheD2HReqPacket.create(
        addr, cache_id, CXL_CACHE_D2HREQ_OPCODE.CACHE_RD_SHARED
    )
    await ccb._downstream_cxl_cache_fifos.target_to_host.put(device_req)
    cache_req = await ccb._upstream_coh_bridge_to_cache_fifo.request.get()
    assert cache_req.type == CACHE_REQUEST_TYPE.SNP_DATA
    await ccb._upstream_coh_bridge_to_cache_fifo.response.put(
        CacheResponse(CACHE_RESPONSE_STATUS.OK)
    )
    resp = await ccb._downstream_cxl_cache_fifos.host_to_target.get()
    assert resp.h2drsp_header.cache_opcode == CXL_CACHE_H2DRSP_OPCODE.GO
    resp = await ccb._downstream_cxl_cache_fifos.host_to_target.get()
    assert isinstance(resp, CxlCacheCacheH2DDataPacket) is True


async def cache_request_test(
    ccb: CacheCoherencyBridge,
    addr: int,
    cache_req_type: CACHE_REQUEST_TYPE,
    h2dreq_opcode: CXL_CACHE_H2DREQ_OPCODE,
    d2hrsp_opcode: CXL_CACHE_D2HRSP_OPCODE,
    mem_flush: bool = True,
    d2h_data: bool = False,
):
    # Setup
    await setup_cacheline(ccb, addr, 0)

    # Actual Test
    cache_req = CacheRequest(cache_req_type, addr, 0x40)
    await ccb._upstream_cache_to_coh_bridge_fifo.request.put(cache_req)
    req = await ccb._downstream_cxl_cache_fifos.host_to_target.get()
    if h2dreq_opcode:
        assert req.h2dreq_header.cache_opcode == h2dreq_opcode
    resp = CxlCacheCacheD2HRspPacket.create(0, d2hrsp_opcode)
    await ccb._downstream_cxl_cache_fifos.target_to_host.put(resp)

    if mem_flush:
        await flush_memory_read(ccb)

    if d2h_data:
        data_packet = CxlCacheCacheD2HDataPacket.create(0, 0xDEADBEEF)
        await ccb._downstream_cxl_cache_fifos.target_to_host.put(data_packet)


@pytest.mark.asyncio
async def test_cache_coh_bridge_cache_request(cxl_cache_coh_bridge):
    ccb: CacheCoherencyBridge
    ccb = cxl_cache_coh_bridge
    run_task = await ccb.run_wait_ready()

    ccb.set_cache_coh_dev_count(2)

    addr = 0x40
    await cache_request_test(
        ccb,
        addr,
        CACHE_REQUEST_TYPE.SNP_INV,
        CXL_CACHE_H2DREQ_OPCODE.SNP_INV,
        CXL_CACHE_D2HRSP_OPCODE.RSP_I_HIT_I,
        True,
        False,
    )
    await cache_request_test(
        ccb,
        addr,
        CACHE_REQUEST_TYPE.SNP_DATA,
        CXL_CACHE_H2DREQ_OPCODE.SNP_DATA,
        CXL_CACHE_D2HRSP_OPCODE.RSP_I_HIT_SE,
        True,
        False,
    )
    await cache_request_test(
        ccb,
        addr,
        CACHE_REQUEST_TYPE.SNP_CUR,
        CXL_CACHE_H2DREQ_OPCODE.SNP_CUR,
        CXL_CACHE_D2HRSP_OPCODE.RSP_I_FWD_M,
        True,
        False,
    )

    addr = 0x80
    await cache_request_test(
        ccb,
        addr,
        CACHE_REQUEST_TYPE.SNP_CUR,
        CXL_CACHE_H2DREQ_OPCODE.SNP_CUR,
        CXL_CACHE_D2HRSP_OPCODE.RSP_S_HIT_SE,
        False,
        True,
    )
    device_req = CxlCacheCacheD2HReqPacket.create(addr, 1, CXL_CACHE_D2HREQ_OPCODE.CACHE_RD_SHARED)
    await ccb._downstream_cxl_cache_fifos.target_to_host.put(device_req)
    await ccb._downstream_cxl_cache_fifos.host_to_target.get()
    resp = CxlCacheCacheD2HRspPacket.create(addr, 1)
    await ccb._downstream_cxl_cache_fifos.target_to_host.put(resp)
    data_packet = CxlCacheCacheD2HDataPacket.create(0, 0xDEADBEEF)
    await ccb._downstream_cxl_cache_fifos.target_to_host.put(data_packet)

    await ccb.stop()
    asyncio.gather(run_task)


@pytest.mark.asyncio
async def test_cache_coh_bridge_cache_snoop_filter_miss(cxl_cache_coh_bridge):
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
