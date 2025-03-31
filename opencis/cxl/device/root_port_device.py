"""
Copyright (c) 2024, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

import asyncio
from dataclasses import dataclass, field
from typing import Optional, List, cast

from opencis.cxl.mmio.component_register.memcache_register.capability import (
    CxlCapabilityIDToName,
)
from opencis.util.logger import logger
from opencis.util.component import RunnableComponent
from opencis.cxl.component.cxl_connection import CxlConnection
from opencis.pci.component.pci import (
    PCI_CLASS,
    PCI_BRIDGE_SUBCLASS,
    memory_base_addr_to_regval,
    memory_limit_addr_to_regval,
    memory_base_regval_to_addr,
    memory_limit_regval_to_addr,
)
from opencis.pci.config_space.pci import REG_ADDR, BAR_OFFSETS, BAR_REGISTER_SIZE
from opencis.util.pci import (
    create_bdf,
    extract_bus_from_bdf,
    extract_device_from_bdf,
    extract_function_from_bdf,
    bdf_to_string,
    generate_bdfs_for_bus,
)
from opencis.cxl.transport.transaction import (
    CXL_MEM_M2SBIRSP_OPCODE,
    BasePacket,
    CxlIoCfgRdPacket,
    CxlIoCfgWrPacket,
    CxlIoCompletionPacket,
    CxlIoCompletionWithDataPacket,
    CxlIoMemRdPacket,
    CxlIoMemWrPacket,
    CxlMemBIRspPacket,
    CxlMemMemWrPacket,
    CxlMemMemRdPacket,
    CxlMemMemDataPacket,
    is_cxl_io_completion_status_sc,
    is_cxl_io_completion_status_ur,
    is_cxl_mem_data,
    is_cxl_mem_completion,
)

BRIDGE_CLASS = PCI_CLASS.BRIDGE << 8 | PCI_BRIDGE_SUBCLASS.PCI_BRIDGE


@dataclass
class MemoryEnumerationInfo:
    memory_base: int = 0
    memory_limit: int = 0


@dataclass
class BarEnumerationInfo:
    memory_base: int = 0
    memory_limit: int = 0


@dataclass
class MmioEnumerationInfo:
    memory_base: int = 0
    memory_limit: int = 0
    bar_blocks: List[BarEnumerationInfo] = field(default_factory=list)


@dataclass
class DvsecRegisterLocator:
    bar: int = 0
    offset: int = 0


@dataclass
class DvsecRegisterLocators:
    component_registers: Optional[DvsecRegisterLocator] = None
    cxl_device_registers: Optional[DvsecRegisterLocator] = None


@dataclass
class PciDvsecCapabilities:
    register_locators: DvsecRegisterLocators = field(default_factory=DvsecRegisterLocators)


@dataclass
class PciCapabilities:
    dvsec: PciDvsecCapabilities = field(default_factory=PciDvsecCapabilities)
    serial_number: str = "0000000000000000"


@dataclass
# Should be merged with CxlCapabilityHeaderStructureOptions
class CxlCapabilities:
    ras: int = 0
    security: int = 0
    link: int = 0
    hdm_decoder: int = 0
    extended_security: int = 0
    ide: int = 0
    snoop_filter: int = 0
    timeout_isolation: int = 0
    cache_mem_extended_register: int = 0
    bi_route_table: int = 0
    bi_decoder: int = 0
    cache_id_route_table: int = 0
    cache_id_decoder: int = 0
    extended_hdm_decoder: int = 0

    def __setitem__(self, key, value):
        setattr(self, key, value)

    def __getitem__(self, key):
        return getattr(self, key)


@dataclass
class DeviceEnumerationInfo:
    bdf: int = 0
    vid_did: int = 0
    class_code: int = 0
    bars: List[int] = field(default_factory=list)
    mmio_range: MemoryEnumerationInfo = field(default_factory=MemoryEnumerationInfo)
    capabilities: PciCapabilities = field(default_factory=PciCapabilities)
    component_registers: CxlCapabilities = field(default_factory=CxlCapabilities)
    is_bridge: bool = False
    parent: Optional["DeviceEnumerationInfo"] = None
    children: List["DeviceEnumerationInfo"] = field(default_factory=list)
    cxl_device_size: int = 256 * 1024 * 1024

    def get_all_devices(self) -> List["DeviceEnumerationInfo"]:
        devices: List["DeviceEnumerationInfo"] = []
        devices.append(self)
        for device in self.children:
            devices += device.get_all_devices()
        return devices

    def get_all_cxl_devices(self) -> List["DeviceEnumerationInfo"]:
        devices: List["DeviceEnumerationInfo"] = []
        if self.class_code == 0x050210:
            devices.append(self)
        for device in self.children:
            devices += device.get_all_cxl_devices()
        return devices

    # TODO: Use Link Capability to get port number
    def get_port_number(self) -> int:
        if self.is_bridge:
            if self.parent is None:
                return 0
            if len(self.parent.children) == 1:
                return self.parent.get_port_number()

            return extract_device_from_bdf(self.bdf)
        if self.parent is None:
            raise Exception("Device must have a parent")
        return self.parent.get_port_number()


@dataclass
class EnumerationInfo:
    devices: List[DeviceEnumerationInfo] = field(default_factory=list)

    def get_all_devices(self) -> List[DeviceEnumerationInfo]:
        devices: List[DeviceEnumerationInfo] = []
        for device in self.devices:
            devices += device.get_all_devices()
        return devices


def check_if_successful_completion(packet):
    base_packet = cast(BasePacket, packet)
    assert is_cxl_io_completion_status_sc(base_packet)


def check_if_unsupported_packet(packet):
    base_packet = cast(BasePacket, packet)
    assert is_cxl_io_completion_status_ur(base_packet)


class CxlRootPortDevice(RunnableComponent):
    def __init__(
        self,
        downstream_connection: CxlConnection,
        secondary_bus: int = 1,
        label: Optional[str] = None,
        test_mode: bool = False,
    ):
        super().__init__(label)
        self._downstream_connection = downstream_connection
        self._secondary_bus = secondary_bus
        self._continue = True
        self._test_mode = test_mode
        self._run_fut = None
        self._next_tag = 0

        # set default HPA base address using port index
        self._cxl_hpa_base = 0x100000000000 | (int(label[-1]) << 40)
        self._used_hpa_size = 0

    """
    Base functions for CFG read/write and MMIO read/write
    """

    async def write_config(self, bdf: int, offset: int, size: int, value: int):
        bus = extract_bus_from_bdf(bdf)
        bdf_string = bdf_to_string(bdf)
        is_type0 = bus == self._secondary_bus
        if is_type0:
            # NOTE: For non-ARI component, only allow device 0
            device_num = extract_device_from_bdf(bdf)
            if device_num != 0:
                return

        packet = CxlIoCfgWrPacket.create(
            bdf, offset, size, value, is_type0, req_id=0, tag=self._next_tag
        )
        self._next_tag = (self._next_tag + 1) % 256

        cfg_fifo = self._downstream_connection.cfg_fifo
        await cfg_fifo.host_to_target.put(packet)

        # TODO: Wait for an incoming packet that matchs tag
        packet = await cfg_fifo.target_to_host.get()

        tpl_type_str = "CFG WR0" if is_type0 else "CFG WR1"

        if not is_cxl_io_completion_status_sc(packet):
            cpl_packet = cast(CxlIoCompletionPacket, packet)
            logger.debug(
                self._create_message(
                    f"[{bdf_string}] {tpl_type_str} @ 0x{offset:x}[{size}B] : "
                    + f"Unsuccessful, Status: 0x{cpl_packet.cpl_header.status:x}"
                )
            )
            return

        logger.debug(
            self._create_message(
                f"[{bdf_string}] {tpl_type_str} @ 0x{offset:x}[{size}B] : 0x{value:x}"
            )
        )

    async def read_config(self, bdf: int, offset: int, size: int) -> int:
        if offset + size > ((offset // 4) + 1) * 4:
            raise Exception("offset + size out of DWORD boundary")

        bit_mask = (1 << size * 8) - 1

        bus = extract_bus_from_bdf(bdf)
        bdf_string = bdf_to_string(bdf)
        is_type0 = bus == self._secondary_bus
        if is_type0:
            # NOTE: For non-ARI component, only allow device 0
            device_num = extract_device_from_bdf(bdf)
            if device_num != 0:
                return 0xFFFFFFFF & bit_mask

        packet = CxlIoCfgRdPacket.create(bdf, offset, size, is_type0, req_id=0, tag=self._next_tag)
        self._next_tag = (self._next_tag + 1) % 256
        cfg_fifo = self._downstream_connection.cfg_fifo
        await cfg_fifo.host_to_target.put(packet)

        # TODO: Wait for an incoming packet that matchs tag
        packet = await cfg_fifo.target_to_host.get()

        bit_offset = (offset % 4) * 8

        tpl_type_str = "CFG RD0" if is_type0 else "CFG RD1"

        if not is_cxl_io_completion_status_sc(packet):
            cpl_packet = cast(CxlIoCompletionPacket, packet)
            logger.debug(
                self._create_message(
                    f"[{bdf_string}] {tpl_type_str} @ 0x{offset:x}[{size}B] : "
                    + f"Unsuccessful, Status: 0x{cpl_packet.cpl_header.status:x}"
                )
            )
            return 0xFFFFFFFF & bit_mask

        cpld_packet = cast(CxlIoCompletionWithDataPacket, packet)
        data = (cpld_packet.data >> bit_offset) & bit_mask

        logger.debug(
            self._create_message(
                f"[{bdf_string}] {tpl_type_str} @ 0x{offset:x}[{size}B] : 0x{data:x}"
            )
        )
        return data

    async def write_mmio(self, address: int, data: int, size: int = 4, verbose: bool = True):
        message = self._create_message(f"MMIO: Writing 0x{data:08x} to 0x{address:08x}")
        if verbose:
            logger.info(message)
        else:
            logger.debug(message)
        packet = CxlIoMemWrPacket.create(address, size, data)
        await self._downstream_connection.mmio_fifo.host_to_target.put(packet)

    async def read_mmio(
        self, address: int, size: int = 4, verbose: bool = True
    ) -> CxlIoCompletionWithDataPacket:
        message = self._create_message(f"MMIO: Reading data from 0x{address:08x}")
        if verbose:
            logger.info(message)
        else:
            logger.debug(message)
        packet = CxlIoMemRdPacket.create(address, size)
        await self._downstream_connection.mmio_fifo.host_to_target.put(packet)
        packet = await self._downstream_connection.mmio_fifo.target_to_host.get()
        assert is_cxl_io_completion_status_sc(packet)
        cpld_packet = cast(CxlIoCompletionWithDataPacket, packet)
        return cpld_packet.data

    async def cxl_mem_read(self, address: int) -> int:
        logger.info(self._create_message(f"CXL.mem Read: HPA addr:0x{address:08x}"))
        packet = CxlMemMemRdPacket.create(address)
        await self._downstream_connection.cxl_mem_fifo.host_to_target.put(packet)
        try:
            async with asyncio.timeout(3):
                packet = await self._downstream_connection.cxl_mem_fifo.target_to_host.get()
            assert is_cxl_mem_data(packet)
            mem_data_packet = cast(CxlMemMemDataPacket, packet)
            return mem_data_packet.data
        except asyncio.exceptions.TimeoutError:
            logger.error(self._create_message("CXL.mem Read: Timed-out"))
            return None

    async def cxl_mem_write(self, address: int, data: int) -> int:
        logger.info(
            self._create_message(f"CXL.mem Write: HPA addr:0x{address:08x} data:0x{data:08x}")
        )
        packet = CxlMemMemWrPacket.create(address, data)
        await self._downstream_connection.cxl_mem_fifo.host_to_target.put(packet)
        try:
            async with asyncio.timeout(3):
                packet = await self._downstream_connection.cxl_mem_fifo.target_to_host.get()
            assert is_cxl_mem_completion(packet)
            return address - self._cxl_hpa_base
        except asyncio.exceptions.TimeoutError:
            logger.error(self._create_message("CXL.mem Write: Timed-out"))
            return None

    async def cxl_mem_birsp(
        self, opcode: CXL_MEM_M2SBIRSP_OPCODE, bi_id: int = 0, bi_tag: int = 0
    ) -> int:
        logger.info(self._create_message(f"CXL.mem BIRsp: opcode:0x{opcode:x}"))
        packet = CxlMemBIRspPacket.create(opcode, bi_id, bi_tag)
        await self._downstream_connection.cxl_mem_fifo.host_to_target.put(packet)
        return 0

    """
    Helper functions for PCI Config Space access
    """

    async def set_secondary_bus(self, bdf: int, secondary_bus: int):
        bdf_string = bdf_to_string(bdf)
        logger.info(
            self._create_message(f"Setting secondary bus of device {bdf_string} to {secondary_bus}")
        )
        await self.write_config(
            bdf,
            REG_ADDR.SECONDARY_BUS_NUMBER.START,
            REG_ADDR.SECONDARY_BUS_NUMBER.LEN,
            secondary_bus,
        )

    async def set_subordinate_bus(self, bdf: int, subordinate_bus: int):
        bdf_string = bdf_to_string(bdf)
        logger.info(
            self._create_message(
                f"Setting subordinate bus of device {bdf_string} to {subordinate_bus}"
            )
        )

        await self.write_config(
            bdf,
            REG_ADDR.SUBORDINATE_BUS_NUMBER.START,
            REG_ADDR.SUBORDINATE_BUS_NUMBER.LEN,
            subordinate_bus,
        )

    async def set_memory_base(self, bdf: int, address_base: int):
        bdf_string = bdf_to_string(bdf)
        logger.info(
            self._create_message(
                f"Setting memory base of device {bdf_string} to {address_base:08x}"
            )
        )
        address_base_regval = memory_base_addr_to_regval(address_base)
        await self.write_config(
            bdf,
            REG_ADDR.MEMORY_BASE.START,
            REG_ADDR.MEMORY_BASE.LEN,
            address_base_regval,
        )

    async def set_memory_limit(self, bdf: int, address_limit: int):
        logger.info(
            self._create_message(
                f"Setting memory limit of device {bdf_to_string(bdf)} to {address_limit:08x}"
            )
        )
        address_limit_regval = memory_limit_addr_to_regval(address_limit)
        await self.write_config(
            bdf,
            REG_ADDR.MEMORY_LIMIT.START,
            REG_ADDR.MEMORY_LIMIT.LEN,
            address_limit_regval,
        )

    async def set_bar0(self, bdf: int, bar_address: int):
        # TODO: Support 64-bit BAR
        await self.write_config(bdf, BAR_OFFSETS.BAR0, BAR_REGISTER_SIZE, bar_address)

    async def get_bar0_size(
        self,
        bdf: int,
    ) -> int:
        # TODO: Support 64-bit BAR
        data = await self.read_config(bdf, BAR_OFFSETS.BAR0, BAR_REGISTER_SIZE)
        if data == 0:
            return data
        return 0xFFFFFFFF - data + 1

    async def read_vid_did(self, bdf: int) -> Optional[int]:
        vid = await self.read_config(bdf, REG_ADDR.VENDOR_ID.START, REG_ADDR.VENDOR_ID.LEN)
        did = await self.read_config(bdf, REG_ADDR.DEVICE_ID.START, REG_ADDR.DEVICE_ID.LEN)
        logger.debug(self._create_message(f"VID: 0x{vid:x}"))
        logger.debug(self._create_message(f"DID: 0x{did:x}"))
        if did == 0xFFFF and vid == 0xFFFF:
            logger.debug(self._create_message(f"Device not found at {bdf_to_string(bdf)}"))
            return None
        return (did << 16) | vid

    async def read_class_code(self, bdf: int) -> int:
        data = await self.read_config(bdf, REG_ADDR.CLASS_CODE.START, REG_ADDR.CLASS_CODE.LEN)
        if data == 0xFFFF:
            raise Exception("Failed to read class code")
        return data

    async def read_bar(self, bdf, bar_id) -> int:
        offset = 0x10 + bar_id * 4
        size = 4
        data = await self.read_config(bdf, offset, size=size)
        if data is None:
            raise Exception(f"Failed to read bar {bar_id}")
        return data

    async def read_secondary_bus(self, bdf: int) -> int:
        data = await self.read_config(
            bdf,
            REG_ADDR.SECONDARY_BUS_NUMBER.START,
            REG_ADDR.SECONDARY_BUS_NUMBER.LEN,
        )
        if data is None:
            raise Exception("Failed to read secondary bus")
        return data

    async def read_subordinate_bus(self, bdf: int) -> int:
        data = await self.read_config(
            bdf,
            REG_ADDR.SUBORDINATE_BUS_NUMBER.START,
            REG_ADDR.SUBORDINATE_BUS_NUMBER.LEN,
        )
        if data == 0xFFFF:
            raise Exception("Failed to read secondary bus")
        return data

    async def read_memory_base(self, bdf: int) -> int:
        data = await self.read_config(bdf, REG_ADDR.MEMORY_BASE.START, REG_ADDR.MEMORY_BASE.LEN)
        if data == 0xFFFF:
            raise Exception("Failed to read subordinate bus")
        return data

    async def read_memory_limit(self, bdf: int) -> int:
        data = await self.read_config(bdf, REG_ADDR.MEMORY_LIMIT.START, REG_ADDR.MEMORY_LIMIT.LEN)
        if data == 0xFFFF:
            raise Exception("Failed to read memory limit")
        return data

    async def check_bar_size_and_set(
        self,
        bdf: int,
        memory_base: int,
        mmio_enum_info: Optional[MmioEnumerationInfo] = None,
    ):
        bdf_string = bdf_to_string(bdf)
        logger.info(self._create_message(f"Checking BAR0 size of device {bdf_string}"))

        # NOTE: Write 0xFFFFFFFF to BAR0 to get the size of BAR0
        await self.set_bar0(bdf, 0xFFFFFFFF)
        size = await self.get_bar0_size(bdf)
        logger.info(self._create_message(f"BAR0 size of device {bdf_string} is {size}"))
        if size > 0:
            logger.info(
                self._create_message(
                    f"Setting BAR0 address of device {bdf_string} to 0x{memory_base:08x}"
                )
            )
            await self.set_bar0(bdf, memory_base)
            if mmio_enum_info is not None:
                mmio_enum_info.bar_blocks.append(
                    BarEnumerationInfo(memory_base=memory_base, memory_limit=memory_base + size - 1)
                )
        else:
            await self.set_bar0(bdf, 0)
        return size

    """
    Device Enumeration functions
    """

    async def scan_dvsec_register_locator(
        self, bdf: int, cap_offset: int, length: int, capabilities: PciCapabilities
    ):
        logger.info(self._create_message("Found Register Locator DVSEC"))
        block_offset_base = 0x0C
        blocks = int((length - block_offset_base) / 8)
        block_size = 8
        for block_index in range(blocks):
            block_offset = block_offset_base + block_index * block_size

            register_offset_low = await self.read_config(bdf, cap_offset + block_offset, 4)
            if register_offset_low is None:
                raise Exception(
                    f"Failed to read Register Block {block_index + 1} - Register Offset Low"
                )
            register_offset_high = await self.read_config(bdf, cap_offset + block_offset + 4, 4)
            if register_offset_high is None:
                raise Exception(
                    f"Failed to read Register Block {block_index + 1} - Register Offset High"
                )

            register_bir = register_offset_low & 0x7
            register_block_identifier = (register_offset_low >> 8) & 0xFF
            bar_offset = (register_offset_low & 0xFFFF0000) | register_offset_high << 32

            if register_block_identifier == 0x01:
                component_registers = DvsecRegisterLocator()
                capabilities.dvsec.register_locators.component_registers = component_registers
                component_registers.bar = register_bir
                component_registers.offset = bar_offset
                logger.info(
                    self._create_message(
                        f"(Block {block_index + 1}) "
                        f"Component Registers, BAR: {component_registers.bar}"
                    )
                )
                logger.info(
                    self._create_message(
                        f"(Block {block_index + 1}) "
                        f"Component Registers, OFFSET: {component_registers.offset}"
                    )
                )
            elif register_block_identifier == 0x03:
                cxl_device_registers = DvsecRegisterLocator()
                capabilities.dvsec.register_locators.cxl_device_registers = cxl_device_registers
                cxl_device_registers.bar = register_bir
                cxl_device_registers.offset = bar_offset
                logger.info(
                    self._create_message(
                        f"(Block {block_index + 1}) CXL Device Registers, "
                        f"BAR: {cxl_device_registers.bar}"
                    )
                )
                logger.info(
                    self._create_message(
                        f"(Block {block_index + 1}) CXL Device Registers, "
                        f"OFFSET: {cxl_device_registers.offset}"
                    )
                )

    async def scan_dvsec(self, bdf: int, cap_offset: int, capabilities: PciCapabilities):
        dvsec_header1 = await self.read_config(bdf, cap_offset + 0x04, 4)
        if dvsec_header1 is None:
            raise Exception("Failed to read DVSEC Header 1")
        dvsec_header2 = await self.read_config(bdf, cap_offset + 0x08, 2)
        if dvsec_header2 is None:
            raise Exception("Failed to read DVSEC Header 2")

        vendor_id = dvsec_header1 & 0xFFFF
        revision_id = (dvsec_header1 >> 16) & 0xF
        length = (dvsec_header1 >> 20) & 0xFFF
        dvsec_id = dvsec_header2

        if vendor_id == 0x1E98 and revision_id == 0x0 and dvsec_id == 0x0008:
            await self.scan_dvsec_register_locator(bdf, cap_offset, length, capabilities)

    async def scan_sn(self, bdf: int, cap_offset: int, capabilities: PciCapabilities):
        sn_low = await self.read_config(bdf, cap_offset + 0x04, 4)
        sn_high = await self.read_config(bdf, cap_offset + 0x08, 4)
        sn_int = (sn_high << 32) | sn_low
        sn_str = f"{sn_int:016x}"
        logger.info(self._create_message(f"Found Device SN - {sn_str}"))
        capabilities.serial_number = sn_str

    async def scan_pcie_cap_helper(self, bdf: int, offset: int, capabilities: PciCapabilities):
        data = await self.read_config(bdf, offset, 4)
        if data is None:
            return

        cap_id = data & 0xFFFF
        cap_version = (data >> 16) & 0xF
        next_cap_offset = (data >> 20) & 0xFFF

        is_dvsec_cap = cap_id == 0x0023 and cap_version == 0x1
        if is_dvsec_cap:
            await self.scan_dvsec(bdf, offset, capabilities)

        is_sn_cap = cap_id == 0x0003 and cap_version == 0x1
        if is_sn_cap:
            await self.scan_sn(bdf, offset, capabilities)

        if next_cap_offset != 0:
            await self.scan_pcie_cap_helper(bdf, next_cap_offset, capabilities)

    async def scan_pci_capabilities(self, bdf: int, capabilities: PciCapabilities):
        PCIE_CONFIG_BASE = 0x100
        await self.scan_pcie_cap_helper(bdf, PCIE_CONFIG_BASE, capabilities)

    async def scan_component_registers(self, info: DeviceEnumerationInfo):
        # pylint: disable=duplicate-code
        component_registers = info.capabilities.dvsec.register_locators.component_registers
        if not component_registers:
            return

        component_register_bar = component_registers.bar
        component_register_offset = component_registers.offset
        mmio_base = info.bars[component_register_bar]
        cxl_cachemem_offset = mmio_base + component_register_offset + 0x1000

        logger.info(
            self._create_message(f"Scanning Component Registers at 0x{cxl_cachemem_offset:x}")
        )

        cxl_capability_header = await self.read_mmio(cxl_cachemem_offset, 4)
        cxl_capability_id = cxl_capability_header & 0xFFFF
        cxl_capability_version = (cxl_capability_header >> 16) & 0xF
        cxl_cachemem_version = (cxl_capability_header >> 20) & 0xF
        array_size = (cxl_capability_header >> 24) & 0xFF

        logger.debug(self._create_message(f"cxl_capability_id: {cxl_capability_id:x}"))
        logger.debug(self._create_message(f"cxl_capability_version: {cxl_capability_version:x}"))
        logger.debug(self._create_message(f"cxl_cachemem_version: {cxl_cachemem_version:x}"))
        logger.debug(self._create_message(f"array_size: {array_size:x}"))

        if cxl_capability_id != 0x0001:
            return

        logger.info(self._create_message("Found Component Registers"))

        for header_index in range(array_size):
            header_offset = header_index * 4 + 4 + cxl_cachemem_offset
            header_info = await self.read_mmio(header_offset, 4)
            cxl_capability_id = header_info & 0xFFFF
            cxl_capability_version = (header_info >> 16) & 0xF
            offset = (header_info >> 20) & 0xFFF
            logger.info(
                self._create_message(
                    f"Found {CxlCapabilityIDToName.get(cxl_capability_id)} Capability Header"
                )
            )
            info.component_registers[CxlCapabilityIDToName.get_original_name(cxl_capability_id)] = (
                cxl_cachemem_offset + offset
            )

    async def scan_bus(
        self, bus: int, parent: Optional[DeviceEnumerationInfo] = None
    ) -> List[DeviceEnumerationInfo]:
        bdf_list = generate_bdfs_for_bus(bus)
        devices: List[DeviceEnumerationInfo] = []
        multi_function_devices = set()
        for bdf in bdf_list:
            device_number = extract_device_from_bdf(bdf)
            function_number = extract_function_from_bdf(bdf)

            if function_number != 0 and device_number not in multi_function_devices:
                continue

            vid_did = await self.read_vid_did(bdf)
            if vid_did is None:
                continue

            is_multifunction = (await self.read_config(bdf, 0x0E, 1) & 0x80) >> 7
            if is_multifunction:
                multi_function_devices.add(device_number)

            bar0 = await self.read_bar(bdf, 0)

            class_code = await self.read_class_code(bdf)
            if (class_code >> 8) == BRIDGE_CLASS:
                secondary_bus = await self.read_secondary_bus(bdf)
                subordinate_bus = await self.read_subordinate_bus(bdf)
                memory_base = memory_base_regval_to_addr(await self.read_memory_base(bdf))
                memory_limit = memory_limit_regval_to_addr(await self.read_memory_limit(bdf))

                logger.info(
                    self._create_message(
                        f"Found an bridge device at {bdf_to_string(bdf)} (VID/DID: 0x{vid_did:08x})"
                    )
                )
                logger.info(self._create_message(f"secondary bus: {secondary_bus}"))
                logger.info(self._create_message(f"subordinate bus: {subordinate_bus}"))
                logger.info(self._create_message(f"memory base: {memory_base:08x}"))
                logger.info(self._create_message(f"memory limit: {memory_limit:08x}"))

                info = DeviceEnumerationInfo(
                    bdf,
                    vid_did=vid_did,
                    class_code=class_code,
                    bars=[bar0],
                    is_bridge=True,
                    mmio_range=MemoryEnumerationInfo(
                        memory_base=memory_base, memory_limit=memory_limit
                    ),
                )

                await self.scan_pci_capabilities(bdf, info.capabilities)
                await self.scan_component_registers(info)
                children_devices = await self.scan_bus(secondary_bus, info)
                info.children = children_devices
                info.parent = parent
                devices.append(info)
            else:
                logger.info(
                    self._create_message(
                        f"Found an endpoint device at {bdf_to_string(bdf)} "
                        f"(VID/DID: 0x{vid_did:08x})"
                    )
                )

                if bar0 == 0 and parent:
                    logger.info(
                        self._create_message(
                            "BAR0 is not set, however MMIO memory range is reserved by the parent"
                        )
                    )
                    memory_base = parent.mmio_range.memory_base
                    size = await self.check_bar_size_and_set(bdf, memory_base)
                    if size > 0:
                        bar0 = memory_base

                info = DeviceEnumerationInfo(
                    bdf,
                    vid_did=vid_did,
                    class_code=class_code,
                    bars=[bar0],
                    is_bridge=False,
                )
                info.parent = parent

                await self.scan_pci_capabilities(bdf, info.capabilities)
                await self.scan_component_registers(info)
                devices.append(info)

        return devices

    async def scan_devices(self) -> EnumerationInfo:
        enumeration_info = EnumerationInfo()
        logger.info(self._create_message(f"Scanning devices under bus {self._secondary_bus}"))
        devices = await self.scan_bus(self._secondary_bus)
        enumeration_info.devices = devices
        return enumeration_info

    async def enumerate(self, memory_base_address: int) -> MmioEnumerationInfo:
        logger.info(
            self._create_message(f"Starting PCI device enumeration at bus {self._secondary_bus}")
        )
        mmio_enum_info = MmioEnumerationInfo()
        bdf = create_bdf(self._secondary_bus, 0, 0)
        bdf_str = bdf_to_string(bdf)
        vid_did = await self.read_vid_did(bdf)
        if vid_did is None:
            logger.warning(self._create_message(f"Device not found at {bdf_str}"))
            return mmio_enum_info

        class_code = await self.read_class_code(bdf)
        if (class_code >> 8) == BRIDGE_CLASS:
            logger.info(self._create_message(f"A switch upstream port device found at {bdf_str}"))
            return await self.enumerate_switch(memory_base_address)

        logger.info(self._create_message(f"An Endpoint device found at {bdf_str}"))
        await self.enumerate_ep(bdf, memory_base_address, mmio_enum_info)
        return mmio_enum_info

    async def enumerate_ep(
        self, bdf: int, memory_base_address: int, mmio_enum_info: MmioEnumerationInfo
    ):
        size = await self.check_bar_size_and_set(bdf, memory_base_address, mmio_enum_info)
        if size == 0:
            return
        mmio_enum_info.memory_base = memory_base_address
        mmio_enum_info.memory_limit = mmio_enum_info.memory_base + size - 1

    async def enumerate_switch(
        self,
        memory_base_address: int,
    ) -> MmioEnumerationInfo:
        usp_bdf = create_bdf(self._secondary_bus, 0, 0)
        usp_bdf_str = bdf_to_string(usp_bdf)
        next_bus = self._secondary_bus + 1
        mmio_enum_info = MmioEnumerationInfo()

        memory_start = memory_base_address
        memory_end = memory_base_address
        memory_range = 0x100000

        # --------------------------------------------------
        # NOTE: Setting up USP
        # --------------------------------------------------
        logger.info(self._create_message(f"Setting up USP at {usp_bdf_str}"))

        size = await self.check_bar_size_and_set(usp_bdf, memory_start, mmio_enum_info)

        if size > 0:
            memory_end += 0x100000
            memory_start = memory_end

        await self.set_secondary_bus(usp_bdf, next_bus)
        await self.set_subordinate_bus(usp_bdf, next_bus)

        for dsp_bdf in generate_bdfs_for_bus(next_bus):
            # --------------------------------------------------
            # NOTE: Check if DSP exists and set up DSP if exists
            # --------------------------------------------------

            # TODO: Instead of enuemrating all devices and functions under a bus,
            # read device at function 0 and check if multifunctions are supported.

            dsp_bdf_str = bdf_to_string(dsp_bdf)
            dsp_memory_start = memory_end

            vid_did = await self.read_vid_did(dsp_bdf)
            if vid_did is None:
                continue

            logger.info(self._create_message(f"Setting up DSP at ({dsp_bdf_str})"))
            next_bus = next_bus + 1

            size = await self.check_bar_size_and_set(dsp_bdf, dsp_memory_start, mmio_enum_info)

            if size > 0:
                memory_end += memory_range
                dsp_memory_start += memory_range

            await self.set_secondary_bus(dsp_bdf, next_bus)
            await self.set_subordinate_bus(dsp_bdf, next_bus)
            await self.set_subordinate_bus(usp_bdf, next_bus)

            if memory_start != memory_end:
                await self.set_memory_base(usp_bdf, memory_start)
                await self.set_memory_limit(usp_bdf, memory_end - 1)

            # ------------------------------------
            # NOTE: Setting up EP attached to DSP
            #       Assume EP exists under the DSP
            # ------------------------------------

            dsp_device_bdf = create_bdf(next_bus, 0, 0)
            dsp_device_bdf_str = bdf_to_string(dsp_device_bdf)

            logger.info(
                self._create_message(
                    f"Setting up EP at {dsp_device_bdf_str} (Attached to DSP {dsp_bdf_str})"
                )
            )

            size = await self.check_bar_size_and_set(
                dsp_device_bdf, dsp_memory_start, mmio_enum_info
            )

            # NOTE: Assume size is less then 0x100000
            if size > 0:
                memory_end += memory_range

            if dsp_memory_start != memory_end:
                await self.set_memory_base(dsp_bdf, dsp_memory_start)
                await self.set_memory_limit(dsp_bdf, memory_end - 1)
                await self.set_memory_limit(usp_bdf, memory_end - 1)

        logger.info(self._create_message("Completed PCI device enumeration"))

        mmio_enum_info.memory_base = memory_base_address
        mmio_enum_info.memory_limit = memory_end
        return mmio_enum_info

    async def enable_hdm_decoder(self, device_enum_info: DeviceEnumerationInfo):
        if device_enum_info.component_registers.hdm_decoder != 0:
            logger.info(
                self._create_message(
                    f"Enabled HDM Decoder at {bdf_to_string(device_enum_info.bdf)}"
                )
            )
            register_offset = device_enum_info.component_registers.hdm_decoder
            global_controller_register_offset = register_offset + 0x04
            global_controller_register_value = 0b10
            await self.write_mmio(
                global_controller_register_offset,
                global_controller_register_value,
                verbose=False,
            )

        for child in device_enum_info.children:
            await self.enable_hdm_decoder(child)

    async def configure_hdm_decoder_common(
        self,
        info: DeviceEnumerationInfo,
        decoder_index: int,
        hpa_base: int,
        hpa_size: int,
        interleaving_granularity: int = 0,
        interleaving_way: int = 0,
    ):
        if info.component_registers.hdm_decoder == 0:
            return 0

        register_offset = info.component_registers.hdm_decoder

        decoder_base_low_offset = 0x20 * decoder_index + 0x10 + register_offset
        decoder_base_high_offset = 0x20 * decoder_index + 0x14 + register_offset
        decoder_size_low_offset = 0x20 * decoder_index + 0x18 + register_offset
        decoder_size_high_offset = 0x20 * decoder_index + 0x1C + register_offset
        decoder_control_register_offset = 0x20 * decoder_index + 0x20 + register_offset

        commit = 1

        decoder_base_low = hpa_base & 0xFFFFFFFF
        decoder_base_high = (hpa_base >> 32) & 0xFFFFFFFF
        decoder_size_low = hpa_size & 0xFFFFFFFF
        decoder_size_high = (hpa_size >> 32) & 0xFFFFFFFF

        decoder_control = (
            interleaving_granularity & 0xF | (interleaving_way & 0xF) << 4 | commit << 9
        )

        logger.info(self._create_message(f"HDM Decoder {decoder_index}, HPA Base: 0x{hpa_base:x}"))
        logger.info(self._create_message(f"HDM Decoder {decoder_index}, HPA Size: 0x{hpa_size:x}"))

        await self.write_mmio(decoder_base_low_offset, decoder_base_low, verbose=False)
        await self.write_mmio(decoder_base_high_offset, decoder_base_high, verbose=False)
        await self.write_mmio(decoder_size_low_offset, decoder_size_low, verbose=False)
        await self.write_mmio(decoder_size_high_offset, decoder_size_high, verbose=False)
        await self.write_mmio(decoder_control_register_offset, decoder_control, verbose=False)

    async def configure_hdm_decoder_switch(
        self,
        info: DeviceEnumerationInfo,
        decoder_index: int,
        hpa_base: int,
        hpa_size: int,
        target_list: List[int],
        interleaving_granularity: int = 0,
        interleaving_way: int = 0,
    ):
        if info.component_registers.hdm_decoder == 0:
            return 0

        register_offset = info.component_registers.hdm_decoder
        logger.debug(self._create_message(f"HDM Decoder Capability Offset: 0x{register_offset:x}"))
        logger.info(
            self._create_message(
                f"Setting HDM Decoder {decoder_index} (Switch) of {bdf_to_string(info.bdf)}"
            )
        )
        target_list_low_offset = 0x20 * decoder_index + 0x24 + register_offset
        target_list_high_offset = 0x20 * decoder_index + 0x28 + register_offset
        target_list_low = 0
        target_list_high = 0

        for i, _ in enumerate(target_list):
            if i < 4:
                target_list_low |= (target_list[i] & 0xFF) << (i * 8)
            elif i < 8:
                target_list_high |= (target_list[i] & 0xFF) << ((i - 4) * 8)

        await self.write_mmio(target_list_low_offset, target_list_low, verbose=False)
        await self.write_mmio(target_list_high_offset, target_list_high, verbose=False)
        await self.configure_hdm_decoder_common(
            info,
            decoder_index,
            hpa_base,
            hpa_size,
            interleaving_granularity,
            interleaving_way,
        )

    async def configure_hdm_decoder_device(
        self,
        info: DeviceEnumerationInfo,
        decoder_index: int,
        hpa_base: int,
        hpa_size: int,
        dpa_skip: int = 0,
        interleaving_granularity: int = 0,
        interleaving_way: int = 0,
    ):
        if info.component_registers.hdm_decoder == 0:
            return 0

        register_offset = info.component_registers.hdm_decoder
        logger.debug(self._create_message(f"HDM Decoder Capability Offset: 0x{register_offset:x}"))
        logger.info(
            self._create_message(
                f"Setting HDM Decoder {decoder_index} (Device) of {bdf_to_string(info.bdf)}"
            )
        )

        dpa_skip_low_offset = 0x20 * decoder_index + 0x24 + register_offset
        dpa_skip_high_offset = 0x20 * decoder_index + 0x28 + register_offset
        dpa_skip_low = dpa_skip & 0xFFFFFFFF
        dpa_skip_high = (dpa_skip >> 32) & 0xFFFFFFFF
        await self.write_mmio(dpa_skip_low_offset, dpa_skip_low, verbose=False)
        await self.write_mmio(dpa_skip_high_offset, dpa_skip_high, verbose=False)

        await self.configure_hdm_decoder_common(
            info,
            decoder_index,
            hpa_base,
            hpa_size,
            interleaving_granularity,
            interleaving_way,
        )

    async def get_hdm_decoder_count(self, info: DeviceEnumerationInfo) -> int:
        if info.component_registers.hdm_decoder == 0:
            logger.warning("HDM Decoder offset not found")
            return 0

        decoder_counter_map = [1, 2, 4, 6, 8, 10, 12, 14, 16, 20, 24, 28, 32]
        register_offset = info.component_registers.hdm_decoder
        hdm_decoder_cap = await self.read_mmio(register_offset, verbose=False)
        decoder_count_index = hdm_decoder_cap & 0xF
        if decoder_count_index >= len(decoder_counter_map):
            raise Exception(f"HDM Decoder counter index, {decoder_count_index}, is not supported")
        return decoder_counter_map[decoder_count_index]

    async def get_next_available_decoder_index(self, info: DeviceEnumerationInfo) -> Optional[int]:
        decoder_count = await self.get_hdm_decoder_count(info)
        if decoder_count == 0:
            return None

        register_offset = info.component_registers.hdm_decoder
        next_available_decoder = None
        for decoder_index in range(decoder_count):
            decoder_control_register_offset = 0x20 + decoder_index * 0x20 + register_offset
            decoder_control_register_value = await self.read_mmio(
                decoder_control_register_offset, verbose=False
            )
            if decoder_control_register_value & 0x400 == 0:
                next_available_decoder = decoder_index
                break
        return next_available_decoder

    async def configure_hdm_decoder_single_device(
        self, usp: DeviceEnumerationInfo, cxl_hpa_base: int
    ):
        self._used_hpa_size = 0
        cxl_devices = usp.get_all_cxl_devices()
        logger.info(self._create_message(f"Found {len(cxl_devices)} CXL devices"))
        for cxl_device in cxl_devices:
            logger.info(self._create_message(f"CXL device at {bdf_to_string(cxl_device.bdf)}"))
            decoder_count = await self.get_hdm_decoder_count(cxl_device)
            logger.info(self._create_message(f"Number of HDM decoders: {decoder_count}"))
            decoder_index = await self.get_next_available_decoder_index(cxl_device)
            if decoder_index is None:
                continue

            hpa_base = cxl_hpa_base + self._used_hpa_size
            hpa_size = cxl_device.cxl_device_size

            await self.configure_hdm_decoder_device(cxl_device, decoder_index, hpa_base, hpa_size)

            if cxl_device.parent is None:
                continue
            port_number = cxl_device.get_port_number()
            logger.info(self._create_message(f"Port Number: {port_number}"))

            decoder_index = await self.get_next_available_decoder_index(usp)
            if decoder_index is None:
                continue

            await self.configure_hdm_decoder_switch(
                usp, decoder_index, hpa_base, hpa_size, target_list=[port_number]
            )
            self._used_hpa_size += hpa_size

    async def init(self, hpa_base: int):
        if self._test_mode:
            return
        logger.debug(self._create_message("Starting CXL initialization"))
        memory_base_address = 0xFE000000
        self._cxl_hpa_base = hpa_base
        await self.enumerate(memory_base_address)
        enum_info = await self.scan_devices()
        usp = enum_info.devices[0]
        await self.enable_hdm_decoder(usp)
        await self.configure_hdm_decoder_single_device(usp, hpa_base)
        logger.debug(self._create_message("Completed CXL initialization"))

    def get_hpa_base(self) -> int:
        return self._cxl_hpa_base

    def get_used_hpa_size(self) -> int:
        return self._used_hpa_size

    async def _run(self):
        self._run_fut = asyncio.Future()
        await self.init(self._cxl_hpa_base)
        await self._change_status_to_running()
        logger.info(self._create_message("Waiting for a new action"))
        await self._run_fut

    async def _stop(self):
        self._run_fut.set_result(0)
