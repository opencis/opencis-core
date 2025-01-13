"""
 Copyright (c) 2024, Eeum, Inc.

 This software is licensed under the terms of the Revised BSD License.
 See LICENSE for details.
"""

from typing import Optional, Tuple, cast
from asyncio import create_task, gather, sleep, Queue
from dataclasses import dataclass, field
from enum import Enum, auto

from opencis.util.logger import logger
from opencis.pci.component.fifo_pair import FifoPair
from opencis.cxl.transport.transaction import (
    BasePacket,
    CxlMemBasePacket,
    CxlMemM2SReqPacket,
    CxlMemM2SRwDPacket,
    CxlMemM2SBIRspPacket,
    CxlMemMemDataPacket,
    CxlMemCmpPacket,
    CxlMemBISnpPacket,
    CXL_MEM_META_FIELD,
    CXL_MEM_META_VALUE,
    CXL_MEM_M2S_SNP_TYPE,
    CXL_MEM_M2SREQ_OPCODE,
    CXL_MEM_M2SBIRSP_OPCODE,
    CXL_MEM_S2MNDR_OPCODE,
    CXL_MEM_S2MDRS_OPCODE,
    CXL_MEM_S2MBISNP_OPCODE,
)
from opencis.cxl.transport.cache_fifo import (
    CacheFifoPair,
    CacheRequest,
    CACHE_REQUEST_TYPE,
    CacheResponse,
    CACHE_RESPONSE_STATUS,
)
from opencis.cxl.component.cache_controller import (
    CohStateMachine,
    COH_STATE_MACHINE,
)
from opencis.cxl.component.cxl_memory_device_component import CxlMemoryDeviceComponent
from opencis.pci.component.packet_processor import PacketProcessor


# snoop filter update type definition
# both cache's snoop filter insertion/deletion
class SF_UPDATE_TYPE(Enum):
    SF_HOST_IN = auto()
    SF_HOST_OUT = auto()


@dataclass
class MemDcohCxlChannel:
    m2s_req: Queue = field(default_factory=Queue)
    m2s_rwd: Queue = field(default_factory=Queue)
    m2s_birsp: Queue = field(default_factory=Queue)


class CxlMemDcoh(PacketProcessor):
    def __init__(
        self,
        cache_to_coh_agent_fifo: CacheFifoPair,
        coh_agent_to_cache_fifo: CacheFifoPair,
        upstream_fifo: FifoPair,
        downstream_fifo: Optional[FifoPair] = None,
        label: Optional[str] = None,
        device_id: int = 0,
    ):
        # pylint: disable=duplicate-code
        self._downstream_fifo: Optional[FifoPair]
        self._upstream_fifo: FifoPair

        super().__init__(upstream_fifo, downstream_fifo, label)
        self._cache_to_coh_agent_fifo = cache_to_coh_agent_fifo
        self._coh_agent_to_cache_fifo = coh_agent_to_cache_fifo
        self._memory_device_component: Optional[CxlMemoryDeviceComponent] = None

        # snoop filter defined as set structure
        # max sf size will be the same as each cache size
        self._cur_state = CohStateMachine(
            state=COH_STATE_MACHINE.COH_STATE_INIT,
            packet=None,
            cache_rsp=CACHE_RESPONSE_STATUS.RSP_I,
            cache_list=[],
            birsp_sched=False,
        )
        self._sf_host = set()
        self._bi_id = device_id
        self._bi_tag = 0

        # emulated .mem m2s channels
        self._cxl_channel = MemDcohCxlChannel()

    def set_memory_device_component(self, memory_device_component: CxlMemoryDeviceComponent):
        self._memory_device_component = memory_device_component

    def _snoop_filter_update(self, addr, sf_update_list) -> None:
        for sf_type in sf_update_list:
            if sf_type == SF_UPDATE_TYPE.SF_HOST_IN:
                self._sf_host.add(addr)
            elif sf_type == SF_UPDATE_TYPE.SF_HOST_OUT:
                self._sf_host.discard(addr)

    def _sf_host_is_hit(self, addr) -> bool:
        return addr in self._sf_host

    # .mem response may have two packets (nds and drs)
    # this method always makes two reponse packets but caller may ignore one if possible
    def _create_mem_rsp_packet(
        self,
        ndr_opcode: CXL_MEM_S2MNDR_OPCODE,
        data: Optional[int] = 0,
        drs_opcode: Optional[CXL_MEM_S2MDRS_OPCODE] = CXL_MEM_S2MDRS_OPCODE.MEM_DATA,
        meta_field: Optional[CXL_MEM_META_FIELD] = CXL_MEM_META_FIELD.NO_OP,
        meta_value: Optional[CXL_MEM_META_VALUE] = CXL_MEM_META_VALUE.INVALID,
    ) -> Tuple[CxlMemCmpPacket, CxlMemMemDataPacket]:
        return (
            CxlMemCmpPacket.create(ndr_opcode, meta_field, meta_value),
            CxlMemMemDataPacket.create(data, drs_opcode, meta_field, meta_value),
        )

    # .mem m2s req (MemRd, MemRdData, and MemInv) handler
    async def _process_cxl_m2s_req_packet(self, m2sreq_packet: CxlMemM2SReqPacket):
        if self._memory_device_component is None:
            raise Exception("CxlMemoryDeviceComponent isn't set yet")

        addr = m2sreq_packet.get_address()
        dpa = self._memory_device_component.get_dpa(addr)

        if m2sreq_packet.m2sreq_header.meta_field == CXL_MEM_META_FIELD.NO_OP:
            data = await self._memory_device_component.read_mem_dpa(dpa)

            _, packet = self._create_mem_rsp_packet(CXL_MEM_S2MNDR_OPCODE.CMP, data)
            await self._upstream_fifo.target_to_host.put(packet)
            self._cur_state.state = COH_STATE_MACHINE.COH_STATE_INIT
            return

        rsp_code = CXL_MEM_S2MNDR_OPCODE.CMP
        sf_update_list = []
        data = 0
        data_flush = False
        data_read = m2sreq_packet.m2sreq_header.mem_opcode in (
            CXL_MEM_M2SREQ_OPCODE.MEM_RD,
            CXL_MEM_M2SREQ_OPCODE.MEM_RD_DATA,
        )

        if m2sreq_packet.m2sreq_header.snp_type == CXL_MEM_M2S_SNP_TYPE.SNP_DATA:
            type = CACHE_REQUEST_TYPE.SNP_DATA
        elif m2sreq_packet.m2sreq_header.snp_type == CXL_MEM_M2S_SNP_TYPE.SNP_INV:
            type = CACHE_REQUEST_TYPE.SNP_INV
        elif m2sreq_packet.m2sreq_header.snp_type == CXL_MEM_M2S_SNP_TYPE.SNP_CUR:
            type = CACHE_REQUEST_TYPE.SNP_CUR

        packet = CacheRequest(type, dpa)
        await self._coh_agent_to_cache_fifo.request.put(packet)
        packet = await self._coh_agent_to_cache_fifo.response.get()

        if packet.status == CACHE_RESPONSE_STATUS.RSP_MISS:
            if m2sreq_packet.m2sreq_header.snp_type == CXL_MEM_M2S_SNP_TYPE.SNP_DATA:
                rsp_code = CXL_MEM_S2MNDR_OPCODE.CMP_E
                sf_update_list.append(SF_UPDATE_TYPE.SF_HOST_IN)
            elif m2sreq_packet.m2sreq_header.snp_type == CXL_MEM_M2S_SNP_TYPE.SNP_INV:
                if m2sreq_packet.m2sreq_header.meta_value == CXL_MEM_META_VALUE.ANY:
                    rsp_code = CXL_MEM_S2MNDR_OPCODE.CMP_E
                    sf_update_list.append(SF_UPDATE_TYPE.SF_HOST_IN)
                elif (
                    m2sreq_packet.m2sreq_header.meta_value == CXL_MEM_META_VALUE.INVALID
                    or m2sreq_packet.m2sreq_header.meta_field == CXL_MEM_META_FIELD.NO_OP
                ):
                    pass
            elif m2sreq_packet.m2sreq_header.snp_type == CXL_MEM_M2S_SNP_TYPE.SNP_CUR:
                pass

            if data_read is True:
                data = await self._memory_device_component.read_mem_dpa(dpa)
        else:
            if packet.status == CACHE_RESPONSE_STATUS.RSP_S:
                rsp_code = CXL_MEM_S2MNDR_OPCODE.CMP_S
                sf_update_list.append(SF_UPDATE_TYPE.SF_HOST_IN)
            elif packet.status == CACHE_RESPONSE_STATUS.RSP_I:
                if m2sreq_packet.m2sreq_header.meta_value == CXL_MEM_META_VALUE.ANY:
                    rsp_code = CXL_MEM_S2MNDR_OPCODE.CMP_E
                    sf_update_list.append(SF_UPDATE_TYPE.SF_HOST_IN)
                elif (
                    m2sreq_packet.m2sreq_header.meta_value == CXL_MEM_META_VALUE.INVALID
                    or m2sreq_packet.m2sreq_header.meta_field == CXL_MEM_META_FIELD.NO_OP
                ):
                    if m2sreq_packet.m2sreq_header.mem_opcode == CXL_MEM_M2SREQ_OPCODE.MEM_RD:
                        data_flush = True
            elif packet.status == CACHE_RESPONSE_STATUS.RSP_V:
                pass
            data = packet.data

        if sf_update_list:
            self._snoop_filter_update(dpa, sf_update_list)

        if data_flush is True:
            await self._memory_device_component.write_mem_dpa(dpa, data)

        if data_read is True:
            ndr_packet, drs_packet = self._create_mem_rsp_packet(
                rsp_code, data, meta_value=CXL_MEM_META_VALUE.ANY
            )
            await self._upstream_fifo.target_to_host.put(ndr_packet)
            await self._upstream_fifo.target_to_host.put(drs_packet)
        else:
            ndr_packet, _ = self._create_mem_rsp_packet(rsp_code, data)
            await self._upstream_fifo.target_to_host.put(ndr_packet)

    # .mem m2s rwd (MemWr) handler
    async def _process_cxl_m2s_rwd_packet(self, m2srwd_packet: CxlMemM2SRwDPacket):
        if self._memory_device_component is None:
            raise Exception("CxlMemoryDeviceComponent isn't set yet")

        addr = m2srwd_packet.get_address()
        dpa = self._memory_device_component.get_dpa(addr)

        if m2srwd_packet.m2srwd_header.meta_field == CXL_MEM_META_FIELD.NO_OP:
            await self._memory_device_component.write_mem_dpa(dpa, m2srwd_packet.data)

            packet, _ = self._create_mem_rsp_packet(CXL_MEM_S2MNDR_OPCODE.CMP, m2srwd_packet.data)
            await self._upstream_fifo.target_to_host.put(packet)
            self._cur_state.state = COH_STATE_MACHINE.COH_STATE_INIT
            return

        rsp_code = CXL_MEM_S2MNDR_OPCODE.CMP
        sf_update_list = []
        data_flush = True

        if m2srwd_packet.m2srwd_header.meta_value == CXL_MEM_META_VALUE.ANY:
            packet = CacheRequest(CACHE_REQUEST_TYPE.SNP_INV, dpa)
        elif m2srwd_packet.m2srwd_header.meta_value == CXL_MEM_META_VALUE.SHARED:
            packet = CacheRequest(CACHE_REQUEST_TYPE.SNP_DATA, dpa)
        elif m2srwd_packet.m2srwd_header.meta_value == CXL_MEM_META_VALUE.INVALID:
            packet = CacheRequest(CACHE_REQUEST_TYPE.SNP_INV, dpa)
            sf_update_list.append(SF_UPDATE_TYPE.SF_HOST_OUT)
        await self._coh_agent_to_cache_fifo.request.put(packet)
        packet = await self._coh_agent_to_cache_fifo.response.get()

        if sf_update_list:
            self._snoop_filter_update(dpa, sf_update_list)

        if data_flush is True:
            await self._memory_device_component.write_mem_dpa(dpa, m2srwd_packet.data)

        ndr_packet, _ = self._create_mem_rsp_packet(rsp_code)
        await self._upstream_fifo.target_to_host.put(ndr_packet)

    # .mem m2s birsp handler
    async def _process_cxl_m2s_birsp_packet(self, m2sbirsp_packet: CxlMemM2SBIRspPacket):
        dpa = self._cur_state.packet.addr
        data = await self._memory_device_component.read_mem_dpa(dpa)

        if m2sbirsp_packet.m2sbirsp_header.opcode == CXL_MEM_M2SBIRSP_OPCODE.BIRSP_S:
            packet = CacheResponse(CACHE_RESPONSE_STATUS.RSP_S, data)
        elif m2sbirsp_packet.m2sbirsp_header.opcode == CXL_MEM_M2SBIRSP_OPCODE.BIRSP_I:
            packet = CacheResponse(CACHE_RESPONSE_STATUS.RSP_I, data)
        else:
            raise Exception(
                f"Unsupported M2SBIRsp Opcode: {m2sbirsp_packet.m2sbirsp_header.opcode}"
            )
        await self._cache_to_coh_agent_fifo.response.put(packet)
        self._cur_state.state = COH_STATE_MACHINE.COH_STATE_INIT

    # .mem s2m device req handler
    async def _process_cache_to_dcoh(self, cache_packet: CacheRequest):
        if self._memory_device_component is None:
            raise Exception("CxlMemoryDeviceComponent isn't set yet")

        if self._cur_state.state == COH_STATE_MACHINE.COH_STATE_WAIT:
            return

        if self._cur_state.state == COH_STATE_MACHINE.COH_STATE_START:
            dpa = cache_packet.addr
            if cache_packet.type == CACHE_REQUEST_TYPE.READ:
                data = await self._memory_device_component.read_mem_dpa(dpa)
                packet = CacheResponse(CACHE_RESPONSE_STATUS.OK, data)
                await self._cache_to_coh_agent_fifo.response.put(packet)
                self._cur_state.state = COH_STATE_MACHINE.COH_STATE_INIT
            elif cache_packet.type in (CACHE_REQUEST_TYPE.WRITE, CACHE_REQUEST_TYPE.WRITE_BACK):
                await self._memory_device_component.write_mem_dpa(dpa, cache_packet.data)
                packet = CacheResponse(CACHE_RESPONSE_STATUS.OK)
                await self._cache_to_coh_agent_fifo.response.put(packet)
                self._cur_state.state = COH_STATE_MACHINE.COH_STATE_INIT
            else:
                # host cache snoop filter miss
                if not self._sf_host_is_hit(dpa):
                    if cache_packet.type == CACHE_REQUEST_TYPE.SNP_DATA:
                        data = await self._memory_device_component.read_mem_dpa(dpa)
                        packet = CacheResponse(CACHE_RESPONSE_STATUS.RSP_I, data)
                    elif cache_packet.type == CACHE_REQUEST_TYPE.SNP_INV:
                        packet = CacheResponse(CACHE_RESPONSE_STATUS.RSP_I)
                    elif cache_packet.type == CACHE_REQUEST_TYPE.SNP_CUR:
                        packet = CacheResponse(CACHE_RESPONSE_STATUS.RSP_V)
                    await self._cache_to_coh_agent_fifo.response.put(packet)
                    self._cur_state.state = COH_STATE_MACHINE.COH_STATE_INIT
                # host cache snoop filter hit
                else:
                    sf_update_list = []
                    if cache_packet.type == CACHE_REQUEST_TYPE.SNP_DATA:
                        bi_opcode = CXL_MEM_S2MBISNP_OPCODE.BISNP_DATA
                    elif cache_packet.type == CACHE_REQUEST_TYPE.SNP_INV:
                        sf_update_list.append(SF_UPDATE_TYPE.SF_HOST_OUT)
                        bi_opcode = CXL_MEM_S2MBISNP_OPCODE.BISNP_INV
                    elif cache_packet.type == CACHE_REQUEST_TYPE.SNP_CUR:
                        bi_opcode = CXL_MEM_S2MBISNP_OPCODE.BISNP_CUR
                    hpa = self._memory_device_component.get_hpa(dpa)
                    cxl_packet = CxlMemBISnpPacket.create(hpa, bi_opcode, self._bi_id, self._bi_tag)
                    await self._upstream_fifo.target_to_host.put(cxl_packet)

                    if sf_update_list:
                        self._snoop_filter_update(dpa, sf_update_list)
                    self._cur_state.state = COH_STATE_MACHINE.COH_STATE_WAIT

    # .mem m2s host packet handler
    async def _process_host_to_target(self):
        while True:
            packet = await self._upstream_fifo.host_to_target.get()
            if packet is None:
                logger.debug(self._create_message("Stopped processing incoming fifo from host"))
                break

            base_packet = cast(BasePacket, packet)
            if not base_packet.is_cxl_mem():
                raise Exception(f"Received unexpected packet: {base_packet.get_type()}")

            # packets are distributed to m2s channels
            cxl_packet = cast(CxlMemBasePacket, packet)
            if cxl_packet.is_m2sreq():
                await self._cxl_channel.m2s_req.put(cast(CxlMemM2SReqPacket, packet))
            elif cxl_packet.is_m2srwd():
                await self._cxl_channel.m2s_rwd.put(cast(CxlMemM2SRwDPacket, packet))
            elif cxl_packet.is_m2sbirsp():
                await self._cxl_channel.m2s_birsp.put(cast(CxlMemM2SBIRspPacket, packet))
            else:
                raise Exception(f"Received unexpected packet: {cxl_packet.get_type()}")

    # process from host/device channels simultaneously
    # pylint: disable=duplicate-code
    async def _cxl_mem_dcoh_main_loop(self):
        _stop_process = False

        while not _stop_process:
            await sleep(0)
            # fetch device request packet
            if self._cur_state.state == COH_STATE_MACHINE.COH_STATE_INIT:
                if not self._cache_to_coh_agent_fifo.request.empty():
                    self._cur_state.packet = await self._cache_to_coh_agent_fifo.request.get()
                    if self._cur_state.packet is None:
                        logger.debug(
                            self._create_message("Stop processing cache coherency bridge main loop")
                        )
                        _stop_process = True
                    self._cur_state.state = COH_STATE_MACHINE.COH_STATE_START

            # run request processing and response checking code continuously until state changed
            else:
                await self._process_cache_to_dcoh(self._cur_state.packet)

                if not self._cxl_channel.m2s_birsp.empty():
                    packet = await self._cxl_channel.m2s_birsp.get()
                    await self._process_cxl_m2s_birsp_packet(packet)

            # process host request regardless of device processing state
            if not self._cxl_channel.m2s_req.empty():
                packet = await self._cxl_channel.m2s_req.get()
                await self._process_cxl_m2s_req_packet(packet)

            # process host request regardless of device processing state
            if not self._cxl_channel.m2s_rwd.empty():
                packet = await self._cxl_channel.m2s_rwd.get()
                await self._process_cxl_m2s_rwd_packet(packet)

    # pylint: disable=duplicate-code
    async def _run(self):
        tasks = [
            create_task(self._process_host_to_target()),
            create_task(self._cxl_mem_dcoh_main_loop()),
        ]
        await self._change_status_to_running()
        await gather(*tasks)

    async def _stop(self):
        await self._upstream_fifo.host_to_target.put(None)
        await self._cache_to_coh_agent_fifo.request.put(None)
