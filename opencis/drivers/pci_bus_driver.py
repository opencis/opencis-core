"""
 Copyright (c) 2024, Eeum, Inc.

 This software is licensed under the terms of the Revised BSD License.
 See LICENSE for details.
"""

from enum import IntEnum
from typing import Optional, Tuple, List, cast
from dataclasses import dataclass, field
from opencis.util.logger import logger
from opencis.util.component import LabeledComponent
from opencis.pci.component.pci import (
    PCI_CLASS,
    PCI_BRIDGE_SUBCLASS,
    PCI_DEVICE_PORT_TYPE,
    memory_base_addr_to_regval,
    memory_limit_addr_to_regval,
)
from opencis.pci.config_space.pci import REG_ADDR, BAR_OFFSETS, BAR_REGISTER_SIZE
from opencis.util.pci import (
    extract_device_from_bdf,
    extract_function_from_bdf,
    bdf_to_string,
    generate_bdfs_for_bus,
)
from opencis.cxl.component.root_complex.root_complex import RootComplex

BRIDGE_CLASS = PCI_CLASS.BRIDGE << 8 | PCI_BRIDGE_SUBCLASS.PCI_BRIDGE
NUM_BARS_BRIDGE = 2
NUM_BARS_ENDPOINT = 6
PCIE_CONFIG_BASE = 0x100
PCI_CAPABILITY_POINTER = 0x34
PCI_CONFIG_HEADER_SIZE = 2
PCIE_CONFIG_HEADER_SIZE = 4
PCIE_CONFIG_HEADER_ID_MASK = 0xFFFF
PCIE_CONFIG_HEADER_ID_START = 0
PCIE_CONFIG_VERSION_MASK = 0xF
PCIE_CONFIG_VERSION_START = 16
PCIE_NEXT_CAP_OFFSET_MASK = 0xFFF
PCIE_NEXT_CAP_OFFSET_START = 20


class PCI_CAPABILITY_ID(IntEnum):
    POWER_MANAGEMENT = 0x01
    PCI_EXPRESS = 0x10
    MSI = 0x05
    MSIX = 0x11


class PCI_EXTENDED_CAPABILITY_ID(IntEnum):
    DEVICE_SERIAL_NUMBER = 0x0003
    DESIGNATED_VENDOR_SPECIFIC = 0x0023
    DATA_OBJECT_EXCHANGE = 0x002E


@dataclass
class PciBarInfo:
    memory_type: int = 0
    prefetchable: bool = False
    base_address: int = 0
    size: int = 0


@dataclass
class PciCapabilityInfo:
    is_extended: bool = False
    id: int = 0
    version: int = 0
    offset: int = 0


@dataclass
class PciExpressCapabilityInfo(PciCapabilityInfo):
    device_port_type: PCI_DEVICE_PORT_TYPE = PCI_DEVICE_PORT_TYPE.PCI_EXPRESS_ENDPOINT
    port_number: int = 0


@dataclass
class PciDeviceInfo:
    bdf: int = 0
    vendor_id: int = 0
    device_id: int = 0
    class_code: int = 0
    serial_number: str = "0000000000000000"
    bars: List[PciBarInfo] = field(default_factory=list)
    is_bridge: bool = False
    parent: Optional["PciDeviceInfo"] = None
    children: List["PciDeviceInfo"] = field(default_factory=list)
    capabilities: List[PciCapabilityInfo] = field(default_factory=list)

    def get_capabilities_by_id(self, id: int, is_extended: bool) -> List[PciCapabilityInfo]:
        capabilities = []
        for capability in self.capabilities:
            if capability.is_extended == is_extended and capability.id == id:
                capabilities.append(capability)
        return capabilities

    def get_device_port_type(self) -> Optional[PCI_DEVICE_PORT_TYPE]:
        capabilities = self.get_capabilities_by_id(PCI_CAPABILITY_ID.PCI_EXPRESS, False)
        if len(capabilities) == 0:
            return None
        pci_express_capability = cast(PciExpressCapabilityInfo, capabilities[0])
        return pci_express_capability.device_port_type

    def get_bdf_string(self) -> str:
        return bdf_to_string(self.bdf)

    def get_port_number(self) -> int:
        capabilities = self.get_capabilities_by_id(PCI_CAPABILITY_ID.PCI_EXPRESS, False)
        if len(capabilities) == 0:
            return 0
        pci_express_capability = cast(PciExpressCapabilityInfo, capabilities[0])
        return pci_express_capability.port_number

    def print(self, prefix: str = ""):
        logger.debug(f"{prefix}BDF              : {bdf_to_string(self.bdf)}")
        logger.debug(f"{prefix}Vendor ID        : 0x{self.vendor_id:04X}")
        logger.debug(f"{prefix}Device ID        : 0x{self.device_id:04X}")
        logger.debug(f"{prefix}Class Code       : 0x{self.class_code:06X}")
        logger.debug(f"{prefix}Is Bridge        : {'Yes' if self.is_bridge else 'No'}")

        if self.parent:
            logger.debug(f"{prefix}Parent BDF       : {bdf_to_string(self.parent.bdf)}")

        if len(self.children) > 0:
            children_bdf_list = [bdf_to_string(child.bdf) for child in self.children]
            logger.debug(f"{prefix}Children BDFs    : {', '.join(children_bdf_list)}")

        for bar_index, bar_info in enumerate(self.bars):
            logger.debug(f"{prefix}BAR{bar_index} Base Address: 0x{bar_info.base_address:X}")
            logger.debug(f"{prefix}BAR{bar_index} Size        : {bar_info.size}")

        if len(self.capabilities) > 0:
            logger.debug(f"{prefix}Capabilities        :")
            for capability in self.capabilities:
                if capability.is_extended:
                    supported_cap_id_list = [member.value for member in PCI_EXTENDED_CAPABILITY_ID]
                    if capability.id in supported_cap_id_list:
                        cap_name = PCI_EXTENDED_CAPABILITY_ID(capability.id).name
                        logger.debug(
                            f"{prefix} - {cap_name} Extended Capability: 0x{capability.offset:X}"
                        )
                    else:
                        logger.debug(
                            f"{prefix} - Extended Capability ID 0x{capability.id:03X}: "
                            f"0x{capability.offset:X}"
                        )
                else:
                    supported_cap_id_list = [member.value for member in PCI_CAPABILITY_ID]
                    if capability.id in supported_cap_id_list:
                        cap_name = PCI_CAPABILITY_ID(capability.id).name
                        logger.debug(f"{prefix} - {cap_name} Capability: 0x{capability.offset:X}")
                    else:
                        logger.debug(
                            f"{prefix} - Capability ID 0x{capability.id:02X}: "
                            f"0x{capability.offset:X}"
                        )
                    if capability.id == PCI_CAPABILITY_ID.PCI_EXPRESS:
                        pxcap = cast(PciExpressCapabilityInfo, capability)
                        logger.debug(f"{prefix}    - Port Number: {pxcap.port_number}")
                        logger.debug(
                            f"{prefix}    - Device/Port Type: {pxcap.device_port_type.name}"
                        )


class PciBusDriver(LabeledComponent):
    def __init__(self, root_complex: RootComplex, label: Optional[str] = None):
        super().__init__(label)
        self._root_complex = root_complex
        self._devices: List[PciDeviceInfo] = []
        self._existing_bdfs: list[int] = []
        self._current_enum_bdfs: list[int] = []

    async def init(self, mmio_base_address: int):
        self._current_enum_bdfs = []
        (_, memory_end) = await self._scan_pci_devices(mmio_base_address)
        await self._init_pci_devices()
        self.display_devices()
        return memory_end

    def get_devices(self):
        return self._devices

    def display_devices(self):
        logger.debug(self._create_message("Enumerated PCI Devices"))
        logger.debug(self._create_message("=============================="))
        for device in self._devices:
            device.print("[PciBusDriver] ")
            logger.debug(self._create_message("------------------------------"))

    async def _scan_pci_devices(self, mmio_base_address: int):
        root_bus = self._root_complex.get_root_bus()
        return await self._scan_bus(root_bus, mmio_base_address)

    async def _init_pci_devices(self):
        pass

    # pylint: disable=duplicate-code

    async def read_config(self, bdf: int, offset: int, size: int) -> int:
        return await self._root_complex.read_config(bdf, offset, size)

    async def write_config(self, bdf: int, offset: int, size: int, value: int):
        await self._root_complex.write_config(bdf, offset, size, value)

    async def read_mmio(self, address, size) -> int:
        return await self._root_complex.read_mmio(address, size)

    async def write_mmio(self, address, size, value):
        await self._root_complex.write_mmio(address, size, value)

    async def _set_secondary_bus(self, bdf: int, secondary_bus: int):
        bdf_string = bdf_to_string(bdf)
        logger.debug(
            self._create_message(f"Setting secondary bus of device {bdf_string} to {secondary_bus}")
        )

        await self.write_config(
            bdf,
            REG_ADDR.SECONDARY_BUS_NUMBER.START,
            REG_ADDR.SECONDARY_BUS_NUMBER.LEN,
            secondary_bus,
        )

    async def _set_subordinate_bus(self, bdf: int, subordinate_bus: int):
        bdf_string = bdf_to_string(bdf)
        logger.debug(
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

    async def _set_memory_base(self, bdf: int, address_base: int):
        bdf_string = bdf_to_string(bdf)
        logger.debug(
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

    async def _set_memory_limit(self, bdf: int, address_limit: int):
        logger.debug(
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

    async def _set_prefetchable_memory_base(self, bdf: int, address_base: int):
        bdf_string = bdf_to_string(bdf)
        logger.debug(
            self._create_message(
                f"Setting prefetchable memory base of device {bdf_string} to {address_base:08x}"
            )
        )

        address_lower = address_base & 0xFFFFFFFF
        address_upper = (address_base >> 32) & 0xFFFFFFFF
        address_base_regval = memory_base_addr_to_regval(address_lower)

        await self.write_config(
            bdf,
            REG_ADDR.PREFETCHABLE_MEMORY_BASE.START,
            REG_ADDR.PREFETCHABLE_MEMORY_BASE.LEN,
            address_base_regval,
        )
        await self.write_config(
            bdf,
            REG_ADDR.PREFETCHABLE_MEMORY_BASE_UPPER.START,
            REG_ADDR.PREFETCHABLE_MEMORY_BASE_UPPER.LEN,
            address_upper,
        )

    async def _set_prefetchable_memory_limit(self, bdf: int, address_limit: int):
        logger.debug(
            self._create_message(
                f"Setting prefetchable memory limit of device {bdf_to_string(bdf)}"
                f" to {address_limit:08x}"
            )
        )

        address_lower = address_limit & 0xFFFFFFFF
        address_upper = (address_limit >> 32) & 0xFFFFFFFF
        address_limit_regval = memory_limit_addr_to_regval(address_lower)
        await self.write_config(
            bdf,
            REG_ADDR.PREFETCHABLE_MEMORY_LIMIT.START,
            REG_ADDR.PREFETCHABLE_MEMORY_LIMIT.LEN,
            address_limit_regval,
        )
        await self.write_config(
            bdf,
            REG_ADDR.PREFETCHABLE_MEMORY_LIMIT_UPPER.START,
            REG_ADDR.PREFETCHABLE_MEMORY_LIMIT_UPPER.LEN,
            address_upper,
        )

    async def _set_bar0(self, bdf: int, bar_address: int):
        await self.write_config(bdf, BAR_OFFSETS.BAR0, BAR_REGISTER_SIZE, bar_address)

    async def _get_bar0_size(
        self,
        bdf: int,
    ) -> int:
        data = await self.read_config(bdf, BAR_OFFSETS.BAR0, BAR_REGISTER_SIZE)
        if data == 0:
            return data
        return 0xFFFFFFFF - data + 1

    async def _read_vid_did(self, bdf: int) -> Optional[int]:
        logger.debug(self._create_message(f"Reading VID/DID from {bdf_to_string(bdf)}"))
        vid = await self.read_config(bdf, REG_ADDR.VENDOR_ID.START, REG_ADDR.VENDOR_ID.LEN)
        did = await self.read_config(bdf, REG_ADDR.DEVICE_ID.START, REG_ADDR.DEVICE_ID.LEN)
        logger.debug(self._create_message(f"VID: 0x{vid:x}"))
        logger.debug(self._create_message(f"DID: 0x{did:x}"))
        if did == 0xFFFF and vid == 0xFFFF:
            logger.debug(self._create_message(f"Device not found at {bdf_to_string(bdf)}"))
            return None
        return (did << 16) | vid

    async def _read_class_code(self, bdf: int) -> int:
        data = await self.read_config(bdf, REG_ADDR.CLASS_CODE.START, REG_ADDR.CLASS_CODE.LEN)
        if data == 0xFFFF:
            raise Exception("Failed to read class code")
        return data

    async def _read_bar(self, bdf, bar_id) -> int:
        offset = 0x10 + bar_id * 4
        size = 4
        data = await self.read_config(bdf, offset, size=size)
        if data == 0xFFFF:
            raise Exception(f"Failed to read bar {bar_id}")
        return data

    async def _read_secondary_bus(self, bdf: int) -> int:
        data = await self.read_config(
            bdf,
            REG_ADDR.SECONDARY_BUS_NUMBER.START,
            REG_ADDR.SECONDARY_BUS_NUMBER.LEN,
        )
        if data == 0xFFFF:
            raise Exception("Failed to read secondary bus")
        return data

    async def _read_subordinate_bus(self, bdf: int) -> int:
        data = await self.read_config(
            bdf,
            REG_ADDR.SUBORDINATE_BUS_NUMBER.START,
            REG_ADDR.SUBORDINATE_BUS_NUMBER.LEN,
        )
        if data == 0xFFFF:
            raise Exception("Failed to read subordinate bus")
        return data

    async def _read_memory_base(self, bdf: int) -> int:
        data = await self.read_config(bdf, REG_ADDR.MEMORY_BASE.START, REG_ADDR.MEMORY_BASE.LEN)
        if data == 0xFFFF:
            raise Exception("Failed to read memory base")
        return data

    async def _read_memory_limit(self, bdf: int) -> int:
        data = await self.read_config(bdf, REG_ADDR.MEMORY_LIMIT.START, REG_ADDR.MEMORY_LIMIT.LEN)
        if data == 0xFFFF:
            raise Exception("Failed to read memory limit")
        return data

    async def _check_bar_size_and_set(self, bdf: int, memory_base: int, device_info: PciDeviceInfo):
        bdf_string = bdf_to_string(bdf)
        logger.debug(self._create_message(f"Checking BAR0 size of device {bdf_string}"))

        # NOTE: Write 0xFFFFFFFF to BAR0 to get the size of BAR0
        await self._set_bar0(bdf, 0xFFFFFFFF)
        size = await self._get_bar0_size(bdf)
        logger.debug(self._create_message(f"BAR0 size of device {bdf_string} is {size}"))
        if size > 0:
            logger.debug(
                self._create_message(
                    f"Setting BAR0 address of device {bdf_string} to 0x{memory_base:08x}"
                )
            )
            await self._set_bar0(bdf, memory_base)
        else:
            await self._set_bar0(bdf, 0)

        device_info.bars[0].base_address = memory_base
        device_info.bars[0].size = size
        return size

    async def scan_pcie_cap_helper(self, bdf: int, offset: int, device_info: PciDeviceInfo):
        data = await self.read_config(bdf, offset, PCIE_CONFIG_HEADER_SIZE)
        if data is None:
            return

        cap_id = (data >> PCIE_CONFIG_HEADER_ID_START) & PCIE_CONFIG_HEADER_ID_MASK
        cap_version = (data >> PCIE_CONFIG_VERSION_START) & PCIE_CONFIG_VERSION_MASK
        next_cap_offset = (data >> PCIE_NEXT_CAP_OFFSET_START) & PCIE_NEXT_CAP_OFFSET_MASK

        if cap_id == 0:
            return

        support_cap_id_list = [member.value for member in PCI_EXTENDED_CAPABILITY_ID]
        if cap_id in support_cap_id_list:
            cap_name = PCI_EXTENDED_CAPABILITY_ID(cap_id).name
            logger.debug(
                self._create_message(
                    f"Found {cap_name} Extended Capbility at 0x{offset:02X} - ID: 0x{cap_id:02X}"
                )
            )
        else:
            logger.debug(
                self._create_message(
                    f"Found PCI Extended Capbility at 0x{offset:02X} - ID: 0x{cap_id:02X}"
                )
            )

        device_info.capabilities.append(
            PciCapabilityInfo(is_extended=True, id=cap_id, version=cap_version, offset=offset)
        )

        if next_cap_offset != 0:
            await self.scan_pcie_cap_helper(bdf, next_cap_offset, device_info)

    async def scan_pci_cap_pci_express(self, bdf: int, capability_info: PciExpressCapabilityInfo):
        offset = capability_info.offset

        pci_express_register_offset = offset + 0x02
        pci_express_register = await self.read_config(bdf, pci_express_register_offset, 2)
        capability_info.device_port_type = PCI_DEVICE_PORT_TYPE((pci_express_register >> 4) & 0xF)
        link_capability_register_offset = offset + 0x0C
        link_capability_register = await self.read_config(bdf, link_capability_register_offset, 4)
        capability_info.port_number = (link_capability_register >> 24) & 0xFF

    async def scan_pci_cap_helper(self, bdf: int, offset: int, device_info: PciDeviceInfo):
        data = await self.read_config(bdf, offset, PCI_CONFIG_HEADER_SIZE)
        if data is None:
            return

        cap_id = data & 0xFF
        next_cap_offset = (data >> 8) & 0xFF

        if cap_id == 0:
            return

        support_cap_id_list = [member.value for member in PCI_CAPABILITY_ID]
        if cap_id in support_cap_id_list:
            logger.debug(
                self._create_message(
                    f"Found {PCI_CAPABILITY_ID(cap_id).name} Capbility at 0x{offset:02X}"
                    f" - ID: 0x{cap_id:02X}"
                )
            )
        else:
            logger.debug(
                self._create_message(f"Found PCI Capbility at 0x{offset:02X} - ID: 0x{cap_id:02X}")
            )

        if cap_id == PCI_CAPABILITY_ID.PCI_EXPRESS:
            capability_info = PciExpressCapabilityInfo(
                is_extended=False, id=cap_id, version=0, offset=offset
            )
            device_info.capabilities.append(capability_info)
            await self.scan_pci_cap_pci_express(bdf, capability_info)
        else:
            device_info.capabilities.append(
                PciCapabilityInfo(is_extended=False, id=cap_id, version=0, offset=offset)
            )

        if next_cap_offset != 0:
            await self.scan_pci_cap_helper(bdf, next_cap_offset, device_info)

    async def _scan_pci_capabilities(self, bdf: int, device_info: PciDeviceInfo):
        pci_cap_pointer = await self.read_config(bdf, PCI_CAPABILITY_POINTER, 2)
        await self.scan_pci_cap_helper(bdf, pci_cap_pointer, device_info)
        await self.scan_pcie_cap_helper(bdf, PCIE_CONFIG_BASE, device_info)

    async def _scan_sn(self, pci_device_info: PciDeviceInfo):
        for capability in pci_device_info.capabilities:
            is_sn = (
                capability.id == PCI_EXTENDED_CAPABILITY_ID.DEVICE_SERIAL_NUMBER
                and capability.version == 0x1
            )
            if not is_sn:
                continue

            bdf = pci_device_info.bdf
            offset = capability.offset

            sn_low = await self._root_complex.read_config(bdf, offset + 0x04, 4)
            sn_high = await self._root_complex.read_config(bdf, offset + 0x08, 4)

            sn_int = (sn_high << 32) | sn_low
            sn_str = f"{sn_int:016x}"
            pci_device_info.serial_number = sn_str

    async def scan_bus_unbind(self):
        remaining_devices = []
        for device in self._devices:
            bdf = device.bdf
            vid_did = await self._read_vid_did(bdf)
            if vid_did is not None:
                remaining_devices.append(device)

        self._devices = remaining_devices

    async def scan_bus_bind(self, memory_start: int):
        (_, mmio_base) = await self._scan_bus(self._root_complex.get_root_bus(), memory_start)
        return mmio_base

    async def _scan_bus(
        self, bus: int, memory_start: int, parent_device_info: Optional[PciDeviceInfo] = None
    ) -> Tuple[int, int]:
        existing_bdfs = [device.bdf for device in self._devices]
        logger.debug(self._create_message(f"Scanning PCI Bus {bus}"))
        bdf_list = generate_bdfs_for_bus(bus)
        multi_function_devices = set()

        for bdf in bdf_list:
            device_number = extract_device_from_bdf(bdf)
            function_number = extract_function_from_bdf(bdf)

            if function_number != 0 and device_number not in multi_function_devices:
                continue

            vid_did = await self._read_vid_did(bdf)
            if vid_did is None:
                continue

            is_multifunction = (await self.read_config(bdf, 0x0E, 1) & 0x80) >> 7
            if is_multifunction:
                multi_function_devices.add(device_number)

            class_code = await self._read_class_code(bdf)

            vendor_id = 0xFFFF & vid_did
            device_id = (vid_did >> 4) & 0xFFFF
            is_bridge = (class_code >> 8) == BRIDGE_CLASS
            if bdf not in existing_bdfs:
                pci_device_info = PciDeviceInfo(
                    bdf=bdf,
                    vendor_id=vendor_id,
                    device_id=device_id,
                    class_code=class_code,
                    is_bridge=is_bridge,
                )
                if parent_device_info:
                    parent_device_info.children.append(pci_device_info)
                    pci_device_info.parent = parent_device_info

                for _ in range(NUM_BARS_BRIDGE if is_bridge else NUM_BARS_ENDPOINT):
                    pci_device_info.bars.append(PciBarInfo())

                self._devices.append(pci_device_info)

                # Scan PCI capabilities
                await self._scan_pci_capabilities(bdf, pci_device_info)
                await self._scan_sn(pci_device_info)

                # Set memory base and memory limit
                size = await self._check_bar_size_and_set(bdf, memory_start, pci_device_info)
                # NOTE: assume size is less than 0x100000
                if size > 0:
                    memory_start += 0x100000
                else:
                    logger.debug(
                        self._create_message(f"BAR0 size of {bdf_to_string(bdf)} is {size}")
                    )
            else:
                for device in self._devices:
                    if device.bdf == bdf:
                        pci_device_info = device

            if is_bridge:
                logger.debug(
                    self._create_message(
                        f"Found a bridge device at {bdf_to_string(bdf)} (VID/DID:{vid_did:08x})"
                    )
                )

                await self._set_secondary_bus(bdf, bus + 1)
                await self._set_subordinate_bus(bdf, 0xFF)

                (bus, memory_end) = await self._scan_bus(bus + 1, memory_start, pci_device_info)

                if memory_start != memory_end:
                    await self._set_memory_base(bdf, memory_start)
                    await self._set_memory_limit(bdf, memory_end - 1)

                memory_start = memory_end
                await self._set_subordinate_bus(bdf, bus)

                # NOTE: Set prefetchable base and limit. Assuming there are no devices
                # requesting prefetchable memory
                await self._set_prefetchable_memory_base(bdf, 0xFFF00000)
                await self._set_prefetchable_memory_limit(bdf, 0xFFE00000)
            else:
                logger.debug(
                    self._create_message(
                        f"Found an endpoint device at {bdf_to_string(bdf)} "
                        f"(VID/DID:{vid_did:08x})"
                    )
                )

        return (bus, memory_start)

    # pylint: enable=duplicate-code
