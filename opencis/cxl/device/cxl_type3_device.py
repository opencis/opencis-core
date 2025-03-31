"""
Copyright (c) 2024, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from asyncio import create_task, gather
from enum import Enum, auto
from typing import Optional


from opencis.cxl.component.cxl_io_callback_data import CxlIoCallbackData
from opencis.cxl.config_space.dvsec.cxl_devices import (
    DvsecCxlCacheableRangeOptions,
    DvsecCxlCapabilityOptions,
)
from opencis.cxl.config_space.serial_number.common import DeviceSNCapabilityOptions
from opencis.cxl.transport.transaction import (
    CXL_MEM_S2MBISNP_OPCODE,
    CxlMemBISnpPacket,
)
from opencis.util.logger import logger
from opencis.util.component import RunnableComponent
from opencis.cxl.component.cxl_connection import CxlConnection
from opencis.cxl.component.cxl_mem_manager import CxlMemManager
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
    SW_MLD_DID,
    PCI_CLASS,
    MEMORY_CONTROLLER_SUBCLASS,
)
from opencis.pci.component.mmio_manager import BarEntry
from opencis.pci.component.config_space_manager import PCI_DEVICE_TYPE


class CXL_T3_DEV_TYPE(Enum):
    SLD = auto()
    MLD = auto()


class CxlType3Device(RunnableComponent):
    def __init__(
        self,
        transport_connection: CxlConnection,
        memory_size: int,
        memory_file: str,
        serial_number: str,
        dev_type: CXL_T3_DEV_TYPE,
        decoder_count: HDM_DECODER_COUNT = HDM_DECODER_COUNT.DECODER_4,
        label: Optional[str] = None,
    ):
        # pylint: disable=unused-argument
        super().__init__(label)
        self._memory_size = memory_size
        self._memory_file = memory_file
        self._serial_number = serial_number
        self._dev_type = dev_type
        self._decoder_count = decoder_count
        self._cxl_memory_device_component = None
        self._upstream_connection = transport_connection

        self._cxl_io_manager = CxlIoManager(
            self._upstream_connection.mmio_fifo,
            None,
            self._upstream_connection.cfg_fifo,
            None,
            device_type=PCI_DEVICE_TYPE.ENDPOINT,
            init_callback=self._init_device,
            label=self._label,
        )
        self._cxl_mem_manager = CxlMemManager(
            upstream_fifo=self._upstream_connection.cxl_mem_fifo,
            label=self._label,
        )

        # Update CxlMemManager with a CxlMemoryDeviceComponent
        self._cxl_mem_manager.set_memory_device_component(self._cxl_memory_device_component)

    def _init_device(
        self,
        cxl_io_callback_data: CxlIoCallbackData,
    ):
        # Create PCiComponent
        pci_identity = PciComponentIdentity(
            vendor_id=EEUM_VID,
            device_id=SW_SLD_DID if self._dev_type is CXL_T3_DEV_TYPE.SLD else SW_MLD_DID,
            base_class_code=PCI_CLASS.MEMORY_CONTROLLER,
            sub_class_coce=MEMORY_CONTROLLER_SUBCLASS.CXL_MEMORY_DEVICE,
            programming_interface=0x10,
        )
        pci_component = PciComponent(pci_identity, cxl_io_callback_data.mmio_manager)

        # Create CxlMemoryDeviceComponent
        logger.debug(f"Total Capacity = {self._memory_size:x}")
        identity = MemoryDeviceIdentity()
        identity.fw_revision = MemoryDeviceIdentity.ascii_str_to_int("EEUM EMU 1.0", 16)
        identity.set_total_capacity(self._memory_size)
        identity.set_volatile_only_capacity(self._memory_size)

        logger.debug(f"Initialized size at device level: 0x{identity.volatile_only_capacity:08x}")
        self._cxl_memory_device_component = CxlMemoryDeviceComponent(
            identity,
            decoder_count=self._decoder_count,
            memory_file=self._memory_file,
            label=self._label,
        )

        # Create CombinedMmioRegister
        options = CombinedMmioRegiterOptions(cxl_component=self._cxl_memory_device_component)
        mmio_register = CombinedMmioRegister(options=options, parent_name="mmio")

        # Update MmioManager with new bar entires
        cxl_io_callback_data.mmio_manager.set_bar_entries([BarEntry(register=mmio_register)])

        config_space_register_options = CxlType3SldConfigSpaceOptions(
            pci_component=pci_component,
            dvsec=DvsecConfigSpaceOptions(
                register_locator=DvsecRegisterLocatorOptions(
                    registers=mmio_register.get_dvsec_register_offsets()
                ),
                device_type=CXL_DEVICE_TYPE.LD,
                memory_device_component=self._cxl_memory_device_component,
                capability_options=DvsecCxlCapabilityOptions(
                    cache_capable=0,
                    mem_capable=1,
                    hdm_count=1,
                    cache_writeback_and_invalidate_capable=0,
                    cache_size_unit=0b0,
                    cache_size=0,
                ),
                cacheable_address_range=DvsecCxlCacheableRangeOptions(0x0, 0x0),
            ),
            doe=CxlDoeExtendedCapabilityOptions(
                cdat_entries=self._cxl_memory_device_component.get_cdat_entries()
            ),
            serial_number=DeviceSNCapabilityOptions(sn=self._serial_number),
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

    async def init_bi_snp(self):
        # TODO: implement real BISnp logic
        # This is only a placeholder for tests
        packet = CxlMemBISnpPacket.create(0x00, CXL_MEM_S2MBISNP_OPCODE.BISNP_DATA)
        await self._cxl_mem_manager.process_cxl_mem_bisnp_packet(packet)

    async def _run(self):
        # pylint: disable=duplicate-code
        run_tasks = [
            create_task(self._cxl_io_manager.run()),
            create_task(self._cxl_mem_manager.run()),
        ]
        wait_tasks = [
            create_task(self._cxl_io_manager.wait_for_ready()),
            create_task(self._cxl_mem_manager.wait_for_ready()),
        ]
        await gather(*wait_tasks)
        await self._change_status_to_running()
        await gather(*run_tasks)

    async def _stop(self):
        # pylint: disable=duplicate-code
        tasks = [
            create_task(self._cxl_io_manager.stop()),
            create_task(self._cxl_mem_manager.stop()),
        ]
        await gather(*tasks)
