"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

# pylint: disable=duplicate-code
from asyncio import create_task, gather
from dataclasses import dataclass
from typing import Optional
from opencis.cxl.component.cxl_cache_dcoh import CxlCacheDcoh

from opencis.cxl.component.cxl_io_callback_data import CxlIoCallbackData
from opencis.cxl.config_space.dvsec.cxl_devices import (
    DvsecCxlCacheableRangeOptions,
    DvsecCxlCapabilityOptions,
)
from opencis.util.logger import logger
from opencis.util.component import RunnableComponent
from opencis.cxl.component.cxl_connection import CxlConnection
from opencis.cxl.component.cxl_io_manager import CxlIoManager
from opencis.cxl.mmio import CombinedMmioRegister, CombinedMmioRegiterOptions
from opencis.cxl.config_space.dvsec import (
    CXL_DEVICE_TYPE,
    DvsecConfigSpaceOptions,
    DvsecRegisterLocatorOptions,
)
from opencis.cxl.config_space.doe.doe import CxlDoeExtendedCapabilityOptions
from opencis.cxl.config_space.device import (
    CxlType3SldConfigSpace,
    CxlType3SldConfigSpaceOptions,
)
from opencis.cxl.component.cxl_memory_device_component import (
    CxlMemoryDeviceComponent,
    MemoryDeviceIdentity,
    HDM_DECODER_COUNT,
)
from opencis.pci.component.pci import (
    PciComponent,
    PciComponentIdentity,
    EEUM_VID,
    SW_SLD_DID,
    PCI_CLASS,
    MEMORY_CONTROLLER_SUBCLASS,
)
from opencis.pci.component.mmio_manager import BarEntry
from opencis.pci.component.config_space_manager import PCI_DEVICE_TYPE
from opencis.cxl.component.cache_controller import (
    CacheController,
    CacheControllerConfig,
)
from opencis.cxl.transport.cache_fifo import CacheFifoPair
from opencis.cxl.component.cxl_mem_dcoh import CxlMemDcoh
from opencis.util.number_const import KB, MB


@dataclass
class CxlType2DeviceConfig:
    device_name: str
    transport_connection: CxlConnection
    memory_size: int
    memory_file: str
    decoder_count: HDM_DECODER_COUNT = HDM_DECODER_COUNT.DECODER_4
    cache_line_count: int = 32
    cache_line_size: int = 64 * KB
    device_id: int = 0


class CxlType2Device(RunnableComponent):
    def __init__(self, config: CxlType2DeviceConfig):
        self._label = lambda class_name: f"{config.device_name}:{class_name}"
        super().__init__(self._label)

        cache_to_coh_agent_fifo = CacheFifoPair()
        coh_agent_to_cache_fifo = CacheFifoPair()

        self._memory_size = config.memory_size
        self._memory_file = config.memory_file
        self._decoder_count = config.decoder_count
        self._cxl_memory_device_component = None
        self._upstream_connection = config.transport_connection
        self._cache_line_count = config.cache_line_count
        self._cache_line_size = config.cache_line_size
        self._mmio_manager = None

        self._cxl_io_manager = CxlIoManager(
            self._upstream_connection.mmio_fifo,
            None,
            self._upstream_connection.cfg_fifo,
            None,
            device_type=PCI_DEVICE_TYPE.ENDPOINT,
            init_callback=self._init_device,
            label=self._label,
        )

        self._cxl_cache_dcoh = CxlCacheDcoh(
            cache_to_coh_agent_fifo=cache_to_coh_agent_fifo,
            coh_agent_to_cache_fifo=coh_agent_to_cache_fifo,
            upstream_fifo=self._upstream_connection.cxl_cache_fifo,
            label=self._label,
            device_id=config.device_id,
        )

        self._cxl_mem_dcoh = CxlMemDcoh(
            cache_to_coh_agent_fifo=cache_to_coh_agent_fifo,
            coh_agent_to_cache_fifo=coh_agent_to_cache_fifo,
            upstream_fifo=self._upstream_connection.cxl_mem_fifo,
            label=self._label,
            device_id=config.device_id,
        )

        # Update CxlMemManager with a CxlMemoryDeviceComponent
        self._cxl_mem_dcoh.set_memory_device_component(self._cxl_memory_device_component)
        cache_num_assoc = 4
        cache_controller_config = CacheControllerConfig(
            component_name=config.device_name,
            processor_to_cache_fifo=None,
            cache_to_coh_agent_fifo=cache_to_coh_agent_fifo,
            coh_agent_to_cache_fifo=coh_agent_to_cache_fifo,
            cache_num_assoc=cache_num_assoc,
            cache_num_set=self._cache_line_count // cache_num_assoc,
        )
        self._cache_controller = CacheController(cache_controller_config)

        # DEBUG tool
        # device_processor_config = DeviceLlcIoGenConfig(
        #     device_name=config.device_name,
        #     processor_to_cache_fifo=processor_to_cache_fifo,
        #     memory_size=config.memory_size,
        # )
        # self._device_simple_processor = DeviceLlcIoGen(device_processor_config)

    async def read_mmio(self, addr: int, size: int, bar: int = 0):
        return await self._mmio_manager.read_mmio(addr, size, bar)

    async def write_mmio(self, addr: int, size: int, data: int, bar: int = 0):
        await self._mmio_manager.write_mmio(addr, size, data, bar)

    def _init_device(
        self,
        cxl_io_callback_data: CxlIoCallbackData,
    ):
        self._mmio_manager = cxl_io_callback_data.mmio_manager

        # Create PCiComponent
        pci_identity = PciComponentIdentity(
            vendor_id=EEUM_VID,
            device_id=SW_SLD_DID,
            base_class_code=PCI_CLASS.MEMORY_CONTROLLER,
            sub_class_coce=MEMORY_CONTROLLER_SUBCLASS.CXL_MEMORY_DEVICE,
            programming_interface=0x10,
        )
        pci_component = PciComponent(pci_identity, self._mmio_manager)

        # Create CxlMemoryDeviceComponent
        logger.debug(f"Total Capacity = {self._memory_size:x}")
        identity = MemoryDeviceIdentity()
        identity.fw_revision = MemoryDeviceIdentity.ascii_str_to_int("EEUM EMU 1.0", 16)
        identity.set_total_capacity(self._memory_size)
        identity.set_volatile_only_capacity(self._memory_size)
        self._cxl_memory_device_component = CxlMemoryDeviceComponent(
            identity,
            decoder_count=self._decoder_count,
            memory_file=self._memory_file,
            label=self._label,
            cache_lines=self._cache_line_count,
        )

        # Create CombinedMmioRegister
        options = CombinedMmioRegiterOptions(cxl_component=self._cxl_memory_device_component)
        mmio_register = CombinedMmioRegister(options=options, parent_name="mmio")

        # Update MmioManager with new bar entires
        self._mmio_manager.set_bar_entries([BarEntry(register=mmio_register)])
        cache_size_unit = 0
        if self._cache_line_size == 64 * KB:
            cache_size_unit = 0x1
        elif self._cache_line_size == 1 * MB:
            cache_size_unit = 0x2
        else:
            raise Exception("cache_line_size should either be 64KiB or 1MiB")
        # The options can be reused from Type3
        # But maybe we should change its name in the future
        config_space_register_options = CxlType3SldConfigSpaceOptions(
            pci_component=pci_component,
            dvsec=DvsecConfigSpaceOptions(
                register_locator=DvsecRegisterLocatorOptions(
                    registers=mmio_register.get_dvsec_register_offsets()
                ),
                device_type=CXL_DEVICE_TYPE.ACCEL_T2,
                memory_device_component=self._cxl_memory_device_component,
                capability_options=DvsecCxlCapabilityOptions(
                    cache_capable=1,
                    mem_capable=1,
                    hdm_count=1,
                    cache_writeback_and_invalidate_capable=1,
                    cache_size_unit=cache_size_unit,
                    cache_size=self._cache_line_count,
                ),
                # TODO: Use a real range instead of the placeholder range
                cacheable_address_range=DvsecCxlCacheableRangeOptions(0x0, 0xFFFFFFFF0000),
            ),
            doe=CxlDoeExtendedCapabilityOptions(
                cdat_entries=self._cxl_memory_device_component.get_cdat_entries()
            ),
        )
        config_space_register = CxlType3SldConfigSpace(
            options=config_space_register_options, parent_name="cfgspace"
        )

        # ------------------------------
        # Update managers with registers
        # ------------------------------

        # Update ConfigSpaceManager with config space register
        cxl_io_callback_data.config_space_manager.set_register(config_space_register)

    def get_reg_vals(self):
        return self._cxl_io_manager.get_cfg_reg_vals()

    # TODO: change to match more efficient/accurate versions in cxl_type1_device.py
    async def cxl_cache_readline(self, hpa: int) -> Optional[int]:
        raise NotImplementedError()

    async def cxl_cache_writeline(self, hpa: int, data: int):
        raise NotImplementedError()

    async def read_mem_dpa(self, dpa: int, size: int = 64) -> int:
        if not self._cxl_memory_device_component:
            raise RuntimeError(self._create_message("Memory device not yet initialized"))
        return await self._cache_controller.cache_coherent_load(dpa, size)

    async def write_mem_dpa(self, dpa: int, data: int, size: int = 64):
        if not self._cxl_memory_device_component:
            raise RuntimeError(self._create_message("Memory device not yet initialized"))
        await self._cache_controller.cache_coherent_store(dpa, size, data)

    async def _run(self):
        # pylint: disable=duplicate-code
        run_tasks = [
            create_task(self._cxl_io_manager.run()),
            create_task(self._cxl_mem_dcoh.run()),
            create_task(self._cache_controller.run()),
        ]
        wait_tasks = [
            create_task(self._cxl_io_manager.wait_for_ready()),
            create_task(self._cxl_mem_dcoh.wait_for_ready()),
            create_task(self._cache_controller.wait_for_ready()),
        ]
        await gather(*wait_tasks)
        await self._change_status_to_running()
        await gather(*run_tasks)

    async def _stop(self):
        # pylint: disable=duplicate-code
        tasks = [
            create_task(self._cxl_io_manager.stop()),
            create_task(self._cxl_mem_dcoh.stop()),
            create_task(self._cache_controller.stop()),
        ]
        await gather(*tasks)
