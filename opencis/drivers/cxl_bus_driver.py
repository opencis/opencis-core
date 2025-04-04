"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from typing import Optional, List, Dict
from dataclasses import dataclass, field
from enum import IntEnum
from opencis.cxl.component.hdm_decoder import (
    HDM_DECODER_COUNT,
    HDM_COUNT_TO_NUM,
)
from opencis.util.component import LabeledComponent, Label
from opencis.cxl.component.root_complex.root_complex import RootComplex
from opencis.pci.component.pci import PCI_DEVICE_PORT_TYPE
from opencis.drivers.pci_bus_driver import PciBusDriver, PciDeviceInfo
from opencis.util.logger import logger
from opencis.util.pci import bdf_to_string

CXL_CACHEMEM_REGISTER_HEADER_SIZE = 4
CXL_HDM_DECODER_CAPABILITY_REGISTER_SIZE = 4
CXL_HDM_DECODER_CONTROL_REGISTER_SIZE = 4
CXL_HDM_DECODER_CONTROL_REGISTER_COMMITTED_MASK = 0x400


class CXL_REGISTER_TYPE(IntEnum):
    EMPTY = 0x00
    COMPONENT = 0x01
    BAR_VIRTUALIZATION_ACL = 0x02
    CXL_DEVICE = 0x03
    CPMU = 0x04
    DESIGNATED_VENDOR_SPECIFIC = 0xFF


class CXL_DVSEC_ID(IntEnum):
    PCIE_DVSEC_FOR_CXL_DEVICES = 0x0000
    CXL_EXTENSION_DVSEC_FOR_PORTS = 0x0003
    GPF_DVSEC_FOR_CXL_PORTS = 0x0004
    GPF_DVSEC_FOR_CXL_DEVICES = 0x0005
    PCIE_DVSEC_FOR_FLEX_BUS_PORT = 0x0007
    REGISTER_LOCATOR_DVSEC = 0x0008


class CXL_CACHEMEM_REGISTER_CAPABILITY_ID(IntEnum):
    CXL = 0x0001
    CXL_RAS = 0x0002
    CXL_SECURITY = 0x0003
    CXL_LINK = 0x0004
    CXL_HDM_DECODER = 0x0005
    CXL_EXTENDED_SECURITY = 0x0006
    CXL_IDE = 0x0007
    CXL_SNOOP_FILTER = 0x0008
    CXL_TIME_AND_ISOLATION = 0x0009
    CXL_EXTENDED_CACHEMEM_REGISTER = 0x000A
    CXL_BI_ROUTE_TABLE = 0x000B
    CXL_BI_DECODER = 0x000C
    CXL_CACHE_ID_ROUTE_TABLE = 0x000D
    CXL_CACHE_ID_DECODER = 0x000E
    CXL_EXTENDED_HDM_DECODER = 0x000F
    CXL_EXTENDED_METADATA = 0x0010


@dataclass
class CxlRegisterInfo:
    type: CXL_REGISTER_TYPE
    bar: int
    offset: int
    address: int = 0


@dataclass
class CxlDvsecInfo:
    id: int
    revision: int
    offset: int
    length: int


@dataclass
class CxlCacheMemRegisterInfo:
    id: int
    version: int
    offset: int
    address: int


@dataclass
class CxlDeviceDvsecRangeInfo:
    memory_info_valid: bool
    memory_active: bool
    media_type: int
    memory_class: int
    desired_interleve: int
    memory_active_timeout: int
    memory_active_degraded: bool
    memory_size: int
    memory_base: int


@dataclass
class CxlDeviceDvsecInfo:
    cache_capable: bool = False
    io_capable: bool = False
    mem_capable: bool = False
    ranges: List[CxlDeviceDvsecRangeInfo] = field(default_factory=list)

    def print(self, prefix: str = ""):
        logger.debug(f"{prefix}Cache Capable  : {'Yes' if self.cache_capable else 'No'}")
        logger.debug(f"{prefix}IO Capable     : {'Yes' if self.io_capable else 'No'}")
        logger.debug(f"{prefix}Mem Capable    : {'Yes' if self.mem_capable else 'No'}")
        for range_index, range in enumerate(self.ranges):
            logger.debug(f"{prefix}Range{range_index+1} Size    : 0x{range.memory_size:X}")


@dataclass
class CxlDeviceInfo:
    root_complex: RootComplex
    pci_device_info: PciDeviceInfo
    registers: List[CxlRegisterInfo] = field(default_factory=list)
    dvsecs: List[CxlDvsecInfo] = field(default_factory=list)
    cachemem_registers: Dict[int, CxlCacheMemRegisterInfo] = field(default_factory=dict)
    parent: Optional["CxlDeviceInfo"] = None
    children: List["CxlDeviceInfo"] = field(default_factory=list)
    device_dvsec: Optional[CxlDeviceDvsecInfo] = None
    log_prefix: str = "CxlDevice"

    def get_dvsec_by_id(self, id: CXL_DVSEC_ID):
        for dvsec in self.dvsecs:
            if dvsec.id == id:
                return dvsec
        return None

    def get_register_by_type(self, type: CXL_REGISTER_TYPE) -> Optional[CxlRegisterInfo]:
        for register in self.registers:
            if register.type == type:
                return register
        return None

    def get_cachemem_register_by_id(self, id: CXL_CACHEMEM_REGISTER_CAPABILITY_ID):
        if id in self.cachemem_registers:
            return self.cachemem_registers[id]
        return None

    def _get_prefix(self) -> str:
        return f"[{self.log_prefix}:{self.pci_device_info.get_bdf_string()}] "

    # pylint: disable=duplicate-code

    async def _get_hdm_decoder_count(self, register_base_address: int) -> int:
        hdm_decoder_cap = await self.root_complex.read_mmio(
            register_base_address, CXL_HDM_DECODER_CAPABILITY_REGISTER_SIZE
        )
        decoder_count_index = HDM_DECODER_COUNT(hdm_decoder_cap & 0xF)
        if decoder_count_index >= len(HDM_DECODER_COUNT):
            logger.warning(
                f"{self._get_prefix()}HDM Decoder count, 0x{decoder_count_index:X}, "
                "is not supported"
            )
            return 0
        decoder_count = HDM_COUNT_TO_NUM.calc(decoder_count_index)
        if (
            self.pci_device_info.get_device_port_type() == PCI_DEVICE_PORT_TYPE.PCI_EXPRESS_ENDPOINT
            and decoder_count > 10
        ):
            logger.warning(
                f"{self._get_prefix()}CXL device shall not advertise more than 10 decoders"
            )
            return 0

        logger.debug(f"{self._get_prefix()}Total of {decoder_count} decoders are supported")
        return decoder_count

    async def _get_next_available_decoder_index(self, register_base_address: int) -> Optional[int]:
        decoder_count = await self._get_hdm_decoder_count(register_base_address)
        if decoder_count == 0:
            return None

        next_available_decoder = None
        for decoder_index in range(decoder_count):
            register_offset = 0x20 + decoder_index * 0x20 + register_base_address
            register_value = await self.root_complex.read_mmio(
                register_offset, CXL_HDM_DECODER_CONTROL_REGISTER_SIZE
            )
            is_committed = bool(register_value & CXL_HDM_DECODER_CONTROL_REGISTER_COMMITTED_MASK)
            if not is_committed:
                next_available_decoder = decoder_index
                break
        return next_available_decoder

    async def _configure_hdm_decoder_common(
        self,
        register_base_address: int,
        decoder_index: int,
        hpa_base: int,
        hpa_size: int,
        interleaving_granularity: int = 0,
        interleaving_way: int = 0,
    ):
        decoder_base_low_offset = 0x20 * decoder_index + 0x10 + register_base_address
        decoder_base_high_offset = 0x20 * decoder_index + 0x14 + register_base_address
        decoder_size_low_offset = 0x20 * decoder_index + 0x18 + register_base_address
        decoder_size_high_offset = 0x20 * decoder_index + 0x1C + register_base_address
        decoder_control_register_offset = 0x20 * decoder_index + 0x20 + register_base_address

        commit = 1

        decoder_base_low = hpa_base & 0xFFFFFFFF
        decoder_base_high = (hpa_base >> 32) & 0xFFFFFFFF
        decoder_size_low = hpa_size & 0xFFFFFFFF
        decoder_size_high = (hpa_size >> 32) & 0xFFFFFFFF

        decoder_control = (
            interleaving_granularity & 0xF | (interleaving_way & 0xF) << 4 | commit << 9
        )

        logger.debug(f"{self._get_prefix()}HDM Decoder {decoder_index}, HPA Base: 0x{hpa_base:x}")
        logger.debug(f"{self._get_prefix()}HDM Decoder {decoder_index}, HPA Size: 0x{hpa_size:x}")

        await self.root_complex.write_mmio(decoder_base_low_offset, 4, decoder_base_low)
        await self.root_complex.write_mmio(decoder_base_high_offset, 4, decoder_base_high)
        await self.root_complex.write_mmio(decoder_size_low_offset, 4, decoder_size_low)
        await self.root_complex.write_mmio(decoder_size_high_offset, 4, decoder_size_high)
        await self.root_complex.write_mmio(decoder_control_register_offset, 4, decoder_control)

        logger.debug(f"{self._get_prefix()}Waiting until the decoder is committed")
        committed = False
        while not committed:
            control = await self.root_complex.read_mmio(decoder_control_register_offset, 4)
            committed = bool(control & CXL_HDM_DECODER_CONTROL_REGISTER_COMMITTED_MASK)

    async def configure_hdm_decoder_device(
        self,
        hpa_base: int,
        hpa_size: int,
        dpa_skip: int = 0,
        interleaving_granularity: int = 0,
        interleaving_way: int = 0,
    ) -> bool:
        hdm_decoder = self.get_cachemem_register_by_id(
            CXL_CACHEMEM_REGISTER_CAPABILITY_ID.CXL_HDM_DECODER
        )

        if not hdm_decoder:
            logger.warning(f"{self._get_prefix()} HDM Decoder Register not found")
            return False

        register_base_address = hdm_decoder.address
        decoder_index = await self._get_next_available_decoder_index(register_base_address)
        if decoder_index is None:
            logger.warning(f"{self._get_prefix()}Not found any available HDM decoders")
            return False

        logger.debug(
            f"{self._get_prefix()}HDM Decoder Capability Offset: 0x{register_base_address:x}"
        )
        logger.debug(f"{self._get_prefix()}Setting HDM Decoder {decoder_index} from CXL Device")

        dpa_skip_low_offset = 0x20 * decoder_index + 0x24 + register_base_address
        dpa_skip_high_offset = 0x20 * decoder_index + 0x28 + register_base_address
        dpa_skip_low = dpa_skip & 0xFFFFFFFF
        dpa_skip_high = (dpa_skip >> 32) & 0xFFFFFFFF
        await self.root_complex.write_mmio(dpa_skip_low_offset, 4, dpa_skip_low)
        await self.root_complex.write_mmio(dpa_skip_high_offset, 4, dpa_skip_high)

        await self._configure_hdm_decoder_common(
            register_base_address,
            decoder_index,
            hpa_base,
            hpa_size,
            interleaving_granularity,
            interleaving_way,
        )

        logger.debug(f"{self._get_prefix()}Successfully configured HDM decoder {decoder_index}")
        return True

    async def configure_hdm_decoder_switch(
        self,
        hpa_base: int,
        hpa_size: int,
        target_list: List[int],
        interleaving_granularity: int = 0,
        interleaving_way: int = 0,
    ) -> bool:
        hdm_decoder = self.get_cachemem_register_by_id(
            CXL_CACHEMEM_REGISTER_CAPABILITY_ID.CXL_HDM_DECODER
        )

        if not hdm_decoder:
            return False

        register_base_address = hdm_decoder.address
        decoder_index = await self._get_next_available_decoder_index(register_base_address)
        if decoder_index is None:
            logger.warning(f"{self._get_prefix()}Not found any available HDM decoders")
            return False

        register_base_address = hdm_decoder.address
        logger.debug(
            f"{self._get_prefix()}HDM Decoder Capability Offset: 0x{register_base_address:x}"
        )
        logger.debug(f"{self._get_prefix()}Setting HDM Decoder {decoder_index} from Upstream Port")
        target_list_low_offset = 0x20 * decoder_index + 0x24 + register_base_address
        target_list_high_offset = 0x20 * decoder_index + 0x28 + register_base_address
        target_list_low = 0
        target_list_high = 0

        target_list_str = ", ".join([str(target) for target in target_list])
        logger.debug(
            f"{self._get_prefix()}HDM Decoder {decoder_index}, Target Ports: {target_list_str}"
        )
        for i, _ in enumerate(target_list):
            if i < 4:
                target_list_low |= (target_list[i] & 0xFF) << (i * 8)
            elif i < 8:
                target_list_high |= (target_list[i] & 0xFF) << ((i - 4) * 8)

        await self.root_complex.write_mmio(target_list_low_offset, 4, target_list_low)
        await self.root_complex.write_mmio(target_list_high_offset, 4, target_list_high)

        await self._configure_hdm_decoder_common(
            register_base_address,
            decoder_index,
            hpa_base,
            hpa_size,
            interleaving_granularity,
            interleaving_way,
        )

        logger.debug(
            f"{self._get_prefix()}Successfully configured HDM decoder (switch) {decoder_index}"
        )
        return True

    async def get_bi_enable(self) -> bool:
        bi_decoder_control_reg = self.get_cachemem_register_by_id(
            CXL_CACHEMEM_REGISTER_CAPABILITY_ID.CXL_BI_DECODER
        )
        if bi_decoder_control_reg is None:
            return False

        reg_val = await self.root_complex.read_mmio(bi_decoder_control_reg.address, 4)
        return reg_val & 0x2 != 0

    # pylint: enable=duplicate-code

    def get_memory_size(self) -> int:
        if not self.device_dvsec:
            return 0
        size = 0
        for range in self.device_dvsec.ranges:
            size += range.memory_size
        return size

    def is_upstream_port(self) -> bool:
        device_port_type = self.pci_device_info.get_device_port_type()
        return device_port_type == PCI_DEVICE_PORT_TYPE.UPSTREAM_PORT_OF_PCI_EXPRESS_SWITCH

    def is_downstream_port(self) -> bool:
        device_port_type = self.pci_device_info.get_device_port_type()
        return device_port_type == PCI_DEVICE_PORT_TYPE.DOWNSTREAM_PORT_OF_PCI_EXPRESS_SWITCH

    def is_cxl_device(self) -> bool:
        device_port_type = self.pci_device_info.get_device_port_type()
        return device_port_type == PCI_DEVICE_PORT_TYPE.PCI_EXPRESS_ENDPOINT and self.device_dvsec


class CxlBusDriver(LabeledComponent):
    def __init__(
        self, pci_bus_driver: PciBusDriver, root_complex: RootComplex, label: Label = None
    ):
        super().__init__(label)
        self._root_complex = root_complex
        self._pci_bus_driver = pci_bus_driver
        self._devices: List[CxlDeviceInfo] = []

    async def init(self):
        await self._scan_cxl_devices()
        await self._connect_cxl_devices()
        self.display_devices()

    def get_devices(self) -> List[CxlDeviceInfo]:
        return self._devices

    def display_devices(self):
        logger.debug(self._create_message("Enumerated CXL Devices"))
        logger.debug(self._create_message("=============================="))
        for device in self._devices:
            pci_info = device.pci_device_info
            logger.debug(self._create_message(f"BDF              : {bdf_to_string(pci_info.bdf)}"))
            device_port_type = pci_info.get_device_port_type()
            if device_port_type is not None:
                logger.debug(self._create_message(f"Type             : {device_port_type.name}"))
            if device.parent:
                logger.debug(
                    self._create_message(
                        f"Parent BDF       : {bdf_to_string(device.parent.pci_device_info.bdf)}"
                    )
                )
            if len(device.children) > 0:
                children_bdf_list = [
                    bdf_to_string(child.pci_device_info.bdf) for child in device.children
                ]
                logger.debug(
                    self._create_message(f"Children BDFs    : {', '.join(children_bdf_list)}")
                )
            if len(device.dvsecs) > 0:
                logger.debug(self._create_message("DVSEC            :"))
                for dvsec_info in device.dvsecs:
                    logger.debug(self._create_message(f" - {CXL_DVSEC_ID(dvsec_info.id).name}"))
                    if (
                        dvsec_info.id == CXL_DVSEC_ID.PCIE_DVSEC_FOR_CXL_DEVICES
                        and device.device_dvsec
                    ):
                        device.device_dvsec.print("[CxlBusDriver]      ")

            component_register = device.get_register_by_type(CXL_REGISTER_TYPE.COMPONENT)
            if component_register:
                logger.debug(
                    self._create_message(f"Component Register: 0x{component_register.address:X}")
                )
                if len(device.cachemem_registers.items()) > 0:
                    for register in device.cachemem_registers.values():
                        logger.debug(
                            self._create_message(
                                f" - {CXL_CACHEMEM_REGISTER_CAPABILITY_ID(register.id).name}: "
                                f"0x{register.address:X}"
                            )
                        )

            logger.debug(self._create_message("------------------------------"))

    async def _connect_cxl_devices(self):
        bdf_map = {}
        for device in self._devices:
            device.parent = None
            device.children = []
            bdf_map[device.pci_device_info.bdf] = device

        # Map parent
        for device in self._devices:
            if device.pci_device_info.parent:
                if device.pci_device_info.parent.bdf in bdf_map:
                    device.parent = bdf_map[device.pci_device_info.parent.bdf]
        # Map children
        for device in self._devices:
            if device.parent:
                device.parent.children.append(device)

    # pylint: disable=duplicate-code

    async def _scan_register_locator_dvsec(self, device_info: CxlDeviceInfo):
        bdf = device_info.pci_device_info.bdf
        register_locator_dvsec = device_info.get_dvsec_by_id(CXL_DVSEC_ID.REGISTER_LOCATOR_DVSEC)
        if not register_locator_dvsec:
            raise Exception("Call this method only when the PCIE_DVSEC_FOR_CXL_DEVICES exists")

        cap_offset = register_locator_dvsec.offset
        length = register_locator_dvsec.length

        block_offset_base = 0x0C
        blocks = int((length - block_offset_base) / 8)
        block_size = 8
        for block_index in range(blocks):
            block_offset = block_offset_base + block_index * block_size

            register_offset_low = await self._root_complex.read_config(
                bdf, cap_offset + block_offset, 4
            )
            if register_offset_low is None:
                raise Exception(
                    f"Failed to read Register Block {block_index + 1} - Register Offset Low"
                )
            register_offset_high = await self._root_complex.read_config(
                bdf, cap_offset + block_offset + 4, 4
            )
            if register_offset_high is None:
                raise Exception(
                    f"Failed to read Register Block {block_index + 1} - Register Offset High"
                )

            register_bir = register_offset_low & 0x7
            register_block_identifier = (register_offset_low >> 8) & 0xFF
            bar_offset = (register_offset_low & 0xFFFF0000) | register_offset_high << 32
            address = device_info.pci_device_info.bars[register_bir].base_address + bar_offset
            register_type = CXL_REGISTER_TYPE(register_block_identifier)
            register_info = CxlRegisterInfo(
                type=register_type,
                bar=register_bir,
                offset=bar_offset,
                address=address,
            )
            logger.debug(
                self._create_message(
                    f"(Block {block_index + 1}) " f"{register_type.name}, BAR: {register_info.bar}"
                )
            )
            logger.debug(
                self._create_message(
                    f"(Block {block_index + 1}) "
                    f"{register_type.name}, OFFSET: 0x{register_info.offset:X}"
                )
            )
            logger.debug(
                self._create_message(
                    f"(Block {block_index + 1}) "
                    f"{register_type.name}, ADDRESS: 0x{register_info.address:X}"
                )
            )
            device_info.registers.append(register_info)

    # pylint: enable=duplicate-code

    async def _scan_pcie_dvsec_for_cxl_devices(self, device_info: CxlDeviceInfo):
        device_dvsec = device_info.get_dvsec_by_id(CXL_DVSEC_ID.PCIE_DVSEC_FOR_CXL_DEVICES)
        if not device_dvsec:
            raise Exception("Call this method only when the PCIE_DVSEC_FOR_CXL_DEVICES exists")

        bdf = device_info.pci_device_info.bdf
        # TODO: Define OFFSETs as IntEnum
        dvsec_cxl_capability_offset = device_dvsec.offset + 0x0A
        capability = await self._root_complex.read_config(bdf, dvsec_cxl_capability_offset, 2)
        cache_capable = bool(capability & 0x01)
        io_capable = bool(capability & 0x02)
        mem_capable = bool(capability & 0x04)
        device_info.device_dvsec = CxlDeviceDvsecInfo(
            cache_capable=cache_capable, io_capable=io_capable, mem_capable=mem_capable
        )

        for range_index in range(2):
            range_size_high_offset = device_dvsec.offset + 0x18 + range_index * 0x10
            size_high = await self._root_complex.read_config(bdf, range_size_high_offset, 4)
            range_size_low_offset = device_dvsec.offset + 0x1C + range_index * 0x10
            size_low = await self._root_complex.read_config(bdf, range_size_low_offset, 4)

            range_base_high_offset = device_dvsec.offset + 0x20 + range_index * 0x10
            base_high = await self._root_complex.read_config(bdf, range_base_high_offset, 4)
            range_base_low_offset = device_dvsec.offset + 0x24 + range_index * 0x10
            base_low = await self._root_complex.read_config(bdf, range_base_low_offset, 4)

            memory_info_valid = bool(size_low & 0b1)
            memory_active = bool((size_low >> 1) & 0b1)
            media_type = (size_low >> 2) & 0b111
            media_class = (size_low >> 5) & 0b111
            desired_interleave = (size_low >> 8) & 0b11111
            memory_active_timeout = (size_low >> 13) & 0b111
            memory_active_degraded = bool((size_low >> 16) & 0b1)
            memory_size = (size_high << 32) | (size_low & 0xF0000000)
            memory_base = (base_high << 32) | (base_low & 0xF0000000)

            range_info = CxlDeviceDvsecRangeInfo(
                memory_info_valid=memory_info_valid,
                memory_active=memory_active,
                media_type=media_type,
                memory_class=media_class,
                desired_interleve=desired_interleave,
                memory_active_timeout=memory_active_timeout,
                memory_active_degraded=memory_active_degraded,
                memory_size=memory_size,
                memory_base=memory_base,
            )
            device_info.device_dvsec.ranges.append(range_info)

    # pylint: disable=duplicate-code

    async def _scan_dvsec(self, device_info: CxlDeviceInfo):
        for capability in device_info.pci_device_info.capabilities:
            is_dvsec = capability.id == 0x0023 and capability.version == 0x1
            if not is_dvsec:
                continue

            bdf = device_info.pci_device_info.bdf
            offset = capability.offset
            dvsec_header1 = await self._root_complex.read_config(bdf, offset + 0x04, 4)
            if dvsec_header1 is None:
                raise Exception("Failed to read DVSEC Header 1")
            dvsec_header2 = await self._root_complex.read_config(bdf, offset + 0x08, 2)
            if dvsec_header2 is None:
                raise Exception("Failed to read DVSEC Header 2")

            vendor_id = dvsec_header1 & 0xFFFF
            revision_id = (dvsec_header1 >> 16) & 0xF
            length = (dvsec_header1 >> 20) & 0xFFF
            dvsec_id = dvsec_header2

            is_cxl_dvsec = vendor_id == 0x1E98
            if not is_cxl_dvsec:
                continue

            dvsec_info = CxlDvsecInfo(
                id=dvsec_id, revision=revision_id, length=length, offset=offset
            )
            device_info.dvsecs.append(dvsec_info)

            dvsec_function_map = {
                CXL_DVSEC_ID.PCIE_DVSEC_FOR_CXL_DEVICES: self._scan_pcie_dvsec_for_cxl_devices,
                CXL_DVSEC_ID.CXL_EXTENSION_DVSEC_FOR_PORTS: None,
                CXL_DVSEC_ID.GPF_DVSEC_FOR_CXL_PORTS: None,
                CXL_DVSEC_ID.GPF_DVSEC_FOR_CXL_DEVICES: None,
                CXL_DVSEC_ID.PCIE_DVSEC_FOR_FLEX_BUS_PORT: None,
                CXL_DVSEC_ID.REGISTER_LOCATOR_DVSEC: self._scan_register_locator_dvsec,
            }

            if dvsec_id not in dvsec_function_map:
                continue

            self._create_message(f"Found DVSEC - {CXL_DVSEC_ID(dvsec_id).name}")
            dvsec_function = dvsec_function_map[dvsec_id]
            if not dvsec_function:
                continue

            await dvsec_function(device_info)

    # pylint: enable=duplicate-code

    async def _scan_cachemem_registers(self, device_info: CxlDeviceInfo):
        component_register_info = device_info.get_register_by_type(CXL_REGISTER_TYPE.COMPONENT)
        if not component_register_info:
            return

        cxl_cachemem_offset = component_register_info.address + 0x1000

        logger.debug(
            self._create_message(
                f"Scanning CXL.cache and CXL.mem Registers at 0x{cxl_cachemem_offset:x}"
            )
        )

        cxl_capability_header = await self._root_complex.read_mmio(
            cxl_cachemem_offset, CXL_CACHEMEM_REGISTER_HEADER_SIZE
        )
        # TODO: Define constants for masks
        cxl_capability_id = cxl_capability_header & 0xFFFF
        cxl_capability_version = (cxl_capability_header >> 16) & 0xF
        cxl_cachemem_version = (cxl_capability_header >> 20) & 0xF
        array_size = (cxl_capability_header >> 24) & 0xFF

        logger.debug(self._create_message(f"cxl_capability_id: {cxl_capability_id:x}"))
        logger.debug(self._create_message(f"cxl_capability_version: {cxl_capability_version:x}"))
        logger.debug(self._create_message(f"cxl_cachemem_version: {cxl_cachemem_version:x}"))
        logger.debug(self._create_message(f"array_size: {array_size:x}"))

        if cxl_capability_id != CXL_CACHEMEM_REGISTER_CAPABILITY_ID.CXL:
            return

        for header_index in range(array_size):
            header_offset = (
                header_index + 1
            ) * CXL_CACHEMEM_REGISTER_HEADER_SIZE + cxl_cachemem_offset
            header_info = await self._root_complex.read_mmio(
                header_offset, CXL_CACHEMEM_REGISTER_HEADER_SIZE
            )

            # TODO: Define constants for masks
            cxl_capability_id = header_info & 0xFFFF
            cxl_capability_version = (header_info >> 16) & 0xF
            offset = (header_info >> 20) & 0xFFF
            cxl_capability_address = cxl_cachemem_offset + offset
            capability_name = CXL_CACHEMEM_REGISTER_CAPABILITY_ID(cxl_capability_id).name
            logger.debug(self._create_message(f"Found {capability_name} Capability Header"))
            device_info.cachemem_registers[cxl_capability_id] = CxlCacheMemRegisterInfo(
                id=cxl_capability_id,
                version=cxl_capability_version,
                offset=offset,
                address=cxl_capability_address,
            )

    async def _scan_component_register(self, device_info: CxlDeviceInfo):
        await self._scan_cachemem_registers(device_info)

    async def _scan_cxl_devices(self):
        self._devices = []
        count = 0
        for device in self._pci_bus_driver.get_devices():
            count += 1
            is_cxl_device = False
            for capability in device.capabilities:
                if capability.id == 0x0023 and capability.version == 0x1:
                    is_cxl_device = True
                    break
            if not is_cxl_device:
                continue
            logger.debug(self._create_message(f"Found CXL Device at {bdf_to_string(device.bdf)}"))
            device_info = CxlDeviceInfo(root_complex=self._root_complex, pci_device_info=device)
            self._devices.append(device_info)
            await self._scan_dvsec(device_info)
            await self._scan_component_register(device_info)
