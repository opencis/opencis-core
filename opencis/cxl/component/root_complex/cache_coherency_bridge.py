"""
 Copyright (c) 2024, Eeum, Inc.

 This software is licensed under the terms of the Revised BSD License.
 See LICENSE for details.
"""

from dataclasses import dataclass, field
from asyncio import create_task, gather, Queue, sleep
from itertools import cycle
from typing import cast
from enum import Enum, auto

from opencis.util.logger import logger
from opencis.util.component import RunnableComponent
from opencis.pci.component.fifo_pair import FifoPair
from opencis.cxl.transport.memory_fifo import (
    MemoryFifoPair,
    MemoryRequest,
    MEMORY_REQUEST_TYPE,
)
from opencis.cxl.transport.cache_fifo import (
    CacheFifoPair,
    CacheRequest,
    CACHE_REQUEST_TYPE,
    CacheResponse,
    CACHE_RESPONSE_STATUS,
)
from opencis.cxl.transport.transaction import (
    BasePacket,
    CxlCacheBasePacket,
    CxlCacheD2HReqPacket,
    CxlCacheD2HRspPacket,
    CxlCacheD2HDataPacket,
    CxlCacheCacheH2DReqPacket,
    CxlCacheCacheH2DRspPacket,
    CxlCacheCacheH2DDataPacket,
    CXL_CACHE_H2DREQ_OPCODE,
    CXL_CACHE_H2DRSP_OPCODE,
    CXL_CACHE_H2DRSP_CACHE_STATE,
    CXL_CACHE_D2HREQ_OPCODE,
    CXL_CACHE_D2HRSP_OPCODE,
)
from opencis.cxl.component.cache_controller import (
    CohStateMachine,
    COH_STATE_MACHINE,
)


# snoop filter update type definition
# device cache's snoop filter insertion/deletion
class SF_UPDATE_TYPE(Enum):
    SF_DEVICE_IN = auto()
    SF_DEVICE_OUT = auto()


@dataclass
class CacheCoherencyBridgeCxlChannel:
    d2h_req: Queue = field(default_factory=Queue)
    d2h_rsp: Queue = field(default_factory=Queue)
    d2h_data: Queue = field(default_factory=Queue)


@dataclass
class CacheCoherencyBridgeConfig:
    host_name: str
    memory_producer_fifos: MemoryFifoPair
    upstream_cache_to_coh_bridge_fifo: CacheFifoPair
    upstream_coh_bridge_to_cache_fifo: CacheFifoPair
    downstream_cxl_cache_fifos: FifoPair


class CacheCoherencyBridge(RunnableComponent):
    def __init__(self, config: CacheCoherencyBridgeConfig):
        super().__init__(lambda class_name: f"{config.host_name}:{class_name}")

        self._memory_producer_fifos = config.memory_producer_fifos
        self._upstream_cache_to_coh_bridge_fifo = config.upstream_cache_to_coh_bridge_fifo
        self._upstream_coh_bridge_to_cache_fifo = config.upstream_coh_bridge_to_cache_fifo
        self._downstream_cxl_cache_fifos = config.downstream_cxl_cache_fifos

        # snoop filter defined as set structure
        # max sf size will be the same as each cache size
        self._num_cache_devices = 1
        self._cur_state = CohStateMachine(
            state=COH_STATE_MACHINE.COH_STATE_INIT,
            packet=None,
            cache_rsp=CACHE_RESPONSE_STATUS.RSP_I,
            cache_list=[],
            birsp_sched=False,
        )
        self._sf_device = [set() for _ in range(self._num_cache_devices)]

        # emulated .cache d2h channels
        self._cxl_channel = CacheCoherencyBridgeCxlChannel()

        self._uqid_gen = cycle(range(0, 4096))

    def set_cache_coh_dev_count(self, count: int):
        self._num_cache_devices = count
        self._sf_device = [set() for _ in range(self._num_cache_devices)]

    def get_next_uqid(self) -> int:
        return next(self._uqid_gen)

    def _snoop_filter_update(self, addr: int, cache_id: int, sf_update_list: list) -> None:
        for sf_type in sf_update_list:
            if sf_type == SF_UPDATE_TYPE.SF_DEVICE_IN:
                self._sf_device[cache_id].add(addr)
            elif sf_type == SF_UPDATE_TYPE.SF_DEVICE_OUT:
                self._sf_device[cache_id].discard(addr)

    def _snoop_filter_find_cache_list(self, addr: int, cache_id: int = None) -> list:
        cache_list = []
        for i in range(self._num_cache_devices):
            if i == cache_id:
                continue
            if addr in self._sf_device[i]:
                cache_list.append(i)
        return cache_list

    async def _snoop_invalidate_caches(self, addr: int, cache_list: list):
        # invalidate all cachelines
        for _, cache_id in enumerate(cache_list):
            opcode = CXL_CACHE_H2DREQ_OPCODE.SNP_INV
            cxl_packet = CxlCacheCacheH2DReqPacket.create(addr, cache_id, opcode)
            await self._downstream_cxl_cache_fifos.host_to_target.put(cxl_packet)

    async def _snoop_read_latest_data(
        self, addr: int, cache_list: list, opcode: CXL_CACHE_H2DREQ_OPCODE
    ):
        assert len(cache_list) == 1

        cache_id = cache_list[0]
        self._cur_state.cache_rsp = CACHE_RESPONSE_STATUS.OK
        cxl_packet = CxlCacheCacheH2DReqPacket.create(addr, cache_id, opcode)
        await self._downstream_cxl_cache_fifos.host_to_target.put(cxl_packet)

    async def _sync_memory_read(self, addr: int) -> int:
        mem_packet = MemoryRequest(MEMORY_REQUEST_TYPE.READ, addr, 64)
        await self._memory_producer_fifos.request.put(mem_packet)
        packet = await self._memory_producer_fifos.response.get()

        return packet.data

    # .cache d2h req handler
    async def _process_cxl_d2h_req_packet(self, d2hreq_packet: CxlCacheD2HReqPacket):
        if self._cur_state.state == COH_STATE_MACHINE.COH_STATE_WAIT:
            return

        addr = d2hreq_packet.get_address()
        cache_id = d2hreq_packet.d2hreq_header.cache_id
        cqid = d2hreq_packet.d2hreq_header.cqid
        sf_update_list = []

        if d2hreq_packet.d2hreq_header.cache_opcode == CXL_CACHE_D2HREQ_OPCODE.CACHE_RD_OWN_NO_DATA:
            if self._cur_state.state == COH_STATE_MACHINE.COH_STATE_START:
                self._cur_state.cache_list = self._snoop_filter_find_cache_list(addr, cache_id)
                # device cache snoop filter miss
                if not self._cur_state.cache_list:
                    self._cur_state.state = COH_STATE_MACHINE.COH_STATE_DONE
                # snoop needs to wait until all invalid requests are finished
                else:
                    await self._snoop_invalidate_caches(addr, self._cur_state.cache_list)
                    self._cur_state.state = COH_STATE_MACHINE.COH_STATE_WAIT

            # invalidate host cache and return to the target device
            if self._cur_state.state == COH_STATE_MACHINE.COH_STATE_DONE:
                cache_packet = CacheRequest(CACHE_REQUEST_TYPE.SNP_INV, addr)
                await self._upstream_coh_bridge_to_cache_fifo.request.put(cache_packet)
                packet = await self._upstream_coh_bridge_to_cache_fifo.response.get()

                cxl_packet = CxlCacheCacheH2DRspPacket.create(
                    cache_id, CXL_CACHE_H2DRSP_OPCODE.GO, CXL_CACHE_H2DRSP_CACHE_STATE.EXCLUSIVE
                )
                sf_update_list.append(SF_UPDATE_TYPE.SF_DEVICE_IN)
                await self._downstream_cxl_cache_fifos.host_to_target.put(cxl_packet)
                self._cur_state.state = COH_STATE_MACHINE.COH_STATE_INIT

        elif d2hreq_packet.d2hreq_header.cache_opcode == CXL_CACHE_D2HREQ_OPCODE.CACHE_DIRTY_EVICT:
            if self._cur_state.state == COH_STATE_MACHINE.COH_STATE_START:
                cxl_packet = CxlCacheCacheH2DRspPacket.create(
                    cache_id,
                    CXL_CACHE_H2DRSP_OPCODE.GO_WRITE_PULL,
                    self.get_next_uqid(),  # fake UQID allocation
                    cqid=cqid,
                )
                await self._downstream_cxl_cache_fifos.host_to_target.put(cxl_packet)
                self._cur_state.state = COH_STATE_MACHINE.COH_STATE_DONE

            elif self._cur_state.state == COH_STATE_MACHINE.COH_STATE_DONE:
                if self._cxl_channel.d2h_data.empty():
                    return
                packet = await self._cxl_channel.d2h_data.get()
                addr = self._cur_state.packet.get_address()
                mem_packet = MemoryRequest(MEMORY_REQUEST_TYPE.WRITE, addr, 64, packet.data)
                await self._memory_producer_fifos.request.put(mem_packet)
                sf_update_list.append(SF_UPDATE_TYPE.SF_DEVICE_OUT)
                self._cur_state.state = COH_STATE_MACHINE.COH_STATE_INIT

        elif d2hreq_packet.d2hreq_header.cache_opcode == CXL_CACHE_D2HREQ_OPCODE.CACHE_RD_SHARED:
            if self._cur_state.state == COH_STATE_MACHINE.COH_STATE_START:
                self._cur_state.cache_list = self._snoop_filter_find_cache_list(addr, cache_id)
                # device cache snoop filter miss
                if not self._cur_state.cache_list or len(self._cur_state.cache_list) > 1:
                    self._cur_state.cache_rsp = CACHE_RESPONSE_STATUS.OK
                    self._cur_state.state = COH_STATE_MACHINE.COH_STATE_DONE
                # snoop needs to wait until exclusive read request is finished
                else:
                    await self._snoop_read_latest_data(
                        addr, self._cur_state.cache_list, CXL_CACHE_H2DREQ_OPCODE.SNP_DATA
                    )
                    self._cur_state.state = COH_STATE_MACHINE.COH_STATE_WAIT

            # share host cache and return to the target device
            if self._cur_state.state == COH_STATE_MACHINE.COH_STATE_DONE:
                if self._cur_state.cache_rsp == CACHE_RESPONSE_STATUS.RSP_S:
                    if self._cxl_channel.d2h_data.empty():
                        return
                    packet = await self._cxl_channel.d2h_data.get()
                    data = packet.data
                else:
                    cache_packet = CacheRequest(CACHE_REQUEST_TYPE.SNP_DATA, addr)
                    await self._upstream_coh_bridge_to_cache_fifo.request.put(cache_packet)
                    packet = await self._upstream_coh_bridge_to_cache_fifo.response.get()

                    if packet.status == CACHE_RESPONSE_STATUS.RSP_MISS:
                        data = await self._sync_memory_read(addr)
                    else:
                        data = packet.data

                cxl_packet = CxlCacheCacheH2DRspPacket.create(
                    cache_id, CXL_CACHE_H2DRSP_OPCODE.GO, CXL_CACHE_H2DRSP_CACHE_STATE.SHARED
                )
                sf_update_list.append(SF_UPDATE_TYPE.SF_DEVICE_IN)
                await self._downstream_cxl_cache_fifos.host_to_target.put(cxl_packet)

                cxl_packet = CxlCacheCacheH2DDataPacket.create(cache_id, data, cqid)
                await self._downstream_cxl_cache_fifos.host_to_target.put(cxl_packet)
                self._cur_state.state = COH_STATE_MACHINE.COH_STATE_INIT

        if sf_update_list:
            self._snoop_filter_update(addr, cache_id, sf_update_list)

    # .cache d2h rsp handler
    async def _process_cxl_d2h_rsp_packet(self, d2hrsp_packet: CxlCacheD2HRspPacket):
        sf_update_list = []

        if d2hrsp_packet.d2hrsp_header.cache_opcode < CXL_CACHE_D2HRSP_OPCODE.RSP_S_FWD_M:
            if d2hrsp_packet.d2hrsp_header.cache_opcode in (
                CXL_CACHE_D2HRSP_OPCODE.RSP_I_HIT_I,
                CXL_CACHE_D2HRSP_OPCODE.RSP_I_HIT_SE,
            ):
                self._cur_state.cache_rsp = CACHE_RESPONSE_STATUS.RSP_I
                sf_update_list.append(SF_UPDATE_TYPE.SF_DEVICE_OUT)
            elif d2hrsp_packet.d2hrsp_header.cache_opcode == CXL_CACHE_D2HRSP_OPCODE.RSP_S_HIT_SE:
                self._cur_state.cache_rsp = CACHE_RESPONSE_STATUS.RSP_S

            assert len(self._cur_state.cache_list) != 0
            cache_id = self._cur_state.cache_list.pop()

            if len(self._cur_state.cache_list) == 0:
                self._cur_state.state = COH_STATE_MACHINE.COH_STATE_DONE

        else:
            if d2hrsp_packet.d2hrsp_header.cache_opcode == CXL_CACHE_D2HRSP_OPCODE.RSP_S_FWD_M:
                self._cur_state.cache_rsp = CACHE_RESPONSE_STATUS.RSP_S
            elif d2hrsp_packet.d2hrsp_header.cache_opcode == CXL_CACHE_D2HRSP_OPCODE.RSP_I_FWD_M:
                self._cur_state.cache_rsp = CACHE_RESPONSE_STATUS.RSP_I
                sf_update_list.append(SF_UPDATE_TYPE.SF_DEVICE_OUT)
            cache_id = self._cur_state.cache_list.pop()
            self._cur_state.state = COH_STATE_MACHINE.COH_STATE_DONE

        if sf_update_list:
            addr = self._cur_state.packet.get_address()
            self._snoop_filter_update(addr, cache_id, sf_update_list)

    # .cache h2d packet process
    # pylint: disable=duplicate-code
    async def _process_upstream_host_to_target_packets(self, cache_packet: CacheRequest):
        if self._cur_state.state == COH_STATE_MACHINE.COH_STATE_WAIT:
            return

        if self._cur_state.state == COH_STATE_MACHINE.COH_STATE_START:
            addr = cache_packet.addr

            if cache_packet.type == CACHE_REQUEST_TYPE.WRITE_BACK:
                mem_packet = MemoryRequest(
                    MEMORY_REQUEST_TYPE.WRITE, addr, cache_packet.size, cache_packet.data
                )
                await self._memory_producer_fifos.request.put(mem_packet)
                cache_packet = CacheResponse(CACHE_RESPONSE_STATUS.OK)
                await self._upstream_cache_to_coh_bridge_fifo.response.put(cache_packet)
                self._cur_state.state = COH_STATE_MACHINE.COH_STATE_INIT
            else:
                # device cache snoop filter miss
                # host can access without sending any transaction to the devices whatsoever
                self._cur_state.cache_list = self._snoop_filter_find_cache_list(addr)
                if not self._cur_state.cache_list:
                    if cache_packet.type == CACHE_REQUEST_TYPE.SNP_INV:
                        status = CACHE_RESPONSE_STATUS.RSP_I
                        cache_packet = CacheResponse(status)
                    else:
                        if cache_packet.type == CACHE_REQUEST_TYPE.SNP_DATA:
                            status = CACHE_RESPONSE_STATUS.RSP_S
                        elif cache_packet.type == CACHE_REQUEST_TYPE.SNP_CUR:
                            status = CACHE_RESPONSE_STATUS.RSP_V
                        data = await self._sync_memory_read(addr)
                        cache_packet = CacheResponse(status, data)
                    await self._upstream_cache_to_coh_bridge_fifo.response.put(cache_packet)
                    self._cur_state.state = COH_STATE_MACHINE.COH_STATE_INIT
                # device cache snoop filter hit
                # host needs to resolve coherency for the requested line
                elif cache_packet.type == CACHE_REQUEST_TYPE.SNP_INV:
                    await self._snoop_invalidate_caches(addr, self._cur_state.cache_list)
                    self._cur_state.state = COH_STATE_MACHINE.COH_STATE_WAIT
                else:
                    # cacheline is in shared status
                    if len(self._cur_state.cache_list) > 1:
                        data = await self._sync_memory_read(addr)
                        if cache_packet.type == CACHE_REQUEST_TYPE.SNP_DATA:
                            status = CACHE_RESPONSE_STATUS.RSP_S
                        elif cache_packet.type == CACHE_REQUEST_TYPE.SNP_CUR:
                            status = CACHE_RESPONSE_STATUS.RSP_V
                        cache_packet = CacheResponse(status, data)
                        await self._upstream_cache_to_coh_bridge_fifo.response.put(cache_packet)
                        self._cur_state.state = COH_STATE_MACHINE.COH_STATE_INIT
                    # cacheline is in modified or exclusive status
                    else:
                        if cache_packet.type == CACHE_REQUEST_TYPE.SNP_DATA:
                            opcode = CXL_CACHE_H2DREQ_OPCODE.SNP_DATA
                        elif cache_packet.type == CACHE_REQUEST_TYPE.SNP_CUR:
                            opcode = CXL_CACHE_H2DREQ_OPCODE.SNP_CUR
                        await self._snoop_read_latest_data(addr, self._cur_state.cache_list, opcode)
                        self._cur_state.state = COH_STATE_MACHINE.COH_STATE_WAIT

        if self._cur_state.state == COH_STATE_MACHINE.COH_STATE_DONE:
            if self._cur_state.cache_rsp == CACHE_RESPONSE_STATUS.RSP_I:
                addr = self._cur_state.packet.addr
                data = await self._sync_memory_read(addr)
            elif self._cur_state.cache_rsp == CACHE_RESPONSE_STATUS.RSP_S:
                if self._cxl_channel.d2h_data.empty():
                    return
                packet = await self._cxl_channel.d2h_data.get()
                data = packet.data
            cache_packet = CacheResponse(self._cur_state.cache_rsp, data)
            await self._upstream_cache_to_coh_bridge_fifo.response.put(cache_packet)
            self._cur_state.state = COH_STATE_MACHINE.COH_STATE_INIT

    # .cache d2h packet process
    async def _process_downstream_target_to_host_packets(self):
        while True:
            packet = await self._downstream_cxl_cache_fifos.target_to_host.get()
            if packet is None:
                logger.debug(
                    self._create_message(
                        "Stopped processing downstream target to host CXL.cache packets"
                    )
                )
                break

            base_packet = cast(BasePacket, packet)
            if not base_packet.is_cxl_cache():
                raise Exception(f"Received unexpected packet: {base_packet.get_type()}")

            # packets are distributed to d2h channels
            cxl_packet = cast(CxlCacheBasePacket, packet)
            if cxl_packet.is_d2hreq():
                await self._cxl_channel.d2h_req.put(cast(CxlCacheD2HReqPacket, packet))
            elif cxl_packet.is_d2hrsp():
                await self._cxl_channel.d2h_rsp.put(cast(CxlCacheD2HRspPacket, packet))
            elif cxl_packet.is_d2hdata():
                await self._cxl_channel.d2h_data.put(cast(CxlCacheD2HDataPacket, packet))
            else:
                raise Exception(f"Received unexpected packet: {cxl_packet.get_type()}")

    # process from host/device channels one by one in state machine
    async def _cache_coherency_bridege_main_loop(self):
        _stop_process = False
        _fc_run = False
        _fc_host_run = False

        while not _stop_process:
            await sleep(0)
            # flow control for host/device packets
            # link state machine and function to the current request
            if self._cur_state.state == COH_STATE_MACHINE.COH_STATE_INIT:
                _fc_run = False
                if _fc_host_run is False:
                    if not self._upstream_cache_to_coh_bridge_fifo.request.empty():
                        _fc_run = True
                        _fc_host_run = True
                    elif not self._cxl_channel.d2h_req.empty():
                        _fc_run = True
                        _fc_host_run = False
                else:
                    if not self._cxl_channel.d2h_req.empty():
                        _fc_run = True
                        _fc_host_run = False
                    elif not self._upstream_cache_to_coh_bridge_fifo.request.empty():
                        _fc_run = True
                        _fc_host_run = True

                if _fc_run:
                    if _fc_host_run:
                        self._cur_state.packet = (
                            await self._upstream_cache_to_coh_bridge_fifo.request.get()
                        )
                        if self._cur_state.packet is None:
                            logger.debug(
                                self._create_message(
                                    "Stop processing cache coherency bridge main loop"
                                )
                            )
                            _stop_process = True
                        fn = self._process_upstream_host_to_target_packets
                    else:
                        self._cur_state.packet = await self._cxl_channel.d2h_req.get()
                        fn = self._process_cxl_d2h_req_packet

                    self._cur_state.state = COH_STATE_MACHINE.COH_STATE_START

            # run request processing and response checking code continuously until state changed
            # data packets are extracted and consumed in request processing code
            else:
                await fn(self._cur_state.packet)

                if not self._cxl_channel.d2h_rsp.empty():
                    packet = await self._cxl_channel.d2h_rsp.get()
                    await self._process_cxl_d2h_rsp_packet(packet)

    async def _run(self):
        tasks = [
            create_task(self._process_downstream_target_to_host_packets()),
            create_task(self._cache_coherency_bridege_main_loop()),
        ]
        await self._change_status_to_running()
        await gather(*tasks)

    async def _stop(self):
        await self._downstream_cxl_cache_fifos.target_to_host.put(None)
        await self._upstream_cache_to_coh_bridge_fifo.request.put(None)
