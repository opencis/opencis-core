"""
 Copyright (c) 2024, Eeum, Inc.

 This software is licensed under the terms of the Revised BSD License.
 See LICENSE for details.
"""

from dataclasses import dataclass, field
from asyncio import create_task, gather, sleep, Queue
import asyncio
from typing import cast

from opencis.util.logger import logger
from opencis.util.component import RunnableComponent
from opencis.pci.component.fifo_pair import FifoPair
from opencis.cxl.transport.memory_fifo import (
    MemoryFifoPair,
    MemoryRequest,
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
from opencis.cxl.transport.transaction import (
    CxlMemBasePacket,
    CxlMemMemDataPacket,
    CxlMemMemRdPacket,
    CxlMemMemWrPacket,
    CxlMemBIRspPacket,
    CxlMemS2MNDRPacket,
    CxlMemS2MDRSPacket,
    CxlMemS2MBISnpPacket,
    CXL_MEM_M2SREQ_OPCODE,
    CXL_MEM_M2SRWD_OPCODE,
    CXL_MEM_M2SBIRSP_OPCODE,
    CXL_MEM_S2MNDR_OPCODE,
    CXL_MEM_S2MDRS_OPCODE,
    CXL_MEM_S2MBISNP_OPCODE,
    CXL_MEM_META_FIELD,
    CXL_MEM_META_VALUE,
    CXL_MEM_M2S_SNP_TYPE,
    is_cxl_mem_data,
)
from opencis.cxl.component.cache_controller import (
    CohStateMachine,
    COH_STATE_MACHINE,
)


@dataclass
class HomeAgentCxlChannel:
    s2m_ndr: Queue = field(default_factory=Queue)
    s2m_drs: Queue = field(default_factory=Queue)
    s2m_bisnp: Queue = field(default_factory=Queue)


@dataclass
class HomeAgentConfig:
    host_name: str
    memory_consumer_io_fifos: MemoryFifoPair
    memory_consumer_coh_fifos: MemoryFifoPair
    memory_producer_fifos: MemoryFifoPair
    upstream_cache_to_home_agent_fifo: CacheFifoPair
    upstream_home_agent_to_cache_fifo: CacheFifoPair
    downstream_cxl_mem_fifos: FifoPair


class HomeAgent(RunnableComponent):
    def __init__(self, config: HomeAgentConfig):
        super().__init__(lambda class_name: f"{config.host_name}:{class_name}")

        self._memory_consumer_io_fifos = config.memory_consumer_io_fifos
        self._memory_consumer_coh_fifos = config.memory_consumer_coh_fifos
        self._memory_producer_fifos = config.memory_producer_fifos
        self._upstream_cache_to_home_agent_fifos = config.upstream_cache_to_home_agent_fifo
        self._upstream_home_agent_to_cache_fifos = config.upstream_home_agent_to_cache_fifo
        self._downstream_cxl_mem_fifos = config.downstream_cxl_mem_fifos

        self._cur_state = CohStateMachine(
            state=COH_STATE_MACHINE.COH_STATE_INIT,
            packet=None,
            cache_rsp=CXL_MEM_M2SBIRSP_OPCODE.BIRSP_I,
            cache_list=[],
            birsp_sched=False,
        )

        # emulated .mem s2m channels
        self._cxl_channel = HomeAgentCxlChannel()

    def _create_m2s_req_packet(
        self,
        opcode: CXL_MEM_M2SREQ_OPCODE,
        meta_field: CXL_MEM_META_FIELD,
        meta_value: CXL_MEM_META_VALUE,
        snp_type: CXL_MEM_M2S_SNP_TYPE,
        addr: int,
    ) -> CxlMemMemRdPacket:
        return CxlMemMemRdPacket.create(addr, opcode, meta_field, meta_value, snp_type)

    def _create_m2s_rwd_packet(
        self,
        opcode: CXL_MEM_M2SRWD_OPCODE,
        meta_field: CXL_MEM_META_FIELD,
        meta_value: CXL_MEM_META_VALUE,
        snp_type: CXL_MEM_M2S_SNP_TYPE,
        addr: int,
        data: int,
    ) -> CxlMemMemWrPacket:
        return CxlMemMemWrPacket.create(addr, data, opcode, meta_field, meta_value, snp_type)

    async def _write_memory(self, addr: int, size: int, value: int):
        packet = MemoryRequest(MEMORY_REQUEST_TYPE.WRITE, addr, size, value)
        await self._memory_producer_fifos.request.put(packet)
        packet = await self._memory_producer_fifos.response.get()

        assert packet.status == MEMORY_RESPONSE_STATUS.OK

    async def _read_memory(self, addr: int, size: int) -> int:
        packet = MemoryRequest(MEMORY_REQUEST_TYPE.READ, addr, size)
        await self._memory_producer_fifos.request.put(packet)
        packet = await self._memory_producer_fifos.response.get()

        return packet.data

    async def write_cxl_mem(self, addr: int, size: int, value: int):
        if addr % 64 != 0 or size % 64 != 0:
            raise Exception("Size and address must be aligned to 64!")

        chunk_count = 0
        while size > 0:
            message = self._create_message(f"CXL.mem: Writing 0x{value:08x} to 0x{addr:08x}")
            logger.debug(message)
            low_64_byte = value & ((1 << (64 * 8)) - 1)
            packet = CxlMemMemWrPacket.create(addr + (chunk_count * 64), low_64_byte)
            await self._downstream_cxl_mem_fifos.host_to_target.put(packet)
            try:
                async with asyncio.timeout(3):
                    packet = await self._downstream_cxl_mem_fifos.target_to_host.get()
            except asyncio.exceptions.TimeoutError:
                logger.error(self._create_message("CXL.mem Write: Timed-out"))
                return
            size -= 64
            chunk_count += 1
            value >>= 64 * 8

    async def read_cxl_mem(self, addr: int, size: int) -> int:
        if addr % 64 or size % 64:
            raise Exception("Size and address must be aligned to 64!")

        result = 0
        while size > 0:
            message = self._create_message(f"CXL.mem: Reading data from 0x{addr:08x}")
            logger.debug(message)
            packet = CxlMemMemRdPacket.create(addr + (size - 64))
            await self._downstream_cxl_mem_fifos.host_to_target.put(packet)

            try:
                # Does not work since target_to_host queue conflicts with
                # _process_downstream_target_to_host_packets
                async with asyncio.timeout(3):
                    packet = await self._downstream_cxl_mem_fifos.target_to_host.get()
                assert is_cxl_mem_data(packet)
                mem_data_packet = cast(CxlMemMemDataPacket, packet)
                size -= 64
                result |= mem_data_packet.data
                result <<= 64 * 8
            except asyncio.exceptions.TimeoutError:
                logger.error(self._create_message("CXL.mem Read: Timed-out"))
                return None

        return result

    async def _process_memory_io_bridge_requests(self):
        while True:
            packet = await self._memory_consumer_io_fifos.request.get()
            if packet is None:
                logger.debug(
                    self._create_message("Stopped processing memory access requests from IO Bridge")
                )
                break
            if packet.type == MEMORY_REQUEST_TYPE.WRITE:
                await self._write_memory(packet.addr, packet.size, packet.data)
            elif packet.type == MEMORY_REQUEST_TYPE.READ:
                data = await self._read_memory(packet.addr, packet.size)
                response = MemoryResponse(MEMORY_RESPONSE_STATUS.OK, data)
                await self._memory_consumer_io_fifos.response.put(response)

    async def _process_memory_coh_bridge_requests(self):
        while True:
            packet = await self._memory_consumer_coh_fifos.request.get()
            if packet is None:
                logger.debug(
                    self._create_message(
                        "Stopped processing memory access requests from Cache Coherency Bridge"
                    )
                )
                break
            if packet.type == MEMORY_REQUEST_TYPE.WRITE:
                await self._write_memory(packet.addr, packet.size, packet.data)
            elif packet.type == MEMORY_REQUEST_TYPE.READ:
                data = await self._read_memory(packet.addr, packet.size)
                response = MemoryResponse(MEMORY_RESPONSE_STATUS.OK, data)
                await self._memory_consumer_coh_fifos.response.put(response)

    # .mem s2m rsp handler
    async def _process_cxl_s2m_rsp_packet(self, s2mndr_packet: CxlMemS2MNDRPacket):
        if s2mndr_packet.s2mndr_header.opcode == CXL_MEM_S2MNDR_OPCODE.CMP_S:
            status = CACHE_RESPONSE_STATUS.RSP_S
        elif s2mndr_packet.s2mndr_header.opcode == CXL_MEM_S2MNDR_OPCODE.CMP_E:
            status = CACHE_RESPONSE_STATUS.RSP_I
        elif s2mndr_packet.s2mndr_header.opcode == CXL_MEM_S2MNDR_OPCODE.CMP_M:
            pass
        else:
            if self._cur_state.birsp_sched:
                bi_id = self._cur_state.packet.s2mbisnp_header.bi_id
                bi_tag = self._cur_state.packet.s2mbisnp_header.bi_tag
                cxl_packet = CxlMemBIRspPacket.create(self._cur_state.cache_rsp, bi_id, bi_tag)
                await self._downstream_cxl_mem_fifos.host_to_target.put(cxl_packet)
                self._cur_state.birsp_sched = False
            self._cur_state.state = COH_STATE_MACHINE.COH_STATE_INIT
            return

        if s2mndr_packet.s2mndr_header.meta_value == CXL_MEM_META_VALUE.ANY:
            # HDM-DB: DRS immediately following NDR as part of one response
            while self._cxl_channel.s2m_drs.empty():
                await asyncio.sleep(0)  # just spin
            cxl_packet = await self._cxl_channel.s2m_drs.get()
            assert cast(CxlMemBasePacket, cxl_packet).is_s2mdrs()
            cache_packet = CacheResponse(status, cxl_packet.data)
        else:
            cache_packet = CacheResponse(status)
        await self._upstream_cache_to_home_agent_fifos.response.put(cache_packet)
        self._cur_state.state = COH_STATE_MACHINE.COH_STATE_INIT

    # .mem s2m drs handler
    # method is only used for non cacheable devices like memory expander
    async def _process_cxl_s2m_drs_packet(self, s2mdrs_packet: CxlMemS2MDRSPacket):
        assert s2mdrs_packet.s2mdrs_header.opcode == CXL_MEM_S2MDRS_OPCODE.MEM_DATA

        cache_packet = CacheResponse(CACHE_RESPONSE_STATUS.OK, s2mdrs_packet.data)
        await self._upstream_cache_to_home_agent_fifos.response.put(cache_packet)
        self._cur_state.state = COH_STATE_MACHINE.COH_STATE_INIT

    # .mem s2m bisnp handler
    async def _process_cxl_s2m_bisnp_packet(self, s2mbisnp_packet: CxlMemS2MBISnpPacket):
        if self._cur_state.state == COH_STATE_MACHINE.COH_STATE_WAIT:
            return

        if self._cur_state.state == COH_STATE_MACHINE.COH_STATE_START:
            addr = s2mbisnp_packet.get_address()

            if s2mbisnp_packet.s2mbisnp_header.opcode == CXL_MEM_S2MBISNP_OPCODE.BISNP_DATA:
                cache_packet = CacheRequest(CACHE_REQUEST_TYPE.SNP_DATA, addr)
            elif s2mbisnp_packet.s2mbisnp_header.opcode == CXL_MEM_S2MBISNP_OPCODE.BISNP_INV:
                cache_packet = CacheRequest(CACHE_REQUEST_TYPE.SNP_INV, addr)
            await self._upstream_home_agent_to_cache_fifos.request.put(cache_packet)
            bi_id = s2mbisnp_packet.s2mbisnp_header.bi_id
            bi_tag = s2mbisnp_packet.s2mbisnp_header.bi_tag

            packet = await self._upstream_home_agent_to_cache_fifos.response.get()

            if packet.status == CACHE_RESPONSE_STATUS.RSP_MISS:
                # corner case handling
                # the cacheline w/ same address is currently write back to device
                rsp_state = CXL_MEM_M2SBIRSP_OPCODE.BIRSP_I
                cxl_packet = CxlMemBIRspPacket.create(rsp_state, bi_id, bi_tag)
                self._cur_state.state = COH_STATE_MACHINE.COH_STATE_INIT
            else:
                if packet.status == CACHE_RESPONSE_STATUS.RSP_S:
                    self._cur_state.cache_rsp = CXL_MEM_M2SBIRSP_OPCODE.BIRSP_S
                else:
                    self._cur_state.cache_rsp = CXL_MEM_M2SBIRSP_OPCODE.BIRSP_I
                self._cur_state.birsp_sched = True
                opcode = CXL_MEM_M2SRWD_OPCODE.MEM_WR
                meta_field = CXL_MEM_META_FIELD.META0_STATE
                meta_value = CXL_MEM_META_VALUE.INVALID
                snp_type = CXL_MEM_M2S_SNP_TYPE.NO_OP

                cxl_packet = self._create_m2s_rwd_packet(
                    opcode, meta_field, meta_value, snp_type, addr, packet.data
                )
                self._cur_state.state = COH_STATE_MACHINE.COH_STATE_WAIT
            await self._downstream_cxl_mem_fifos.host_to_target.put(cxl_packet)

    # .mem m2s packet process
    async def _process_upstream_host_to_target_packets(self, cache_packet: CacheRequest):
        if self._cur_state.state == COH_STATE_MACHINE.COH_STATE_WAIT:
            return

        if self._cur_state.state == COH_STATE_MACHINE.COH_STATE_START:
            meta_field = CXL_MEM_META_FIELD.NO_OP
            meta_value = CXL_MEM_META_VALUE.INVALID
            snp_type = CXL_MEM_M2S_SNP_TYPE.NO_OP
            addr = cache_packet.addr

            if cache_packet.type in (
                CACHE_REQUEST_TYPE.WRITE,
                CACHE_REQUEST_TYPE.WRITE_BACK,
                CACHE_REQUEST_TYPE.WRITE_BACK_CLEAN,
                CACHE_REQUEST_TYPE.UNCACHED_WRITE,
            ):
                opcode = CXL_MEM_M2SRWD_OPCODE.MEM_WR
                data = cache_packet.data

                # HDM-H Normal Write
                if cache_packet.type == CACHE_REQUEST_TYPE.WRITE:
                    meta_value = CXL_MEM_META_VALUE.ANY
                # HDM-DB Flush Write (Cmp: I/I)
                elif cache_packet.type in (
                    CACHE_REQUEST_TYPE.WRITE_BACK,
                    CACHE_REQUEST_TYPE.WRITE_BACK_CLEAN,
                ):
                    # TODO: should consider skip sending data back to .MEM dev
                    # if the cache line is clean (WRITE_BACK_CLEAN)
                    meta_field = CXL_MEM_META_FIELD.META0_STATE
                    meta_value = CXL_MEM_META_VALUE.INVALID
                # HDM Uncached Write
                elif cache_packet.type == CACHE_REQUEST_TYPE.UNCACHED_WRITE:
                    meta_value = CXL_MEM_META_VALUE.ANY

                cxl_packet = self._create_m2s_rwd_packet(
                    opcode, meta_field, meta_value, snp_type, addr, data
                )
                packet = CacheResponse(CACHE_RESPONSE_STATUS.OK)
                await self._upstream_cache_to_home_agent_fifos.response.put(packet)
            else:
                # HDM-H Normal Read
                if cache_packet.type == CACHE_REQUEST_TYPE.READ:
                    opcode = CXL_MEM_M2SREQ_OPCODE.MEM_RD
                    meta_value = CXL_MEM_META_VALUE.ANY
                # HDM-DB Device Shared Read (Cmp-S: S/S, Cmp-E: A/I)
                elif cache_packet.type == CACHE_REQUEST_TYPE.SNP_DATA:
                    opcode = CXL_MEM_M2SREQ_OPCODE.MEM_RD
                    meta_field = CXL_MEM_META_FIELD.META0_STATE
                    meta_value = CXL_MEM_META_VALUE.SHARED
                    snp_type = CXL_MEM_M2S_SNP_TYPE.SNP_DATA
                # HDM-DB Non-Data, Host Ownership Device Invalidation (Cmp-E: A/I)
                elif cache_packet.type == CACHE_REQUEST_TYPE.SNP_INV:
                    opcode = CXL_MEM_M2SREQ_OPCODE.MEM_INV
                    meta_field = CXL_MEM_META_FIELD.META0_STATE
                    meta_value = CXL_MEM_META_VALUE.ANY
                    snp_type = CXL_MEM_M2S_SNP_TYPE.SNP_INV
                # HDM-DB Non-Cacheable Read, Leaving Device Cache (Cmp: I/A)
                elif cache_packet.type == CACHE_REQUEST_TYPE.SNP_CUR:
                    opcode = CXL_MEM_M2SREQ_OPCODE.MEM_RD
                    meta_field = CXL_MEM_META_FIELD.META0_STATE
                    snp_type = CXL_MEM_M2S_SNP_TYPE.SNP_CUR
                elif cache_packet.type == CACHE_REQUEST_TYPE.UNCACHED_READ:
                    opcode = CXL_MEM_M2SREQ_OPCODE.MEM_RD
                    meta_value = CXL_MEM_META_VALUE.ANY
                else:
                    raise Exception(f"Invalid M2S Opcode Type: {cache_packet.type}")

                cxl_packet = self._create_m2s_req_packet(
                    opcode, meta_field, meta_value, snp_type, addr
                )

            self._cur_state.state = COH_STATE_MACHINE.COH_STATE_WAIT
            await self._downstream_cxl_mem_fifos.host_to_target.put(cxl_packet)

    # .mem s2m packet process
    async def _process_downstream_target_to_host_packets(self):
        while True:
            packet = await self._downstream_cxl_mem_fifos.target_to_host.get()
            if packet is None:
                logger.debug(
                    self._create_message(
                        "Stopped processing memory access requests from downstream packets"
                    )
                )
                break

            base_packet = cast(CxlMemBasePacket, packet)
            if not base_packet.is_cxl_mem():
                raise Exception(f"Received unexpected packet: {base_packet.get_type()}")

            # packets are distributed to s2m channels
            cxl_packet = cast(CxlMemBasePacket, packet)
            if cxl_packet.is_s2mndr():
                await self._cxl_channel.s2m_ndr.put(cast(CxlMemS2MNDRPacket, packet))
            elif cxl_packet.is_s2mdrs():
                await self._cxl_channel.s2m_drs.put(cast(CxlMemS2MDRSPacket, packet))
            elif cxl_packet.is_s2mbisnp():
                await self._cxl_channel.s2m_bisnp.put(cast(CxlMemS2MBISnpPacket, packet))
            else:
                raise Exception(f"Received unexpected packet: {cxl_packet.get_type()}")

    # process from host/device channels one by one in state machine
    async def _home_agent_coherency_main_loop(self):
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
                    if not self._upstream_cache_to_home_agent_fifos.request.empty():
                        _fc_run = True
                        _fc_host_run = True
                    elif not self._cxl_channel.s2m_bisnp.empty():
                        _fc_run = True
                        _fc_host_run = False
                else:
                    if not self._cxl_channel.s2m_bisnp.empty():
                        _fc_run = True
                        _fc_host_run = False
                    elif not self._upstream_cache_to_home_agent_fifos.request.empty():
                        _fc_run = True
                        _fc_host_run = True

                if _fc_run:
                    if _fc_host_run:
                        self._cur_state.packet = (
                            await self._upstream_cache_to_home_agent_fifos.request.get()
                        )
                        if self._cur_state.packet is None:
                            logger.debug(
                                self._create_message(
                                    "Stop processing home agent coherency main loop"
                                )
                            )
                            _stop_process = True
                        fn = self._process_upstream_host_to_target_packets
                    else:
                        self._cur_state.packet = await self._cxl_channel.s2m_bisnp.get()
                        fn = self._process_cxl_s2m_bisnp_packet

                    self._cur_state.state = COH_STATE_MACHINE.COH_STATE_START

            # run request processing and response checking code continuously until state changed
            # drs packets are extracted and consumed in ndr processing code
            else:
                await fn(self._cur_state.packet)

                if not self._cxl_channel.s2m_ndr.empty():
                    packet = await self._cxl_channel.s2m_ndr.get()
                    await self._process_cxl_s2m_rsp_packet(packet)

                if not self._cxl_channel.s2m_drs.empty():
                    packet = await self._cxl_channel.s2m_drs.get()
                    await self._process_cxl_s2m_drs_packet(packet)

    async def _run(self):
        tasks = [
            create_task(self._process_memory_io_bridge_requests()),
            create_task(self._process_memory_coh_bridge_requests()),
            create_task(self._process_downstream_target_to_host_packets()),
            create_task(self._home_agent_coherency_main_loop()),
        ]
        await self._change_status_to_running()
        await gather(*tasks)

    async def _stop(self):
        await self._memory_consumer_io_fifos.request.put(None)
        await self._memory_consumer_coh_fifos.request.put(None)
        await self._upstream_cache_to_home_agent_fifos.request.put(None)
        await self._downstream_cxl_mem_fifos.target_to_host.put(None)
