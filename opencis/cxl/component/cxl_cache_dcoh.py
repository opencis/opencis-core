"""
 Copyright (c) 2024, Eeum, Inc.

 This software is licensed under the terms of the Revised BSD License.
 See LICENSE for details.
"""

# pylint: disable=unused-import
from dataclasses import dataclass, field
from itertools import cycle
import math
from typing import Awaitable, Callable, Optional, cast
from asyncio import (
    Future,
    Lock,
    create_task,
    current_task,
    gather,
    get_running_loop,
    sleep,
    Queue,
    timeout,
)

from opencis.util.bound_event import BoundEvent
from opencis.util.logger import logger
from opencis.pci.component.fifo_pair import FifoPair
from opencis.cxl.transport.transaction import (
    BasePacket,
    CxlCacheBasePacket,
    CxlCacheH2DReqPacket,
    CxlCacheH2DRspPacket,
    CxlCacheH2DDataPacket,
    CxlCacheCacheD2HReqPacket,
    CxlCacheCacheD2HRspPacket,
    CxlCacheCacheD2HDataPacket,
    CXL_CACHE_H2DREQ_OPCODE,
    CXL_CACHE_H2DRSP_OPCODE,
    CXL_CACHE_H2DRSP_CACHE_STATE,
    CXL_CACHE_D2HREQ_OPCODE,
    CXL_CACHE_D2HRSP_OPCODE,
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
from opencis.pci.component.packet_processor import PacketProcessor
from opencis.util.number import split_int


@dataclass
class CacheDcohCxlChannel:
    h2d_req: Queue = field(default_factory=Queue)
    h2d_rsp: Queue = field(default_factory=Queue)
    h2d_data: Queue = field(default_factory=Queue)


class CxlCacheDcoh(PacketProcessor):
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
        self._label = label
        self._downstream_fifo: Optional[FifoPair]
        self._upstream_fifo: FifoPair

        super().__init__(upstream_fifo, downstream_fifo, label)
        self._cache_to_coh_agent_fifo = cache_to_coh_agent_fifo
        self._coh_agent_to_cache_fifo = coh_agent_to_cache_fifo

        self._cur_state = CohStateMachine(
            state=COH_STATE_MACHINE.COH_STATE_INIT,
            packet=None,
            cache_rsp=CACHE_RESPONSE_STATUS.RSP_I,
            cache_list=[
                device_id,
            ],
            birsp_sched=False,
        )

        # emulated .cache d2h channels
        self._cxl_channel = CacheDcohCxlChannel()

        self.device_entries: dict[int, Future] = (
            {}
        )  # maps CQID -> received future packets associated with CQID
        self.device_entry_lock = Lock()  # locks the above mapping

        self._cqid_gen = cycle(range(0, 4096))
        self._cqid_assign_lock = Lock()

    async def get_next_cqid(self) -> int:
        cqid: int
        async with self._cqid_assign_lock:
            cqid = next(self._cqid_gen)
        return cqid

    async def register_cqid_listener(
        self,
        cqid: int,
        cb: Callable[[BasePacket], None],
        _timeout: Optional[int] = None,
        _one_use: bool = True,
    ):
        """
        Currently not used. We created this function for _process_cxl_h2d_data_packet,
        but the state machine in _process_cxl_h2d_rsp_packet was already processing the data pckt.
        TODO: Implement the cqid logic in the future with _process_cxl_h2d_rsp_packet.

        Registers a callback action upon reception of a H2DRSP/H2DREQ packet with matching CQID.
        Used to emulate the "device entry" model in CXL.cache spec. The listener should accept
        a single CxlBasePacket parameter, which will contain the H2D packet object.

        If `_one_use` is True, the callback action will automatically unregister itself after
        one call. Note that if `_one_use` is false, the caller will have to manually handle
        cancelling by raising CancelledError, just as they would for a generic asyncio Task.

        If the operation times out, the callback action unconditionally unregisters itself.
        """
        async with self.device_entry_lock:
            # two threads accessing self.device_entries simultaneously
            # has the potential to SERIOUSLY break the emulator
            if cqid in self.device_entries:
                # cancel any currently running listeners, if they exist
                self.device_entries[cqid].cancel()

        fut_pckt = BoundEvent()

        async def _tracker_entry(fut: BoundEvent):
            while True:
                if _timeout:
                    try:
                        async with timeout(_timeout):
                            await fut
                    except TimeoutError:
                        # this request was apparently lost by the host
                        # clear the cqid entry for reuse
                        async with self.device_entry_lock:
                            del self.device_entries[cqid]
                        current_task().cancel()  # intentionally cancel the current task
                else:
                    await fut
                cb(fut.result())
                if _one_use:
                    async with self.device_entry_lock:
                        del self.device_entries[cqid]
                    break

        self.device_entries[cqid] = fut_pckt
        create_task(_tracker_entry(fut_pckt))

    async def send_d2h_req_rdown(self, addr: int, cqid: int):
        # Cache ID is "filled in" by the switch
        packet = CxlCacheCacheD2HReqPacket.create(
            addr=addr, cache_id=0, opcode=CXL_CACHE_D2HREQ_OPCODE.CACHE_RD_OWN, cqid=cqid
        )
        await self._upstream_fifo.target_to_host.put(packet)

    async def send_d2h_req_rdshared(self, addr: int, cqid: int):
        packet = CxlCacheCacheD2HReqPacket.create(
            addr=addr, cache_id=0, opcode=CXL_CACHE_D2HREQ_OPCODE.CACHE_RD_SHARED, cqid=cqid
        )
        await self._upstream_fifo.target_to_host.put(packet)

    async def send_d2h_req_itomwr(self, addr: int, cqid: int):
        packet = CxlCacheCacheD2HReqPacket.create(
            addr=addr, cache_id=0, opcode=CXL_CACHE_D2HREQ_OPCODE.CACHE_I_TO_M_WR, cqid=cqid
        )
        await self._upstream_fifo.target_to_host.put(packet)

    async def send_d2h_req_dirtyevict(self, addr: int, cqid: int):
        packet = CxlCacheCacheD2HReqPacket.create(
            addr=addr, cache_id=0, opcode=CXL_CACHE_D2HREQ_OPCODE.CACHE_DIRTY_EVICT, cqid=cqid
        )
        await self._upstream_fifo.target_to_host.put(packet)

    async def send_d2h_data(self, data: int, uqid: int):
        packet = CxlCacheCacheD2HDataPacket.create(
            uqid=uqid,
            data=data,
        )
        await self._upstream_fifo.target_to_host.put(packet)

    # async def cxl_cache_readline(self, addr: int, cqid: Optional[int] = None) -> Awaitable[int]:
    # TODO: Migrate the cqid logic to the state machine in the future

    # fut_data = BoundEvent()

    #     def _listen_check_set_fut(pckt: CxlCacheH2DRspPacket | CxlCacheH2DDataPacket):
    #         # for now, ignore the 32B transfer case.
    #         if isinstance(pckt, CxlCacheH2DDataPacket):
    #             # received a data packet
    #             # since we're ignoring the 32B transfer case,
    #             # we can just assume this data packet contains everything we want
    #             fut_data.set_result(pckt.data)
    #             current_task().cancel()
    #         if (
    #             pckt.h2drsp_header.cache_opcode != CXL_CACHE_H2DRSP_OPCODE.GO
    #             or pckt.h2drsp_header.rsp_data
    #             in (CXL_CACHE_H2DRSP_CACHE_STATE.INVALID, CXL_CACHE_H2DRSP_CACHE_STATE.ERROR)
    #         ):
    #             current_task().cancel()  # terminate the listener and free the cqid

    #         if not cqid:
    #             cqid = await self.get_next_cqid()

    #         await self.send_d2h_req_rdshared(addr, cqid)

    #         # avoid sequential cacheline writes by maintaining callbacks which are
    #         # executed upon retrieval of a Rsp with matching cqid.

    #         await self.register_cqid_listener(
    #             cqid=cqid,
    #             cb=_listen_check_set_fut,
    #             _timeout=20,
    #         )

    # return fut_data.result()

    # async def cxl_cache_writeline(self, addr: int, data: int, cqid: Optional[int] = None):
    #     def _listen_check_send(pckt: CxlCacheH2DRspPacket):
    #         """
    #         Callback registered to listen for the given CQID.
    #         Checks if the host response packet represents an error.
    #         If not, sends the requested cacheline write.
    #         """
    #         # don't need to perform the type check twice
    #         # just trust in ourselves!
    #         if pckt.h2drsp_header.cache_opcode == CXL_CACHE_H2DRSP_OPCODE.GO_ERR_WRITE_PUL:
    #             current_task().cancel()  # terminate the listener and free the cqid
    #         self.send_d2h_data(data, pckt.h2drsp_header.rsp_data)

    #     if not cqid:
    #         cqid = await self.get_next_cqid()

    #     await self.send_d2h_req_dirtyevict(addr, cqid)

    #     # avoid sequential cacheline writes by maintaining callbacks which are
    #     # executed upon retrieval of a Rsp with matching cqid.
    #     self.register_cqid_listener(
    #         cqid=cqid,
    #         cb=_listen_check_send,
    #         _timeout=20,
    #     )

    # async def cxl_cache_readlines(self, addr: int, length: int, parallel: bool = False) -> int:
    #     # pylint: disable=not-an-iterable
    #     CACHELINE_LENGTH = 64
    #     lines = bytearray(max(length, 64))
    #     if parallel:
    #         tasks = []
    #         async for l_idx in range(math.ceil(length / CACHELINE_LENGTH)):
    #             tasks.append(
    #                 create_task(
    #                     self.cxl_cache_readline(
    #                         addr + l_idx * CACHELINE_LENGTH, await self.get_next_cqid()
    #                     )
    #                 )
    #             )
    #         await gather(*tasks)
    #         for l_idx, l_offset in enumerate(range(0, length, CACHELINE_LENGTH)):
    #             lines[l_offset : l_offset + CACHELINE_LENGTH] = bytes(tasks[l_idx])
    #     else:
    #         async for l_idx in range(math.ceil(length / CACHELINE_LENGTH)):
    #             lines[l_idx * CACHELINE_LENGTH : (l_idx + 1) * CACHELINE_LENGTH] = bytes(
    #                 await self.cxl_cache_readline(
    #                     addr + l_idx * CACHELINE_LENGTH, await self.get_next_cqid()
    #                 )
    #             )
    #     return int.from_bytes(lines)

    # pylint: disable=line-too-long
    # async def cxl_cache_writelines(self, addr: int, data: int, length: int, parallel: bool = False):
    #     # pylint: disable=not-an-iterable
    #     CACHELINE_LENGTH = 64
    #     if parallel:
    #         tasks = []
    #     async for l_idx, line in enumerate(split_int(data, length, CACHELINE_LENGTH)):
    #         write_task = create_task(
    #             self.cxl_cache_writeline(
    #                 addr + l_idx * CACHELINE_LENGTH, line, await self.get_next_cqid()
    #             )
    #         )
    #         if parallel:
    #             tasks.append(write_task)
    #         else:
    #             await write_task
    #     if parallel:
    #         await gather(*tasks)

    # .cache h2d req handler
    async def _process_cxl_h2d_req_packet(self, h2dreq_packet: CxlCacheH2DReqPacket):
        if self._downstream_fifo is not None:
            raise Exception(f"CXL Endpoint Device: {self._label}")

        data_read = False
        addr = h2dreq_packet.get_address()

        if h2dreq_packet.h2dreq_header.cache_opcode == CXL_CACHE_H2DREQ_OPCODE.SNP_DATA:
            type = CACHE_REQUEST_TYPE.SNP_DATA
        elif h2dreq_packet.h2dreq_header.cache_opcode == CXL_CACHE_H2DREQ_OPCODE.SNP_INV:
            type = CACHE_REQUEST_TYPE.SNP_INV
        elif h2dreq_packet.h2dreq_header.cache_opcode == CXL_CACHE_H2DREQ_OPCODE.SNP_CUR:
            type = CACHE_REQUEST_TYPE.SNP_CUR

        cache_packet = CacheRequest(type, addr)
        await self._coh_agent_to_cache_fifo.request.put(cache_packet)
        cache_packet = await self._coh_agent_to_cache_fifo.response.get()

        if cache_packet.status == CACHE_RESPONSE_STATUS.RSP_MISS:
            opcode = CXL_CACHE_D2HRSP_OPCODE.RSP_I_HIT_I

        elif cache_packet.status == CACHE_RESPONSE_STATUS.RSP_I:
            if type == CACHE_REQUEST_TYPE.SNP_INV:
                opcode = CXL_CACHE_D2HRSP_OPCODE.RSP_I_HIT_SE

        elif cache_packet.status in (CACHE_RESPONSE_STATUS.RSP_S, CACHE_RESPONSE_STATUS.RSP_V):
            data_read = True
            if type == CACHE_REQUEST_TYPE.SNP_DATA:
                opcode = CXL_CACHE_D2HRSP_OPCODE.RSP_S_FWD_M
            elif type == CACHE_REQUEST_TYPE.SNP_CUR:
                opcode = CXL_CACHE_D2HRSP_OPCODE.RSP_V_HIT_V
        else:
            raise Exception(f"Received unexpected packet: {h2dreq_packet.get_type()}")

        cxl_packet = CxlCacheCacheD2HRspPacket.create(0, opcode)
        await self._upstream_fifo.target_to_host.put(cxl_packet)

        if data_read is True:
            cxl_packet = CxlCacheCacheD2HDataPacket.create(0, cache_packet.data)
            await self._upstream_fifo.target_to_host.put(cxl_packet)

    # .cache h2d rsp handler
    async def _process_cxl_h2d_rsp_packet(self, h2drsp_packet: CxlCacheH2DRspPacket):
        if self._downstream_fifo is not None:
            raise Exception(f"CXL Endpoint Device: {self._label}")

        # Forward packet to listening tracket entry

        # TODO: implement cqid logic here
        # cqid = h2drsp_packet.h2drsp_header.cqid
        # async with self.device_entry_lock:
        #     if cqid in self.device_entries:
        #         self.device_entries[cqid].set_result(h2drsp_packet)
        #         return

        # Handle H2DRSP without matching CQID

        if h2drsp_packet.h2drsp_header.cache_opcode == CXL_CACHE_H2DRSP_OPCODE.GO:
            if h2drsp_packet.h2drsp_header.rsp_data == CXL_CACHE_H2DRSP_CACHE_STATE.EXCLUSIVE:
                cache_packet = CacheResponse(CACHE_RESPONSE_STATUS.RSP_I)
                await self._cache_to_coh_agent_fifo.response.put(cache_packet)

            elif h2drsp_packet.h2drsp_header.rsp_data == CXL_CACHE_H2DRSP_CACHE_STATE.SHARED:
                packet = await self._cxl_channel.h2d_data.get()
                cache_packet = CacheResponse(CACHE_RESPONSE_STATUS.RSP_S, packet.data)
                await self._cache_to_coh_agent_fifo.response.put(cache_packet)

            elif h2drsp_packet.h2drsp_header.rsp_data == CXL_CACHE_H2DRSP_CACHE_STATE.INVALID:
                pass

        elif h2drsp_packet.h2drsp_header.cache_opcode == CXL_CACHE_H2DRSP_OPCODE.GO_WRITE_PULL:
            cxl_packet = CxlCacheCacheD2HDataPacket.create(0, self._cur_state.packet.data)
            await self._upstream_fifo.target_to_host.put(cxl_packet)
            cache_packet = CacheResponse(CACHE_RESPONSE_STATUS.OK)
            await self._cache_to_coh_agent_fifo.response.put(cache_packet)

        self._cur_state.state = COH_STATE_MACHINE.COH_STATE_INIT

    # async def _process_cxl_h2d_data_packet(self, h2ddata_packet: CxlCacheH2DDataPacket):
    #     Forward packet to listening tracker entry
    #     TODO: migrate this to _process_cxl_h2d_rsp_packet
    #     cqid = h2ddata_packet.h2ddata_header.cqid
    #     print(f"getting cqid {cqid}")
    #     async with self.device_entry_lock:
    #         if cqid in self.device_entries:
    #             print("Setting result")
    #             self.device_entries[cqid].set_result(h2ddata_packet)
    #     # print("Back here")
    #     self._cur_state.state = COH_STATE_MACHINE.COH_STATE_INIT

    # .cache d2h device req handler
    async def _process_cache_to_dcoh(self, cache_packet: CacheRequest):
        if self._cur_state.state == COH_STATE_MACHINE.COH_STATE_WAIT:
            return

        if self._cur_state.state == COH_STATE_MACHINE.COH_STATE_START:
            addr = cache_packet.addr

            if cache_packet.type == CACHE_REQUEST_TYPE.WRITE_BACK:
                cxl_packet = CxlCacheCacheD2HReqPacket.create(
                    addr, self._cur_state.cache_list[0], CXL_CACHE_D2HREQ_OPCODE.CACHE_DIRTY_EVICT
                )
            elif cache_packet.type == CACHE_REQUEST_TYPE.SNP_DATA:
                cxl_packet = CxlCacheCacheD2HReqPacket.create(
                    addr, self._cur_state.cache_list[0], CXL_CACHE_D2HREQ_OPCODE.CACHE_RD_SHARED
                )
            elif cache_packet.type == CACHE_REQUEST_TYPE.SNP_INV:
                cxl_packet = CxlCacheCacheD2HReqPacket.create(
                    addr,
                    self._cur_state.cache_list[0],
                    CXL_CACHE_D2HREQ_OPCODE.CACHE_RD_OWN_NO_DATA,
                )
            await self._upstream_fifo.target_to_host.put(cxl_packet)
            self._cur_state.state = COH_STATE_MACHINE.COH_STATE_WAIT

    # .cache h2d host packet handler
    async def _process_host_to_target(self):
        # pylint: disable=duplicate-code
        logger.debug(self._create_message("Started processing incoming fifo from host"))
        while True:
            packet = await self._upstream_fifo.host_to_target.get()
            if packet is None:
                logger.debug(self._create_message("Stopped processing incoming fifo from host"))
                break

            base_packet = cast(BasePacket, packet)
            if not base_packet.is_cxl_cache():
                raise Exception(f"Received unexpected packet: {base_packet.get_type()}")

            cxl_packet = cast(CxlCacheBasePacket, packet)
            if cxl_packet.is_h2dreq():
                await self._cxl_channel.h2d_req.put(cast(CxlCacheH2DReqPacket, packet))
            elif cxl_packet.is_h2drsp():
                await self._cxl_channel.h2d_rsp.put(cast(CxlCacheH2DRspPacket, packet))
            elif cxl_packet.is_h2ddata():
                await self._cxl_channel.h2d_data.put(cast(CxlCacheH2DDataPacket, packet))
            else:
                raise Exception(f"Received unexpected packet: {cxl_packet.get_type()}")

    # process from host/device channels simultaneously
    async def _cxl_cache_dcoh_main_loop(self):
        _stop_process = False

        while not _stop_process:
            await sleep(0)
            # fetch device request packet
            if self._cur_state.state == COH_STATE_MACHINE.COH_STATE_INIT:
                if not self._cache_to_coh_agent_fifo.request.empty():
                    self._cur_state.packet = await self._cache_to_coh_agent_fifo.request.get()
                    if self._cur_state.packet is None:
                        logger.debug(
                            self._create_message("Stop processing cxl cache dcoh main loop")
                        )
                        _stop_process = True
                    self._cur_state.state = COH_STATE_MACHINE.COH_STATE_START

            # run request processing and response checking code continuously until state changed
            # data packets are extracted and consumed in request processing code
            else:
                await self._process_cache_to_dcoh(self._cur_state.packet)

                if not self._cxl_channel.h2d_rsp.empty():
                    packet = await self._cxl_channel.h2d_rsp.get()
                    await self._process_cxl_h2d_rsp_packet(packet)

            # process host request regardless of device processing state
            if not self._cxl_channel.h2d_req.empty():
                packet = await self._cxl_channel.h2d_req.get()
                # corner case handling
                if (
                    self._cur_state.state != COH_STATE_MACHINE.COH_STATE_INIT
                    and packet.get_address() == self._cur_state.packet.addr
                ):
                    assert self._cur_state.packet.type == CACHE_REQUEST_TYPE.WRITE_BACK
                    if packet.h2dreq_header.cache_opcode == CXL_CACHE_H2DREQ_OPCODE.SNP_INV:
                        cxl_packet = CxlCacheCacheD2HRspPacket.create(
                            0, CXL_CACHE_D2HRSP_OPCODE.RSP_I_HIT_I
                        )
                        await self._upstream_fifo.target_to_host.put(cxl_packet)
                        continue
                await self._process_cxl_h2d_req_packet(packet)

    # pylint: disable=duplicate-code
    async def _run(self):
        tasks = [
            create_task(self._process_host_to_target()),
            create_task(self._cxl_cache_dcoh_main_loop()),
        ]
        await self._change_status_to_running()
        await gather(*tasks)

    async def _stop(self):
        await self._upstream_fifo.host_to_target.put(None)
        await self._cache_to_coh_agent_fifo.request.put(None)
