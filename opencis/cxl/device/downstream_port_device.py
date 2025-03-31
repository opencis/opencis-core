"""
Copyright (c) 2024, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from typing import Optional
from asyncio import create_task, gather, Condition

from opencis.cxl.component.cxl_io_callback_data import CxlIoCallbackData
from opencis.util.logger import logger
from opencis.util.component import RunnableComponent
from opencis.util.async_gatherer import AsyncGatherer
from opencis.cxl.component.common import CXL_COMPONENT_TYPE
from opencis.cxl.component.cxl_cache_manager import CxlCacheManager
from opencis.cxl.component.cxl_connection import CxlConnection
from opencis.cxl.component.virtual_switch.vppb_routing_info import VppbRoutingInfo
from opencis.cxl.component.cxl_mem_manager import CxlMemManager
from opencis.cxl.component.cxl_io_manager import CxlIoManager
from opencis.cxl.component.cxl_bridge_component import (
    CxlDownstreamPortComponent,
)
from opencis.cxl.mmio import CombinedMmioRegister, CombinedMmioRegiterOptions
from opencis.cxl.device.port_device import CxlPortDevice
from opencis.cxl.device.pci_to_pci_bridge_device import PpbDevice
from opencis.cxl.config_space.port import (
    CxlDownstreamPortConfigSpace,
    CxlDownstreamPortConfigSpaceOptions,
)
from opencis.cxl.config_space.dvsec import (
    DvsecConfigSpaceOptions,
    DvsecRegisterLocatorOptions,
    CXL_DEVICE_TYPE,
)
from opencis.pci.component.pci import (
    PciComponentIdentity,
    PciBridgeComponent,
    PCI_BRIDGE_TYPE,
    PCI_CLASS,
    PCI_BRIDGE_SUBCLASS,
    PCI_DEVICE_PORT_TYPE,
    EEUM_VID,
    SW_DSP_DID,
)
from opencis.pci.component.mmio_manager import BarEntry
from opencis.pci.component.config_space_manager import PCI_DEVICE_TYPE


class SleepLoop(RunnableComponent):
    def __init__(self):
        super().__init__()
        self._task = None
        self._running = False
        self._loopcond = Condition()

    async def _process(self):
        await self._loopcond.acquire()
        try:
            await self._change_status_to_running()
            if self._running:
                await self._loopcond.wait()
        finally:
            self._loopcond.release()

    async def _run(self):
        self._running = True
        self._task = create_task(self._process())
        await self.wait_for_ready()
        await self._task

    async def _stop(self):
        self._running = False
        await self._loopcond.acquire()
        self._loopcond.notify()
        self._loopcond.release()
        await self._task


class DownstreamPortDevice(CxlPortDevice):
    def __init__(
        self,
        transport_connection: CxlConnection,
        port_index: int = 0,
    ):
        super().__init__(transport_connection, port_index)

        self._tasks = AsyncGatherer()
        self._stop_tasks = []

        # Per LD
        self._pci_bridge_component = {}
        self._pci_registers = {}
        self._cxl_component = {}

        self._vppb_upstream_connection = {}
        self._vppb_downstream_connection = {}

        self._ppb_device: PpbDevice = None
        self._ppb_bind = None
        self._vppb_index = -1

        self._cxl_io_manager = {}
        self._cxl_mem_manager = {}
        self._cxl_cache_manager = {}

        # Create a dummy process to keep the component running
        # TODO: cleaner method
        self._dummy_process = SleepLoop()

    def _init_device(
        self,
        cxl_io_callback_data: CxlIoCallbackData,
    ):
        ld_id = cxl_io_callback_data.ld_id
        pci_identity = PciComponentIdentity(
            vendor_id=EEUM_VID,
            device_id=SW_DSP_DID,
            base_class_code=PCI_CLASS.BRIDGE,
            sub_class_coce=PCI_BRIDGE_SUBCLASS.PCI_BRIDGE,
            programming_interface=0x00,
            device_port_type=PCI_DEVICE_PORT_TYPE.DOWNSTREAM_PORT_OF_PCI_EXPRESS_SWITCH,
        )
        self._pci_bridge_component[ld_id] = PciBridgeComponent(
            identity=pci_identity,
            type=PCI_BRIDGE_TYPE.DOWNSTREAM_PORT,
            mmio_manager=cxl_io_callback_data.mmio_manager,
            label=self._get_label(),
        )

        # Create MMIO register
        cxl_component = CxlDownstreamPortComponent()
        self._cxl_component[ld_id] = cxl_component
        mmio_options = CombinedMmioRegiterOptions(cxl_component=cxl_component)
        mmio_register = CombinedMmioRegister(options=mmio_options)
        cxl_io_callback_data.mmio_manager.set_bar_entries([BarEntry(mmio_register)])

        # Create Config Space Register
        pci_registers_options = CxlDownstreamPortConfigSpaceOptions(
            pci_bridge_component=self._pci_bridge_component[ld_id],
            dvsec=DvsecConfigSpaceOptions(
                device_type=CXL_DEVICE_TYPE.DSP,
                register_locator=DvsecRegisterLocatorOptions(
                    registers=mmio_register.get_dvsec_register_offsets()
                ),
            ),
        )
        self._pci_registers[ld_id] = CxlDownstreamPortConfigSpace(options=pci_registers_options)
        cxl_io_callback_data.config_space_manager.set_register(self._pci_registers[ld_id])

    def _get_label(self) -> str:
        return f"DSP{self._port_index}"

    def _create_message(self, message: str) -> str:
        message = f"[{self.__class__.__name__}:{self._get_label()}] {message}"
        return message

    def get_reg_vals(self, ld_id: int = 0):
        print(f"len: {len(self._cxl_io_manager)}")
        return self._cxl_io_manager[ld_id].get_cfg_reg_vals()

    def set_vppb_index(self, vppb_index: int):
        self._vppb_index = vppb_index

    def get_device_type(self) -> CXL_COMPONENT_TYPE:
        return CXL_COMPONENT_TYPE.DSP

    def set_routing_table(self, vppb_routing_info: VppbRoutingInfo):
        self._pci_bridge_component[vppb_routing_info.ld_id].set_routing_table(vppb_routing_info)

    def get_secondary_bus_number(self, ld_id: int):
        return self._pci_registers[ld_id].pci.secondary_bus_number

    async def bind_to_vppb(self, ld_id: int):
        # TODO: Check for invalid ld_id
        logger.info(self._create_message(f"Binding LD-ID {ld_id} to vPPB{self._vppb_index}"))
        self._vppb_upstream_connection[ld_id] = CxlConnection()
        self._vppb_downstream_connection[ld_id] = CxlConnection()
        self._cxl_io_manager[ld_id] = CxlIoManager(
            self._vppb_upstream_connection[ld_id].mmio_fifo,
            self._vppb_downstream_connection[ld_id].mmio_fifo,
            self._vppb_upstream_connection[ld_id].cfg_fifo,
            self._vppb_downstream_connection[ld_id].cfg_fifo,
            device_type=PCI_DEVICE_TYPE.DOWNSTREAM_BRIDGE,
            init_callback=self._init_device,
            label=self._get_label(),
            ld_id=ld_id,
        )
        self._cxl_mem_manager[ld_id] = CxlMemManager(
            upstream_fifo=self._vppb_upstream_connection[ld_id].cxl_mem_fifo,
            downstream_fifo=self._vppb_downstream_connection[ld_id].cxl_mem_fifo,
            label=self._get_label(),
        )
        self._cxl_cache_manager[ld_id] = CxlCacheManager(
            upstream_fifo=self._vppb_upstream_connection[ld_id].cxl_cache_fifo,
            downstream_fifo=self._vppb_downstream_connection[ld_id].cxl_cache_fifo,
            label=self._get_label(),
        )

        self._pci_bridge_component[ld_id].set_port_number(self._vppb_index)

        wait_tasks = []

        self._tasks.add_task(self._cxl_io_manager[ld_id].run())
        wait_tasks.append(self._cxl_io_manager[ld_id].wait_for_ready())
        self._stop_tasks.append(self._cxl_io_manager[ld_id])

        self._tasks.add_task(self._cxl_mem_manager[ld_id].run())
        wait_tasks.append(self._cxl_mem_manager[ld_id].wait_for_ready())
        self._stop_tasks.append(self._cxl_mem_manager[ld_id])

        self._tasks.add_task(self._cxl_cache_manager[ld_id].run())
        wait_tasks.append(self._cxl_cache_manager[ld_id].wait_for_ready())
        self._stop_tasks.append(self._cxl_cache_manager[ld_id])

        await gather(*wait_tasks)

        return (
            self._cxl_mem_manager[ld_id],
            self._cxl_io_manager[ld_id],
            self._cxl_cache_manager[ld_id],
            self._pci_bridge_component[ld_id],
            self._pci_registers[ld_id],
            self._cxl_component[ld_id],
            self._vppb_upstream_connection[ld_id],
            self._vppb_downstream_connection[ld_id],
        )

    # Caller should always await this function
    async def unbind_from_vppb(self, ld_id: int):
        tasks = []
        self._vppb_downstream_connection.pop(ld_id, None)
        self._vppb_upstream_connection.pop(ld_id, None)
        io_task = self._cxl_io_manager.pop(ld_id, None)
        mem_task = self._cxl_mem_manager.pop(ld_id, None)
        cache_task = self._cxl_cache_manager.pop(ld_id, None)
        if io_task:
            tasks.append(create_task(io_task.stop()))
            self._stop_tasks.remove(io_task)
        if mem_task:
            tasks.append(create_task(mem_task.stop()))
            self._stop_tasks.remove(mem_task)
        if cache_task:
            tasks.append(create_task(cache_task.stop()))
            self._stop_tasks.remove(cache_task)
        await gather(*tasks)

        logger.info(
            self._create_message(f"Unbinding ld_id {ld_id} to vPPB{self._vppb_index} (noop)")
        )
        # Nothing to do here

    def get_cxl_component(self) -> CxlDownstreamPortComponent:
        return self._cxl_component

    def set_ppb(self, ppb_device: PpbDevice, ppb_bind):
        self._ppb_device = ppb_device
        self._ppb_bind = ppb_bind

    def get_ppb_device(self) -> Optional[PpbDevice]:
        return self._ppb_device

    def get_ppb_bind(self):
        return self._ppb_bind

    async def _run(self):
        logger.info(self._create_message("Starting"))
        await self._change_status_to_running()
        self._tasks.add_task(self._dummy_process.run())
        self._stop_tasks.append(self._dummy_process)
        await self._dummy_process.wait_for_ready()
        await self._tasks.wait_for_completion()
        logger.info(self._create_message("Stopped"))

    async def _stop(self):
        logger.info(self._create_message("Stopping"))
        await self._dummy_process.wait_for_ready()
        stop_tasks = [create_task(task.stop()) for task in self._stop_tasks]
        await gather(*stop_tasks)
