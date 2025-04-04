"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from typing import TypedDict, Dict, Optional
from opencis.util.unaligned_bit_structure import (
    BitMaskedBitStructure,
    BitField,
    ByteField,
    ShareableByteArray,
    StructureField,
    FIELD_ATTR,
)
from opencis.pci.component.pci import (
    PciComponentIdentity,
    PCI_DEVICE_PORT_TYPE,
)


# TODO: Add an option to support setting next capability pointer
class PciExpressCapabilityListRegister(BitMaskedBitStructure):
    _fields = [
        BitField("capability_id", 0, 7, FIELD_ATTR.RO, 0x10),
        BitField("next_capability_pointer", 8, 15, FIELD_ATTR.RO),
    ]


class PciExpressCapabilitiesRegisterOptions(TypedDict):
    pci_component_identity: PciComponentIdentity


class PciExpressCapabilitiesRegister(BitMaskedBitStructure):
    def __init__(
        self,
        data: ShareableByteArray | None = None,
        parent_name: str | None = None,
        options: PciExpressCapabilitiesRegisterOptions = None,
    ):
        if not options:
            raise Exception("options is required")

        device_port_type = options["pci_component_identity"].device_port_type
        slot_implemented = (
            1
            if device_port_type == PCI_DEVICE_PORT_TYPE.DOWNSTREAM_PORT_OF_PCI_EXPRESS_SWITCH
            else 0
        )
        self._fields = [
            BitField("capability_version", 0, 3, FIELD_ATTR.RO, 0x2),
            BitField(
                "device_port_type",
                4,
                7,
                FIELD_ATTR.RO,
                default=device_port_type,
            ),
            BitField("slot_implemented", 8, 8, FIELD_ATTR.HW_INIT, default=slot_implemented),
            BitField("interrupt_message_number", 9, 13, FIELD_ATTR.RO),
            BitField("undefined", 14, 14, FIELD_ATTR.RO),
            BitField("reserved1", 15, 15, FIELD_ATTR.RESERVED, 0),
        ]

        super().__init__(data, parent_name)

    @staticmethod
    def get_size_from_options(_: Optional[Dict] = None) -> int:
        return 2


class LinkCapabilitiesRegisterOptions(TypedDict):
    pci_component_identity: PciComponentIdentity


class LinkCapabilitiesRegister(BitMaskedBitStructure):
    def __init__(
        self,
        data: ShareableByteArray | None = None,
        parent_name: str | None = None,
        options: Optional[LinkCapabilitiesRegisterOptions] = None,
    ):
        if not options:
            raise Exception("options is required")

        self._identity = options["pci_component_identity"]

        self._fields = [
            BitField("max_link_speed", 0, 3, FIELD_ATTR.RO),
            BitField("reserved0", 4, 9, FIELD_ATTR.RESERVED),
            BitField("maximum_link_width", 10, 11, FIELD_ATTR.RO),
            BitField("aspm_support", 12, 14, FIELD_ATTR.RO),
            BitField("l0s_exit_latency", 15, 17, FIELD_ATTR.RO),
            BitField("l1_exit_latency", 18, 20, FIELD_ATTR.RO),
            BitField("clock_power_management", 21, 21, FIELD_ATTR.RO),
            BitField("surprise_down_error_reporting_capable", 22, 22, FIELD_ATTR.RO),
            BitField("data_link_layer_link_active_reporting_capable", 23, 23, FIELD_ATTR.RO),
            BitField("link_bandwidth_notification_capability", 24, 24, FIELD_ATTR.RO),
            BitField("reserved1", 25, 30, FIELD_ATTR.RESERVED),
            BitField("port_number", 31, 31, FIELD_ATTR.HW_INIT),
        ]

        super().__init__(data, parent_name)

    def read_bytes(self, start_offset: int, end_offset: int) -> int:
        value = super().read_bytes(start_offset, end_offset)
        value |= (self._identity.port_number & 0xFF) << 24
        return value

    @classmethod
    def get_size_from_options(cls, _: Optional[Dict] = None) -> int:
        return cls.get_size()


class PciExpressCapabilityRegisterOptions(TypedDict):
    pci_component_identity: PciComponentIdentity


class PciExpressCapabilityRegister(BitMaskedBitStructure):
    def __init__(
        self,
        data: ShareableByteArray | None = None,
        parent_name: str | None = None,
        options: PciExpressCapabilitiesRegisterOptions = None,
    ):
        if not options:
            raise Exception("options is required")

        self._fields = [
            StructureField("capability_list", 0x00, 0x01, PciExpressCapabilityListRegister),
            StructureField(
                "pcie_capabilities",
                0x02,
                0x03,
                PciExpressCapabilitiesRegister,
                options=options,
            ),
            ByteField(
                "device_capabilities",
                0x04,
                0x07,
                attribute=FIELD_ATTR.RO,
                default=0x00008000,
            ),
            ByteField("device_control", 0x08, 0x09, attribute=FIELD_ATTR.RW),
            ByteField("device_status", 0x0A, 0x0B, attribute=FIELD_ATTR.RW),
            StructureField(
                "link_capabilities", 0x0C, 0x0F, LinkCapabilitiesRegister, options=options
            ),
            ByteField("link_control", 0x10, 0x11, attribute=FIELD_ATTR.RW),
            ByteField("link_status", 0x12, 0x13, attribute=FIELD_ATTR.RW),
            ByteField("slot_capabilities", 0x14, 0x17, attribute=FIELD_ATTR.RO),
            ByteField("slot_control", 0x18, 0x19, attribute=FIELD_ATTR.RW),
            ByteField("slot_status", 0x1A, 0x1B, attribute=FIELD_ATTR.RW),
            ByteField("root_control", 0x1C, 0x1D, attribute=FIELD_ATTR.RESERVED),
            ByteField("root_capabilities", 0x1E, 0x1F, attribute=FIELD_ATTR.RESERVED),
            ByteField("root_status", 0x20, 0x23, attribute=FIELD_ATTR.RESERVED),
            ByteField("device_capabilities2", 0x24, 0x27, attribute=FIELD_ATTR.RO),
            ByteField("device_control2", 0x28, 0x29, attribute=FIELD_ATTR.RW),
            ByteField("device_status2", 0x2A, 0x2B, attribute=FIELD_ATTR.RESERVED),
            ByteField("link_capabilities2", 0x2C, 0x2F, attribute=FIELD_ATTR.RO),
            ByteField("link_control2", 0x30, 0x31, attribute=FIELD_ATTR.RW),
            ByteField("link_status2", 0x32, 0x33, attribute=FIELD_ATTR.RW),
            ByteField("slot_capabilities2", 0x34, 0x37, attribute=FIELD_ATTR.RO),
            ByteField("slot_control2", 0x38, 0x39, attribute=FIELD_ATTR.RESERVED),
            ByteField("slot_status2", 0x3A, 0x3B, attribute=FIELD_ATTR.RESERVED),
            ByteField("reserved1", 0x3C, 0x3F, attribute=FIELD_ATTR.RESERVED),
        ]

        super().__init__(data, parent_name)

    @staticmethod
    def get_size_from_options(_: Optional[Dict] = None) -> int:
        return 0x40
