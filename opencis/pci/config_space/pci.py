"""
Copyright (c) 2024, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from typing import TypedDict, Optional, List
from enum import IntEnum, Enum
from opencis.util.unaligned_bit_structure import (
    ShareableByteArray,
    BitMaskedBitStructure,
    BitField,
    ByteField,
    StructureField,
    FIELD_ATTR,
    DataField,
)
from opencis.pci.component.pci import (
    PciComponent,
    PciBridgeComponent,
    PciComponentIdentity,
    memory_base_regval_to_addr,
    memory_limit_regval_to_addr,
)
from opencis.pci.component.mmio_manager import MmioManager


class REG_ADDR(Enum):
    VENDOR_ID = (0x00, 0x01)
    DEVICE_ID = (0x02, 0x03)
    CLASS_CODE = (0x09, 0x0B)
    PRIMARY_BUS_NUMBER = (0x18, 0x18)
    SECONDARY_BUS_NUMBER = (0x19, 0x19)
    SUBORDINATE_BUS_NUMBER = (0x1A, 0x1A)
    MEMORY_BASE = (0x20, 0x21)
    MEMORY_LIMIT = (0x22, 0x23)
    PREFETCHABLE_MEMORY_BASE = (0x24, 0x25)
    PREFETCHABLE_MEMORY_LIMIT = (0x26, 0x27)
    PREFETCHABLE_MEMORY_BASE_UPPER = (0x28, 0x2B)
    PREFETCHABLE_MEMORY_LIMIT_UPPER = (0x2C, 0x2F)

    def __init__(self, s, e):
        self.s = s
        self.e = e

    @property
    def START(self):
        return self.s

    @property
    def END(self):
        return self.e

    @property
    def LEN(self):
        return self.e - self.s + 1


class BAR_OFFSETS(IntEnum):
    BAR0: int = 0x10
    BAR1: int = 0x14
    BAR2: int = 0x18
    BAR3: int = 0x1C
    BAR4: int = 0x20
    BAR5: int = 0x24


TOTAL_TYPE0_BARS = 6
TOTAL_TYPE1_BARS = 2
BAR_REGISTER_SIZE = 4
PCI_CONFIG_SPACE_HEADER_SIZE = 0x40


class PciConfigSpaceCommand(BitMaskedBitStructure):
    io_space_enable: int
    memory_space_enable: int
    bus_master_enable: int
    parity_error_response: int
    serrb_enable: int
    interrupt_disable: int

    _fields = [
        BitField("io_space_enable", 0, 0, FIELD_ATTR.RW),
        BitField("memory_space_enable", 1, 1, FIELD_ATTR.RW),
        BitField("bus_master_enable", 2, 2, FIELD_ATTR.RW),
        BitField("reserved1", 3, 3, FIELD_ATTR.RESERVED),
        BitField("reserved2", 4, 4, FIELD_ATTR.RESERVED),
        BitField("reserved3", 5, 5, FIELD_ATTR.RESERVED),
        BitField("parity_error_response", 6, 6, FIELD_ATTR.RW),
        BitField("reserved4", 7, 7, FIELD_ATTR.RESERVED),
        BitField("serrb_enable", 8, 8, FIELD_ATTR.RW),
        BitField("reserved5", 9, 9, FIELD_ATTR.RESERVED),
        BitField("interrupt_disable", 10, 10, FIELD_ATTR.RW),
        BitField("reserved6", 11, 15, FIELD_ATTR.RESERVED),
    ]


class PciConfigSpaceStatus(BitMaskedBitStructure):
    immediate_readiness: int
    interrupt_status: int
    capabilities_list: int
    master_data_parity_enable: int
    signaled_target_abort: int
    received_target_abort: int
    received_master_abort: int
    signaled_system_error: int
    detected_parity_error: int

    _fields = [
        BitField("immediate_readiness", 0, 0, FIELD_ATTR.RO, 1),
        BitField("reserved1", 1, 2, FIELD_ATTR.RESERVED),
        BitField("interrupt_status", 3, 3, FIELD_ATTR.RO),
        BitField("capabilities_list", 4, 4, FIELD_ATTR.RO, 1),
        BitField("reserved2", 5, 5, FIELD_ATTR.RESERVED),
        BitField("reserved3", 6, 6, FIELD_ATTR.RESERVED),
        BitField("reserved4", 7, 7, FIELD_ATTR.RESERVED),
        BitField("master_data_parity_enable", 8, 8, FIELD_ATTR.RW1C),
        BitField("reserved5", 9, 10, FIELD_ATTR.RESERVED),
        BitField("signaled_target_abort", 11, 11, FIELD_ATTR.RW1C),
        BitField("received_target_abort", 12, 12, FIELD_ATTR.RW1C),
        BitField("received_master_abort", 13, 13, FIELD_ATTR.RW1C),
        BitField("signaled_system_error", 14, 14, FIELD_ATTR.RW1C),
        BitField("detected_parity_error", 15, 15, FIELD_ATTR.RW1C),
    ]


class PciConfigSpaceClassCodeOptions(TypedDict):
    programming_interface: int
    sub_class_code: int
    base_class_code: int


class PciConfigSpaceClassCode(BitMaskedBitStructure):
    programming_interface: int
    sub_class_code: int
    base_class_code: int

    def __init__(
        self,
        data: Optional[ShareableByteArray] = None,
        parent_name: Optional[str] = None,
        options: Optional[PciConfigSpaceClassCodeOptions] = None,
    ):
        if not options:
            raise Exception("options is required")
        programming_interface = options["programming_interface"]
        sub_class_code = options["sub_class_code"]
        base_class_code = options["base_class_code"]

        self._fields = [
            ByteField(
                "programming_interface",
                0,
                0,
                attribute=FIELD_ATTR.RO,
                default=programming_interface,
            ),
            ByteField("sub_class_code", 1, 1, attribute=FIELD_ATTR.RO, default=sub_class_code),
            ByteField(
                "base_class_code",
                2,
                2,
                attribute=FIELD_ATTR.RO,
                default=base_class_code,
            ),
        ]
        super().__init__(data, parent_name)


class PciConfigSpaceHeaderType(BitMaskedBitStructure):
    header_layout: int
    multi_function_device: int

    _fields = [
        BitField("header_layout", 0, 6, FIELD_ATTR.RO),
        BitField("multi_function_device", 7, 7, FIELD_ATTR.RO),
    ]


class PciConfigSpaceBist(BitMaskedBitStructure):
    completion_code: int
    start_bist: int
    bist_capable: int

    _fields = [
        BitField("completion_code", 0, 3, FIELD_ATTR.RO),
        BitField("reserved1", 4, 5, FIELD_ATTR.RESERVED),
        BitField("start_bist", 6, 6, FIELD_ATTR.RW),  # RW if BIST Capable is 0
        BitField("bist_capable", 7, 7, FIELD_ATTR.HW_INIT),
    ]


class PciConfigSpaceBarMem64Low(BitMaskedBitStructure):
    _fields = [
        BitField("memory_space_indicator", 0, 0, FIELD_ATTR.HW_INIT),
        BitField("memory_type", 1, 2, FIELD_ATTR.HW_INIT),
        BitField("base_address", 3, 31, FIELD_ATTR.RW),
    ]


class PciConfigSpaceBarMem64High(BitMaskedBitStructure):
    _fields = [
        BitField("base_address", 0, 31, FIELD_ATTR.RW),
    ]


class PciConfigSpaceOptions(TypedDict):
    capability_pointer: Optional[int]
    pci_component: Optional[PciComponent]


class PciConfigSpaceType0Options(PciConfigSpaceOptions):
    pass


def create_common_fields(identity: PciComponentIdentity, is_type0: bool) -> List[DataField]:
    vendor_id = identity.vendor_id
    device_id = identity.device_id
    base_class_code = identity.base_class_code
    sub_class_code = identity.sub_class_coce
    programming_interface = identity.programming_interface

    class_code_options = PciConfigSpaceClassCodeOptions(
        programming_interface=programming_interface,
        sub_class_code=sub_class_code,
        base_class_code=base_class_code,
    )

    header_type = 0b00000000 if is_type0 else 0b00000001

    return [
        ByteField("vendor_id", 0, 1, attribute=FIELD_ATTR.HW_INIT, default=vendor_id),
        ByteField("device_id", 2, 3, attribute=FIELD_ATTR.HW_INIT, default=device_id),
        StructureField("command", 4, 5, PciConfigSpaceCommand),
        StructureField("status", 6, 7, PciConfigSpaceStatus),
        ByteField("revision_id", 8, 8, attribute=FIELD_ATTR.HW_INIT),
        StructureField(
            "class_code",
            9,
            0xB,
            PciConfigSpaceClassCode,
            options=class_code_options,
        ),
        ByteField("cache_line_size", 0xC, 0xC, attribute=FIELD_ATTR.RW),
        ByteField("reserved1", 0xD, 0xD, attribute=FIELD_ATTR.RESERVED),
        StructureField("header_type", 0xE, 0xE, PciConfigSpaceHeaderType, default=header_type),
        StructureField("bist", 0xF, 0xF, PciConfigSpaceBist),
    ]


def create_bar_fields(ranges: int, mmio_manager: MmioManager) -> List[DataField]:
    fields = []
    for bar_index in range(ranges):
        default = 0
        mask = 0
        attribute = FIELD_ATTR.HW_INIT

        # TODO: Handle Bar with 64bit address

        bar_size = mmio_manager.get_bar_size(bar_index)
        info = mmio_manager.get_bar_info(bar_index)
        if info and bar_size > 0:
            attribute = FIELD_ATTR.RW
            default |= (info.memory_type & 0b11) << 1
            default |= (info.prefetchable & 0b1) << 3
            mask = ~(bar_size - 1) & 0xFFFFFFFF

        start = BAR_OFFSETS.BAR0 + bar_index * BAR_REGISTER_SIZE
        end = BAR_OFFSETS.BAR0 + (bar_index + 1) * BAR_REGISTER_SIZE - 1
        fields.append(
            ByteField(
                f"bar{bar_index}",
                start,
                end,
                attribute=attribute,
                default=default,
                mask=mask,
            )
        )
    return fields


class PciConfigSpaceType0(BitMaskedBitStructure):
    vendor_id: int
    device_id: int
    command: PciConfigSpaceCommand
    status: PciConfigSpaceStatus
    revision_id: int
    class_code: PciConfigSpaceClassCode
    cache_line_size: int
    header_type: PciConfigSpaceHeaderType
    bist: PciConfigSpaceBist
    bar0: int
    bar1: int
    bar2: int
    bar3: int
    bar4: int
    bar5: int
    subsystem_vendor_id: int
    subsystem_id: int
    expansion_rom_bar: int
    capability_pointer: int
    interrupt_line: int
    interrupt_pin: int

    def __init__(
        self,
        data: Optional[ShareableByteArray] = None,
        parent_name: Optional[str] = None,
        options: Optional[PciConfigSpaceOptions] = None,
    ):
        capability_pointer = 0
        if options:
            capability_pointer = options.get("capability_pointer")

        capability_pointer = options.get("capability_pointer")
        pci_component = options.get("pci_component")
        if pci_component:
            self.mmio_manager = pci_component.get_mmio_manager()
            identity = pci_component.get_identity()
        else:
            self.mmio_manager = None
            identity = PciComponentIdentity()

        vendor_id = identity.vendor_id
        device_id = identity.device_id
        base_class_code = identity.base_class_code
        sub_class_code = identity.sub_class_coce
        programming_interface = identity.programming_interface
        subsystem_vendor_id = identity.subsystem_vendor_id
        subsystem_id = identity.subsystem_id

        class_code_options = PciConfigSpaceClassCodeOptions(
            programming_interface=programming_interface,
            sub_class_code=sub_class_code,
            base_class_code=base_class_code,
        )

        self._fields = [
            ByteField("vendor_id", 0, 1, attribute=FIELD_ATTR.HW_INIT, default=vendor_id),
            ByteField("device_id", 2, 3, attribute=FIELD_ATTR.HW_INIT, default=device_id),
            StructureField("command", 4, 5, PciConfigSpaceCommand),
            StructureField("status", 6, 7, PciConfigSpaceStatus),
            ByteField("revision_id", 8, 8, attribute=FIELD_ATTR.HW_INIT),
            StructureField(
                "class_code",
                9,
                0xB,
                PciConfigSpaceClassCode,
                options=class_code_options,
            ),
            ByteField("cache_line_size", 0xC, 0xC, attribute=FIELD_ATTR.RW),
            ByteField("reserved1", 0xD, 0xD, attribute=FIELD_ATTR.RESERVED),
            StructureField("header_type", 0xE, 0xE, PciConfigSpaceHeaderType),
            StructureField("bist", 0xF, 0xF, PciConfigSpaceBist),
        ]

        for bar_index in range(TOTAL_TYPE0_BARS):
            default = 0
            mask = 0
            attribute = FIELD_ATTR.HW_INIT
            # TODO: Handle Bar with 64bit address
            if self.mmio_manager:
                bar_size = self.mmio_manager.get_bar_size(bar_index)
                info = self.mmio_manager.get_bar_info(bar_index)
                if info and bar_size > 0:
                    attribute = FIELD_ATTR.RW
                    default |= (info.memory_type & 0b11) << 1
                    default |= (info.prefetchable & 0b1) << 3
                    mask = ~(bar_size - 1) & 0xFFFFFFFF

            start = BAR_OFFSETS.BAR0 + bar_index * BAR_REGISTER_SIZE
            end = BAR_OFFSETS.BAR0 + (bar_index + 1) * BAR_REGISTER_SIZE - 1
            self._fields.append(
                ByteField(
                    f"bar{bar_index}",
                    start,
                    end,
                    attribute=attribute,
                    default=default,
                    mask=mask,
                )
            )

        self._fields += [
            ByteField("reserved2", 0x28, 0x2B, attribute=FIELD_ATTR.RESERVED),
            ByteField("subsystem_vendor_id", 0x2C, 0x2D, default=subsystem_vendor_id),
            ByteField("subsystem_id", 0x2E, 0x2F, default=subsystem_id),
            ByteField("expansion_rom_bar", 0x30, 0x33),
            ByteField("capability_pointer", 0x34, 0x34, default=capability_pointer),
            ByteField("reserved3", 0x35, 0x3B, attribute=FIELD_ATTR.RESERVED),
            ByteField("interrupt_line", 0x3C, 0x3C),
            ByteField("interrupt_pin", 0x3D, 0x3D),
            ByteField("reseved4", 0x3E, 0x3F),
        ]

        super().__init__(data, parent_name)

    def write_bytes(self, start_offset: int, end_offset: int, value: int):
        super().write_bytes(start_offset, end_offset, value)
        if start_offset >= BAR_OFFSETS.BAR0 and end_offset < BAR_OFFSETS.BAR5 + BAR_REGISTER_SIZE:
            bar_index = (start_offset - BAR_OFFSETS.BAR0) // BAR_REGISTER_SIZE
            bar_size = self.mmio_manager.get_bar_size(bar_index)
            mask = ~(bar_size - 1) & 0xFFFFFFFF
            if value != mask:
                self.mmio_manager.set_bar(bar_index, value)

    @staticmethod
    def get_size_from_options(options: Optional[PciConfigSpaceOptions]):
        return 0x40


class PciConfigSpaceSecondaryStatus(BitMaskedBitStructure):
    master_data_parity_enable: int
    signaled_target_abort: int
    received_target_abort: int
    received_master_abort: int
    signaled_system_error: int
    detected_parity_error: int

    _fields = [
        BitField("reserved1", 0, 4, FIELD_ATTR.RESERVED),
        # 66 MHz Capable must be hardwired to 0
        BitField("reserved2", 5, 5, FIELD_ATTR.RESERVED),
        # Fast Back-to-Back Transaction Capable must be hardwired to 0
        BitField("reserved3", 6, 6, FIELD_ATTR.RESERVED),
        # DEVSL Timing must be hardwired to 0
        BitField("reserved4", 7, 7, FIELD_ATTR.RESERVED),
        BitField("master_data_parity_enable", 8, 8),
        BitField("reserved5", 9, 10, FIELD_ATTR.RESERVED),
        BitField("signaled_target_abort", 11, 11),
        BitField("received_target_abort", 12, 12),
        BitField("received_master_abort", 13, 13),
        BitField("signaled_system_error", 14, 14),
        BitField("detected_parity_error", 15, 15),
    ]


class BridgeControl(BitMaskedBitStructure):
    _fields = [
        BitField("parity_error_response_enable", 0, 0, FIELD_ATTR.RW, 0b0),
        BitField("serr_enable", 1, 1, FIELD_ATTR.RW, 0b0),
        BitField("isa_enable", 2, 2, FIELD_ATTR.RW, 0b0),
        BitField("vga_enable", 3, 3, FIELD_ATTR.RW, 0b0),
        BitField("vga_16_bit_decode", 4, 4, FIELD_ATTR.RW, 0b0),
        BitField("reserved0", 5, 5, FIELD_ATTR.RESERVED, 0b0),
        BitField("secondary_bus_reset", 6, 6, FIELD_ATTR.RW, 0b0),
        BitField("reserved1", 7, 15, FIELD_ATTR.RESERVED, 0x0),
    ]


class PciConfigSpaceType1Options(TypedDict):
    pci_bridge_component: PciBridgeComponent
    capability_pointer: Optional[int]


class PciConfigSpaceType1(BitMaskedBitStructure):
    vendor_id: int
    device_id: int
    command: PciConfigSpaceCommand
    status: PciConfigSpaceStatus
    revision_id: int
    class_code: PciConfigSpaceClassCode
    cache_line_size: int
    header_type: PciConfigSpaceHeaderType
    bist: PciConfigSpaceBist
    bar0: int
    bar1: int
    primary_bus_number: int
    secondary_bus_number: int
    subordinate_bus_number: int
    io_base: int
    io_limit: int
    secondary_status: PciConfigSpaceSecondaryStatus
    memory_base: int
    memory_limit: int
    prefetchable_memory_base: int
    prefetchable_memory_limit: int
    prefetchable_base_upper: int
    prefetchable_limit_upper: int
    io_base_upper: int
    io_limit_upper: int
    capability_pointer: int
    expansion_rom_bar: int
    interrupt_line: int
    interrupt_pin: int

    def __init__(
        self,
        data: Optional[ShareableByteArray] = None,
        parent_name: Optional[str] = None,
        options: Optional[PciConfigSpaceType1Options] = None,
    ):
        if not options:
            raise Exception("options is required")

        self._capability_pointer = options.get("capability_pointer", 0)
        self._pci_bridge_component = options["pci_bridge_component"]
        self._mmio_manager = self._pci_bridge_component.get_mmio_manager()
        identity = self._pci_bridge_component.get_identity()

        self._fields = (
            create_common_fields(identity, is_type0=False) + self._create_type_specific_fields()
        )

        super().__init__(data, parent_name)

    def _create_type_specific_fields(self) -> List[DataField]:
        return create_bar_fields(TOTAL_TYPE1_BARS, self._mmio_manager) + [
            ByteField("primary_bus_number", 0x18, 0x18),
            ByteField("secondary_bus_number", 0x19, 0x19),
            ByteField("subordinate_bus_number", 0x1A, 0x1A),
            ByteField("reserved2", 0x1B, 0x1B, attribute=FIELD_ATTR.RESERVED),
            ByteField("io_base", 0x1C, 0x1C),
            ByteField("io_limit", 0x1D, 0x1D),
            StructureField("secondary_status", 0x1E, 0x1F, PciConfigSpaceSecondaryStatus),
            ByteField("memory_base", 0x20, 0x21),
            ByteField("memory_limit", 0x22, 0x23),
            ByteField("prefetchable_memory_base", 0x24, 0x25, attribute=FIELD_ATTR.RO),
            ByteField("prefetchable_memory_limit", 0x26, 0x27, attribute=FIELD_ATTR.RO),
            ByteField("prefetchable_base_upper", 0x28, 0x2B, attribute=FIELD_ATTR.RO),
            ByteField("prefetchable_limit_upper", 0x2C, 0x2F, attribute=FIELD_ATTR.RO),
            ByteField("io_base_upper", 0x30, 0x31),
            ByteField("io_limit_upper", 0x32, 0x33),
            ByteField("capability_pointer", 0x34, 0x34, default=self._capability_pointer),
            ByteField("reserved3", 0x35, 0x37, attribute=FIELD_ATTR.RESERVED),
            ByteField("expansion_rom_bar", 0x38, 0x3B, attribute=FIELD_ATTR.RO),
            ByteField("interrupt_line", 0x3C, 0x3C),
            ByteField("interrupt_pin", 0x3D, 0x3D),
            StructureField(
                "bridge_control",
                0x3E,
                0x3F,
                BridgeControl,
            ),
        ]

    def _update_bar(self, start_offset: int, end_offset: int, value: int):
        if start_offset >= BAR_OFFSETS.BAR0 and end_offset < BAR_OFFSETS.BAR1 + BAR_REGISTER_SIZE:
            base = value
            bar_index = (start_offset - BAR_OFFSETS.BAR0) // BAR_REGISTER_SIZE
            bar_size = self._mmio_manager.get_bar_size(bar_index)
            mask = ~(bar_size - 1) & 0xFFFFFFFF
            limit = base + bar_size - 1
            if value != mask:
                self._mmio_manager.set_bar(bar_index, base)
                self._pci_bridge_component.set_bar(bar_index, base, limit)

    def _update_secondary_bus_number(self, start_offset: int, end_offset: int, value: int):
        if (
            start_offset >= REG_ADDR.SECONDARY_BUS_NUMBER.START
            and end_offset <= REG_ADDR.SECONDARY_BUS_NUMBER.END
        ):
            self._pci_bridge_component.set_secondary_bus_number(value)

    def _update_subordinate_bus_number(self, start_offset: int, end_offset: int, value: int):
        if (
            start_offset >= REG_ADDR.SUBORDINATE_BUS_NUMBER.START
            and end_offset <= REG_ADDR.SUBORDINATE_BUS_NUMBER.END
        ):
            self._pci_bridge_component.set_subordinate_bus_number(value)

    def _update_memory_base(self, start_offset: int, end_offset: int, value: int):
        if start_offset >= REG_ADDR.MEMORY_BASE.START and end_offset <= REG_ADDR.MEMORY_BASE.END:
            addr = memory_base_regval_to_addr(value)
            self._pci_bridge_component.set_memory_base(addr)

    def _update_memory_limit(self, start_offset: int, end_offset: int, value: int):
        if start_offset >= REG_ADDR.MEMORY_LIMIT.START and end_offset <= REG_ADDR.MEMORY_LIMIT.END:
            addr = memory_limit_regval_to_addr(value)
            self._pci_bridge_component.set_memory_limit(addr)

    def _update_prefetchable_memory_base(self, start_offset: int, end_offset: int):
        # TODO: Check if prefetchable memory is supported
        has_update = False
        if (
            start_offset >= REG_ADDR.PREFETCHABLE_MEMORY_BASE.START
            and end_offset <= REG_ADDR.PREFETCHABLE_MEMORY_BASE.END
        ):
            has_update = True

        if (
            start_offset >= REG_ADDR.PREFETCHABLE_MEMORY_BASE_UPPER.START
            and end_offset <= REG_ADDR.PREFETCHABLE_MEMORY_BASE_UPPER.END
        ):
            has_update = True

        if has_update:
            base = self.prefetchable_memory_base | self.prefetchable_base_upper << 32
            self._pci_bridge_component.set_prefetchable_memory_base(base)

    def _update_prefetchable_memory_limit(self, start_offset: int, end_offset: int):
        # TODO: Check if prefetchable memory is supported
        has_update = False
        if (
            start_offset >= REG_ADDR.PREFETCHABLE_MEMORY_LIMIT.START
            and end_offset <= REG_ADDR.PREFETCHABLE_MEMORY_LIMIT.END
        ):
            has_update = True

        if (
            start_offset >= REG_ADDR.PREFETCHABLE_MEMORY_LIMIT_UPPER.START
            and end_offset <= REG_ADDR.PREFETCHABLE_MEMORY_LIMIT_UPPER.END
        ):
            has_update = True

        if has_update:
            limit = self.prefetchable_memory_limit | self.prefetchable_limit_upper << 32
            self._pci_bridge_component.set_prefetchable_memory_limit(limit)

    def write_bytes(self, start_offset: int, end_offset: int, value: int):
        super().write_bytes(start_offset, end_offset, value)
        self._update_bar(start_offset, end_offset, value)
        self._update_secondary_bus_number(start_offset, end_offset, value)
        self._update_subordinate_bus_number(start_offset, end_offset, value)
        self._update_memory_base(start_offset, end_offset, value)
        self._update_memory_limit(start_offset, end_offset, value)
        self._update_prefetchable_memory_base(start_offset, end_offset)
        self._update_prefetchable_memory_limit(start_offset, end_offset)

    @staticmethod
    def get_size_from_options(options: Optional[PciConfigSpaceOptions]):
        return 0x40
