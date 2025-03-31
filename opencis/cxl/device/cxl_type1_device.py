"""
Copyright (c) 2024, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

# pylint: disable=duplicate-code,unused-import
from asyncio import (
    create_task,
    gather,
)
from dataclasses import dataclass
from typing import Optional

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
from opencis.pci.component.config_space_manager import (
    ConfigSpaceManager,
    PCI_DEVICE_TYPE,
)
from opencis.cxl.component.cache_controller import (
    CacheController,
    CacheControllerConfig,
)
from opencis.cxl.transport.memory_fifo import MemoryFifoPair
from opencis.cxl.transport.cache_fifo import CacheFifoPair
from opencis.cxl.component.device_llc_iogen import (
    DeviceLlcIoGen,
    DeviceLlcIoGenConfig,
)
from opencis.cxl.component.cxl_cache_dcoh import CxlCacheDcoh
from opencis.util.number_const import KB, MB


@dataclass
class CxlType1DeviceConfig:
    device_name: str
    transport_connection: CxlConnection
    cache_line_count: int = 32
    cache_line_size: int = 64 * KB
    device_id: int = 0


class CxlType1Device(RunnableComponent):
    def __init__(
        self,
        config: CxlType1DeviceConfig,
    ):
        self._label = lambda class_name: f"{config.device_name}:{class_name}"
        super().__init__(self._label)

        cache_to_coh_agent_fifo = CacheFifoPair()
        coh_agent_to_cache_fifo = CacheFifoPair()
        self._mmio_manager = None
        self._memory_size = 0
        self._cxl_cache_device_component = None
        self._upstream_connection = config.transport_connection
        self._cache_line_count = config.cache_line_count
        self._cache_line_size = config.cache_line_size
        self._cxl_io_manager = CxlIoManager(
            self._upstream_connection.mmio_fifo,
            None,
            self._upstream_connection.cfg_fifo,
            None,
            device_type=PCI_DEVICE_TYPE.ENDPOINT,
            init_callback=self._init_device,
            label=self._label,
        )

        self._cxl_memory_device_component = None

        self._cxl_cache_dcoh = CxlCacheDcoh(
            cache_to_coh_agent_fifo=cache_to_coh_agent_fifo,
            coh_agent_to_cache_fifo=coh_agent_to_cache_fifo,
            upstream_fifo=self._upstream_connection.cxl_cache_fifo,
            label=self._label,
            device_id=config.device_id,
        )

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
        #     memory_size=config.host_mem_size,
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
            decoder_count=0,
            memory_file="",
            label=self._label,
            cache_lines=self._cache_line_count,
            cache_line_size=self._cache_line_size,
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
                device_type=CXL_DEVICE_TYPE.ACCEL_T1,
                memory_device_component=self._cxl_memory_device_component,
                capability_options=DvsecCxlCapabilityOptions(
                    cache_capable=1,
                    mem_capable=0,
                    hdm_count=0,
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

    async def cxl_cache_readline(self, addr: int, cqid: Optional[int] = None) -> int:
        logger.debug(f"Beware: cqid {cqid} is not currently implemented.")
        return await self._cache_controller.cache_coherent_load(addr, 64)

    async def cxl_cache_writeline(self, addr: int, data: int, cqid: Optional[int] = None):
        logger.debug(f"Beware: cqid {cqid} is not currently implemented.")
        await self._cache_controller.cache_coherent_store(addr, 64, data)

    async def cxl_cache_read(self, address, size) -> bytes:
        end = address + size
        result = b""
        for cacheline_offset in range(address, address + size, 64):
            cacheline = await self.cxl_cache_readline(cacheline_offset)
            chunk_size = min(64, (end - cacheline_offset))
            chunk_data = cacheline.to_bytes(64, "little")
            result += chunk_data[:chunk_size]
        return result

    async def cxl_cache_write(self, address, size, value):
        if address % 64 != 0 or size % 64 != 0:
            raise Exception(f"Size {size} and address 0x{address:x} must be aligned to 64!")

        chunk_count = 0
        while size > 0:
            message = self._create_message(f"Host Memory: Writing 0x{value:08x} to 0x{address:08x}")
            logger.debug(message)
            low_64_byte = value & ((1 << (64 * 8)) - 1)
            await self.cxl_cache_writeline(address + (chunk_count * 64), low_64_byte)
            size -= 64
            chunk_count += 1
            value >>= 64 * 8

    async def _run(self):
        # pylint: disable=duplicate-code
        run_tasks = [
            create_task(self._cxl_io_manager.run()),
            create_task(self._cxl_cache_dcoh.run()),
            create_task(self._cache_controller.run()),
        ]
        wait_tasks = [
            create_task(self._cxl_io_manager.wait_for_ready()),
            create_task(self._cxl_cache_dcoh.wait_for_ready()),
            create_task(self._cache_controller.wait_for_ready()),
        ]
        await gather(*wait_tasks)
        await self._change_status_to_running()
        await gather(*run_tasks)

    async def _stop(self):
        # pylint: disable=duplicate-code
        tasks = [
            create_task(self._cxl_io_manager.stop()),
            create_task(self._cxl_cache_dcoh.stop()),
            create_task(self._cache_controller.stop()),
        ]
        await gather(*tasks)
