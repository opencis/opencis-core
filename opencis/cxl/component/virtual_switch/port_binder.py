"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from asyncio import create_task, gather
from dataclasses import dataclass
from enum import Enum, auto
from typing import List, Optional

from opencis.cxl.component.bind_processor import VppbPpbBindProcessor
from opencis.cxl.component.virtual_switch.vppb import Vppb
from opencis.cxl.device.downstream_port_device import DownstreamPortDevice, SleepLoop
from opencis.util.async_gatherer import AsyncGatherer
from opencis.util.component import RunnableComponent


class BIND_STATUS(Enum):
    INIT = auto()
    BOUND = auto()
    UNBOUND = auto()


@dataclass
class BindSlot:
    vppb: Vppb
    status: BIND_STATUS = BIND_STATUS.INIT
    processor: Optional[VppbPpbBindProcessor] = None
    dsp: Optional[DownstreamPortDevice] = None


class PortBinder(RunnableComponent):
    def __init__(self, vcs_id: int, vppbs: List[Vppb]):
        super().__init__()
        self._vcs_id = vcs_id
        self._vppbs = vppbs
        self._bind_slots: List[BindSlot] = []
        self._async_gatherer = AsyncGatherer()
        for vppb in self._vppbs:
            bind_slot = BindSlot(
                vppb=vppb,
            )
            self._bind_slots.append(bind_slot)

        # Create a dummy process to keep the component running
        # TODO: cleaner method
        self._dummy_process = SleepLoop()

    def _create_message(self, message):
        message = f"[{self.__class__.__name__}:VCS{self._vcs_id}] {message}"
        return message

    async def bind_vppb(self, dsp_device: DownstreamPortDevice, vppb_index: int, ld_id: int = 0):
        if vppb_index >= len(self._bind_slots) or vppb_index < 0:
            raise Exception("vppb_index is out of bound")

        bind_slot = self._bind_slots[vppb_index]
        if bind_slot.status == BIND_STATUS.BOUND:
            raise Exception(f"vPPB[{vppb_index}] is already bound")

        # TODO: Get config space from dummy and store in PPB
        if bind_slot.processor is not None:
            await bind_slot.processor.stop()

        bind_slot.dsp = dsp_device
        bind_slot.vppb = self._vppbs[vppb_index]
        downstream_connection = bind_slot.vppb.get_downstream_connection()
        upstream_connection = dsp_device.get_ppb_device().get_upstream_connection()[ld_id]
        bind_slot.processor = VppbPpbBindProcessor(
            self._vcs_id, vppb_index, downstream_connection, upstream_connection
        )
        self._async_gatherer.add_task(bind_slot.processor.run())
        await bind_slot.processor.wait_for_ready()
        bind_slot.status = BIND_STATUS.BOUND

    async def unbind_vppb(self, vppb_index: int):
        if vppb_index >= len(self._bind_slots) or vppb_index < 0:
            raise Exception("vppb_index is out of bound")

        bind_slot = self._bind_slots[vppb_index]
        if bind_slot.status == BIND_STATUS.UNBOUND:
            raise Exception(f"vPPB[{vppb_index}] is already unbound")

        # Start unbound
        if bind_slot.processor is not None:
            await bind_slot.processor.stop()
            bind_slot.processor = None

        bind_slot.status = BIND_STATUS.UNBOUND

    def get_bind_status(self, vppb_index: int) -> BIND_STATUS:
        if vppb_index >= len(self._bind_slots) or vppb_index < 0:
            raise Exception("vppb_index is out of bound")
        return self._bind_slots[vppb_index].status

    def get_bound_vppbs_count(self) -> int:
        bound_vppbs = 0
        for slot in self._bind_slots:
            if slot.status == BIND_STATUS.BOUND:
                bound_vppbs += 1
        return bound_vppbs

    def get_bound_port_id(self, vppb_index: int) -> int:
        if vppb_index >= len(self._bind_slots) or vppb_index < 0:
            raise Exception("vppb_index is out of bound")
        if self._bind_slots[vppb_index].status != BIND_STATUS.BOUND:
            raise Exception(f"vPPB{vppb_index} is not bound")
        return self._bind_slots[vppb_index].dsp.get_port_index()

    def get_bind_slots(self):
        return self._bind_slots

    def get_vppbs(self):
        return self._vppbs

    async def _run(self):
        self._async_gatherer.add_task(self._dummy_process.run())
        await self._dummy_process.wait_for_ready()
        await self._change_status_to_running()
        await self._async_gatherer.wait_for_completion()

    async def _stop(self):
        tasks = []
        for slot in self._bind_slots:
            if slot.processor is not None:
                tasks.append(create_task(slot.processor.stop()))
        tasks.append(create_task(self._dummy_process.stop()))
        await gather(*tasks)
