"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from asyncio import gather, create_task
from dataclasses import dataclass
from enum import IntEnum
from typing import List, Optional, cast, Callable, Coroutine, Any

from opencis.cxl.component.irq_manager import Irq, IrqManager
from opencis.cxl.component.virtual_switch.vppb_routing_info import VppbRoutingInfo
from opencis.util.logger import logger
from opencis.cxl.component.common import CXL_COMPONENT_TYPE
from opencis.cxl.component.virtual_switch.port_binder import PortBinder, BIND_STATUS
from opencis.cxl.component.virtual_switch.routers import CxlMemRouter, CxlIoRouter, CxlCacheRouter
from opencis.cxl.component.virtual_switch.routing_table import RoutingTable
from opencis.cxl.component.virtual_switch.upstream_vppb import UpstreamVppb
from opencis.cxl.component.virtual_switch.downstream_vppb import DownstreamVppb
from opencis.cxl.device.port_device import CxlPortDevice
from opencis.cxl.device.downstream_port_device import DownstreamPortDevice
from opencis.util.component import RunnableComponent


class PPB_BINDING_STATUS(IntEnum):
    UNBOUND = 0x00
    BIND_OR_UNBIND_IN_PROGRESS = 0x01
    BOUND_PHYSICAL_PORT = 0x02
    BOUND_LD = 0x03


@dataclass
class SwitchUpdateEvent:
    vcs_id: int
    vppb_id: int
    binding_status: PPB_BINDING_STATUS


AsyncEventHandlerType = Callable[[SwitchUpdateEvent], Coroutine[Any, Any, None]]


class VCS_STATE(IntEnum):
    DISABLED = 0x00
    ENABLED = 0x01
    INVALID_VCS_ID = 0xFF


class CxlVirtualSwitch(RunnableComponent):
    def __init__(
        self,
        id: int,
        upstream_port_index: int,
        vppb_counts: int,
        initial_bounds: List[int],
        physical_ports: List[CxlPortDevice],
        allocated_ld: List[int] = None,
        bi_enable_override_for_test: Optional[int] = None,
        bi_forward_override_for_test: Optional[int] = None,
        irq_host: str = "0.0.0.0",
        irq_port: int = 8500,
    ):
        super().__init__()
        self._label = f"VCS{id}"
        self._id = id
        self._vppb_counts = vppb_counts
        self._initial_bounds = initial_bounds
        self._physical_ports = physical_ports
        self._routing_table = RoutingTable(vppb_counts, label=self._label)
        self._event_handler = None
        self._fm_enabled = False
        self._bi_enable_override_for_test = bi_enable_override_for_test
        self._bi_forward_override_for_test = bi_forward_override_for_test
        self._cxl_io_router = None
        self._cxl_mem_router = None
        self._cxl_cache_router = None
        self._vppb_ld_id_map = {}

        # Convert allocated_ld from dictionary to list of lists format
        if allocated_ld is None:
            self._allocated_ld = [[] for _ in range(len(physical_ports))]
        elif isinstance(allocated_ld, dict):
            # Convert dictionary format to list of lists
            self._allocated_ld = [[] for _ in range(len(physical_ports))]
            for port_index, ld_list in allocated_ld.items():
                if port_index < len(self._allocated_ld):
                    self._allocated_ld[port_index] = ld_list
        else:
            self._allocated_ld = allocated_ld

        self._irq_manager = IrqManager(
            device_name=self._label,
            addr=irq_host,
            port=irq_port,
            server=False,
            device_id=id,
        )

        if len(initial_bounds) != self._vppb_counts:
            raise Exception("length of initial_bounds and vppb_count must be the same")

        # NOTE: Selects USP device based on initially provided upstream port index
        # The assigned USP will not be remapped later.
        if upstream_port_index < 0 or upstream_port_index >= len(self._physical_ports):
            raise Exception("Upstream Port Index is out of bound")

        logger.info(f"Upstream Port Index: {upstream_port_index}")

        self._upstream_vppb = UpstreamVppb(upstream_port_index)
        self._upstream_vppb.bind_to_physical_usp_port(self._physical_ports[upstream_port_index])
        if self._physical_ports[upstream_port_index].get_device_type() != CXL_COMPONENT_TYPE.USP:
            raise Exception(f"physical port {upstream_port_index} is not USP")
        self._downstream_vppbs = [DownstreamVppb(idx, id) for idx in range(vppb_counts)]

        self._upstream_vppb.set_routing_table(VppbRoutingInfo(self._routing_table))
        for idx in range(len(self._physical_ports)):
            self._upstream_vppb.get_cxl_component().add_cache_route_target(idx)

        # NOTE: Make PortBinder
        self._port_binder = PortBinder(self._id, self._downstream_vppbs)

        # TODO: Pseudo FM, replace with real FM and remove pseudo_fm_get_ld_id()
        self._pseudo_fm_dict = {}
        self._physical_ports_vppb_map = {}

        # NOTE: Make Routers
        self._cxl_io_router = CxlIoRouter(
            self._id, self._routing_table, self._upstream_vppb, self._port_binder
        )
        self._cxl_mem_router = CxlMemRouter(
            self._id,
            self._routing_table,
            self._upstream_vppb,
            self._port_binder,
            self._bi_enable_override_for_test,
            self._bi_forward_override_for_test,
        )
        self._cxl_cache_router = CxlCacheRouter(
            self._id, self._routing_table, self._upstream_vppb, self._port_binder
        )

    def _create_message(self, message: str):
        message = f"[{self.__class__.__name__} {self._id}] {message}"
        return message

    async def _bind_initial_vppb(self):
        for vppb_index, port_index in enumerate(self._initial_bounds):
            _port_index = -1
            _ld_id = 0
            if isinstance(port_index, List):
                if len(port_index) == 2:
                    _ld_id = port_index[1]
                _port_index = port_index[0]
            else:
                _port_index = port_index
            if _port_index == -1:
                # RoutingTable starts with 1, set to 0 here
                self._routing_table.deactivate_vppb(vppb_index)
            else:
                await self.bind_vppb(_port_index, vppb_index, _ld_id)

    async def _run(self):
        await self._bind_initial_vppb()

        run_tasks = [
            create_task(self._irq_manager.run()),
            create_task(self._cxl_io_router.run()),
            create_task(self._cxl_mem_router.run()),
            create_task(self._cxl_cache_router.run()),
            create_task(self._port_binder.run()),
        ]
        wait_tasks = [
            create_task(self._irq_manager.wait_for_ready()),
            create_task(self._cxl_io_router.wait_for_ready()),
            create_task(self._cxl_mem_router.wait_for_ready()),
            create_task(self._cxl_cache_router.wait_for_ready()),
            create_task(self._port_binder.wait_for_ready()),
        ]
        await gather(*wait_tasks)
        await self._change_status_to_running()
        await gather(*run_tasks)

    async def _stop(self):
        tasks = [
            create_task(self._cxl_io_router.stop()),
            create_task(self._cxl_mem_router.stop()),
            create_task(self._cxl_cache_router.stop()),
            create_task(self._port_binder.stop()),
            create_task(self._irq_manager.stop()),
        ]
        await gather(*tasks)

    async def bind_vppb(self, port_index: int, vppb_index: int, ld_id: int):
        if port_index < 0 or port_index >= len(self._physical_ports):
            raise Exception("port_index is out of bound")

        # Handle case where there are no allocated LD IDs for this port
        if port_index >= len(self._allocated_ld) or not self._allocated_ld[port_index]:
            logger.warning(
                self._create_message(f"No allocated LD IDs for port {port_index}, skipping binding")
            )
            return

        if ld_id not in self._allocated_ld[port_index]:
            logger.error(
                self._create_message(f"ld_id: {ld_id} in port: {port_index} is out of bound")
            )
            raise Exception("ld_id is out of bound")

        self._routing_table.activate_vppb(vppb_index)
        port_device = self._physical_ports[port_index]
        vppb = self._downstream_vppbs[vppb_index]
        if port_device.get_device_type() != CXL_COMPONENT_TYPE.DSP:
            raise Exception(f"physical port {port_index} is not DSP")
        logger.info(
            self._create_message(f"Started Binding physical port {port_index} to vPPB {vppb_index}")
        )
        dsp_device = cast(DownstreamPortDevice, port_device)

        await dsp_device.get_ppb_device().bind(ld_id)
        dsp_device.set_vppb_index(vppb_index)
        await vppb.bind_to_physical_dsp_port(dsp_device, ld_id)

        vppb.set_ld_id(ld_id)
        vppb.set_routing_table(VppbRoutingInfo(self._routing_table, ld_id))
        vppb.set_vppb_index(vppb_index)

        # Create physical port to vppb mapping
        self._physical_ports_vppb_map[vppb_index] = port_device
        self._vppb_ld_id_map[vppb_index] = ld_id

        await self._call_event_handler(vppb_index, PPB_BINDING_STATUS.BIND_OR_UNBIND_IN_PROGRESS)
        await self._port_binder.bind_vppb(dsp_device, vppb_index, ld_id)

        await self._call_event_handler(vppb_index, PPB_BINDING_STATUS.BOUND_LD)
        await self._cxl_mem_router.update_router(vppb_index)
        await self._cxl_cache_router.update_router(vppb_index)
        await self._cxl_io_router.update_router(vppb_index)

        logger.info(
            self._create_message(
                f"Succcessfully bound physical port {port_index} "
                + f"to vPPB {vppb_index} with LD-ID {ld_id}"
            )
        )

    # TODO: Unused for now, integrate when FM is ready
    async def fm_bind_vppb(self, port_index: int, vppb_index: int, ld_id: int):
        await self.bind_vppb(port_index, vppb_index, ld_id)
        await self._irq_manager.send_irq_request(Irq.DEV_ADDED)

    async def unbind_vppb(self, vppb_index: int):
        logger.info(self._create_message(f"Started unbinding physical port from vPPB {vppb_index}"))
        if self._physical_ports_vppb_map.get(vppb_index, None) is not None:
            ld_id = self._downstream_vppbs[vppb_index].get_ld_id()
            await self._downstream_vppbs[vppb_index].unbind_from_physical_port(
                self._physical_ports_vppb_map[vppb_index]
            )
            await self._physical_ports_vppb_map[vppb_index].get_ppb_device().unbind(ld_id)
            del self._physical_ports_vppb_map[vppb_index]
        else:
            logger.error(
                self._create_message(f"vPPB {vppb_index} is not bound to any physical port")
            )
            raise Exception(f"vPPB {vppb_index} is not bound to any physical port")

        await self._call_event_handler(vppb_index, PPB_BINDING_STATUS.BIND_OR_UNBIND_IN_PROGRESS)
        await self._port_binder.unbind_vppb(vppb_index)

        await self._call_event_handler(vppb_index, PPB_BINDING_STATUS.UNBOUND)

        self._downstream_vppbs[vppb_index].set_ld_id(0)
        self._routing_table.deactivate_vppb(vppb_index)
        if vppb_index in self._vppb_ld_id_map:
            self._vppb_ld_id_map.pop(vppb_index)

        await self._cxl_mem_router.update_router(vppb_index)
        await self._cxl_cache_router.update_router(vppb_index)
        await self._cxl_io_router.update_router(vppb_index)

        logger.info(
            self._create_message(f"Succcessfully unbound physical port from vPPB {vppb_index}")
        )

    async def fm_unbind_vppb(self, vppb_index: int):
        await self.unbind_vppb(vppb_index)
        # TODO: Free ld id?
        await self._irq_manager.send_irq_request(Irq.DEV_REMOVED)

    async def freeze_vppb(self, vppb_index: int):
        logger.info(self._create_message(f"Freezing physical port from vPPB {vppb_index}"))
        if self._physical_ports_vppb_map.get(vppb_index, None) is not None:
            ld_id = self._downstream_vppbs[vppb_index].get_ld_id()
            await self._physical_ports_vppb_map[vppb_index].get_ppb_device().freeze(ld_id)
        else:
            logger.error(
                self._create_message(f"vPPB {vppb_index} is not bound to any physical port")
            )
            raise Exception(f"vPPB {vppb_index} is not bound to any physical port")

        logger.info(
            self._create_message(f"Succcessfully froze physical port from vPPB {vppb_index}")
        )

    async def unfreeze_vppb(self, vppb_index: int):
        logger.info(self._create_message(f"Unfreezing physical port from vPPB {vppb_index}"))
        if self._physical_ports_vppb_map.get(vppb_index, None) is not None:
            ld_id = self._downstream_vppbs[vppb_index].get_ld_id()
            await self._physical_ports_vppb_map[vppb_index].get_ppb_device().unfreeze(ld_id)
        else:
            logger.error(
                self._create_message(f"vPPB {vppb_index} is not bound to any physical port")
            )
            raise Exception(f"vPPB {vppb_index} is not bound to any physical port")

        logger.info(
            self._create_message(f"Succcessfully unfroze physical port from vPPB {vppb_index}")
        )

    def get_vppb_counts(self) -> int:
        return self._vppb_counts

    def get_bound_vppb_counts(self) -> int:
        return len(self._physical_ports_vppb_map)

    def is_vppb_bound(self, vppb_index) -> bool:
        if vppb_index >= self._vppb_counts:
            raise Exception("vppb_index is out of bound")
        return self._port_binder.get_bind_status(vppb_index) == BIND_STATUS.BOUND

    def get_usp_port_id(self) -> int:
        return self._upstream_vppb.get_port_index()

    def get_bound_port_id(self, vppb_id: int) -> int:
        return self._port_binder.get_bound_port_id(vppb_id)

    def get_ld_id(self, vppb_id: int) -> int:
        return self._vppb_ld_id_map[vppb_id]

    def get_irq_port(self) -> int:
        return self._irq_manager.get_port()

    def register_event_handler(self, event_handler: AsyncEventHandlerType):
        self._event_handler = event_handler

    def update_ld_allocations(self, port_index: int, ld_ids: List[int]):
        """Update LD allocations for a specific port.

        Args:
            port_index: The port index to update
            ld_ids: List of LD IDs that are allocated to this port
        """
        if port_index < 0 or port_index >= len(self._allocated_ld):
            logger.error(self._create_message(f"Port index {port_index} is out of bounds"))
            return

        # For now, we'll still replace the entire list to maintain compatibility
        # TODO: In the future, this could be enhanced to handle partial updates
        # by comparing with the current FMLD state to determine which LDs to add/remove
        self._allocated_ld[port_index] = ld_ids
        logger.info(self._create_message(f"Updated LD allocations for port {port_index}: {ld_ids}"))

    def sync_with_fmld_state(self, port_index: int, fmld_allocations: dict):
        """Sync virtual switch LD allocations with FMLD state.

        Args:
            port_index: The port index to sync
            fmld_allocations: Dictionary of LD ID -> allocation value from FMLD
        """
        if port_index < 0 or port_index >= len(self._allocated_ld):
            logger.error(self._create_message(f"Port index {port_index} is out of bounds"))
            return

        # Extract only the allocated LD IDs (non-zero values)
        allocated_ld_ids = [ld_id for ld_id, value in fmld_allocations.items() if value > 0]

        self._allocated_ld[port_index] = allocated_ld_ids
        logger.info(
            self._create_message(
                f"Synced LD allocations for port {port_index} with FMLD state: {allocated_ld_ids}"
            )
        )

    async def _call_event_handler(self, vppb_index: int, binding_status: PPB_BINDING_STATUS):
        if not self._event_handler:
            return
        event = SwitchUpdateEvent(
            vcs_id=self._id, vppb_id=vppb_index, binding_status=binding_status
        )
        await self._event_handler(event)
