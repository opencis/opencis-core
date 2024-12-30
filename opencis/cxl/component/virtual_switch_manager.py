"""
 Copyright (c) 2024, Eeum, Inc.

 This software is licensed under the terms of the Revised BSD License.
 See LICENSE for details.
"""

from asyncio import create_task, gather
from dataclasses import dataclass
from typing import List, Optional

from opencis.cxl.component.virtual_switch.virtual_switch import (
    CxlVirtualSwitch,
    AsyncEventHandlerType,
)
from opencis.cxl.component.physical_port_manager import PhysicalPortManager
from opencis.util.component import RunnableComponent


@dataclass
class VirtualSwitchConfig:
    upstream_port_index: int
    vppb_counts: int
    initial_bounds: List[int]
    irq_host: str
    irq_port: int


class VirtualSwitchManager(RunnableComponent):
    def __init__(
        self,
        switch_configs: List[VirtualSwitchConfig],
        physical_port_manager: PhysicalPortManager,
        allocated_ld: List[int],
        bi_enable_override_for_test: Optional[int] = None,
        bi_forward_override_for_test: Optional[int] = None,
    ):
        super().__init__()
        self._physical_port_manager = physical_port_manager
        self._virtual_switches: List[CxlVirtualSwitch] = []
        for vs_index, switch_config in enumerate(switch_configs):
            virtual_switch = CxlVirtualSwitch(
                id=vs_index,
                upstream_port_index=switch_config.upstream_port_index,
                vppb_counts=switch_config.vppb_counts,
                initial_bounds=switch_config.initial_bounds,
                bi_enable_override_for_test=bi_enable_override_for_test,
                bi_forward_override_for_test=bi_forward_override_for_test,
                physical_ports=physical_port_manager.get_port_devices(),
                irq_host=switch_config.irq_host,
                irq_port=switch_config.irq_port,
                allocated_ld=allocated_ld,
            )
            self._virtual_switches.append(virtual_switch)

    def get_virtual_switch(self, switch_index: str) -> CxlVirtualSwitch:
        if switch_index >= len(self._virtual_switches) or switch_index < 0:
            raise Exception(f"Switch index {switch_index} is out of bound")
        return self._virtual_switches[switch_index]

    def get_virtual_switch_counts(self) -> int:
        return len(self._virtual_switches)

    def get_total_vppbs_count(self) -> int:
        total_vppbs = 0
        for virtual_switch in self._virtual_switches:
            total_vppbs += virtual_switch.get_vppb_counts()
        return total_vppbs

    def get_total_bound_vppbs_count(self) -> int:
        total_bound_vppbs = 0
        for virtual_switch in self._virtual_switches:
            total_bound_vppbs += virtual_switch.get_bound_vppb_counts()
        return total_bound_vppbs

    async def _run(self):
        run_tasks = []
        for virtual_switch in self._virtual_switches:
            run_tasks.append(create_task(virtual_switch.run()))
        wait_tasks = []
        for virtual_switch in self._virtual_switches:
            wait_tasks.append(create_task(virtual_switch.wait_for_ready()))
        await gather(*wait_tasks)
        await self._change_status_to_running()
        await gather(*run_tasks)

    async def _stop(self):
        tasks = []
        for virtual_switch in self._virtual_switches:
            tasks.append(create_task(virtual_switch.stop()))
        await gather(*tasks)

    def register_event_handler(self, event_handler: AsyncEventHandlerType):
        for vcs in self._virtual_switches:
            vcs.register_event_handler(event_handler)
