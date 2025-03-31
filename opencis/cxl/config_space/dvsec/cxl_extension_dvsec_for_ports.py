"""
Copyright (c) 2024, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from typing import TypedDict, List, Optional

from opencis.util.unaligned_bit_structure import (
    ShareableByteArray,
    BitMaskedBitStructure,
    BitField,
    ByteField,
    StructureField,
    DataField,
    FIELD_ATTR,
)
from opencis.cxl.config_space.dvsec.common import (
    DvsecCapabilityHeader,
    DvsecCapabilityHeaderOptions,
)


class CxlDvsecHeader1(BitMaskedBitStructure):
    _fields = [
        BitField("dvsec_vendor_id", 0, 15, FIELD_ATTR.RO, 0x1E98),
        BitField("dvsec_revision_id", 16, 19, FIELD_ATTR.RO, 0x0),
        BitField("dvsec_length", 20, 31, FIELD_ATTR.RO, 0x028),
    ]


class CxlPortExtensionStatus(BitMaskedBitStructure):
    # TODO: Connect this register to a logic block later
    _fields = [
        BitField("port_power_management_initialization_complete", 0, 0, FIELD_ATTR.RO),
        BitField("reserved1", 1, 13, FIELD_ATTR.RESERVED),
        BitField("viral_status", 14, 14, FIELD_ATTR.RW1CS),
        BitField("reserved2", 15, 15, FIELD_ATTR.RESERVED),
    ]


class PortControlExtension(BitMaskedBitStructure):
    # TODO: Connect this register to a logic block later
    _fields = [
        BitField("unmask_srb", 0, 0, FIELD_ATTR.RW),
        BitField("unmask_link_disable", 1, 1, FIELD_ATTR.RW),
        BitField("alt_memory_and_id_space_enable", 2, 2, FIELD_ATTR.RW),
        BitField("alt_bme", 3, 3, FIELD_ATTR.RW),
        BitField("uio_to_hdm_enable", 4, 4, FIELD_ATTR.RW),
        BitField("reserved1", 5, 13, FIELD_ATTR.RESERVED),
        BitField("viral_enable", 14, 14, FIELD_ATTR.RW),
        BitField("reserved2", 15, 15, FIELD_ATTR.RW),
    ]


class CxlRcrbBase(BitMaskedBitStructure):
    # TODO: Connect this register to a logic block later
    _fields = [
        BitField("cxl_rcrb_enable", 0, 0, FIELD_ATTR.RW),
        BitField("reserved1", 1, 12, FIELD_ATTR.RESERVED),
        BitField("cxl_rcrb_base_address_low", 13, 31, FIELD_ATTR.RW),
    ]


class CxlExtensionDvsecForPortsOptions(TypedDict):
    header: DvsecCapabilityHeaderOptions


class CxlExtensionDvsecForPorts(BitMaskedBitStructure):
    def __init__(
        self,
        data: Optional[ShareableByteArray] = None,
        parent_name: Optional[str] = None,
        options: Optional[CxlExtensionDvsecForPortsOptions] = None,
    ):
        if not options:
            raise Exception("options is required")

        header_options = options["header"]
        self._fields = [
            StructureField(
                "capability_header",
                0x00,
                0x03,
                DvsecCapabilityHeader,
                options=header_options,
            ),
            StructureField("dvsec_header1", 0x04, 0x07, CxlDvsecHeader1),
            ByteField("dvsec_header2", 0x08, 0x09, attribute=FIELD_ATTR.RO, default=0x0003),
            StructureField("cxl_port_extension_status", 0x0A, 0x0B, CxlPortExtensionStatus),
            StructureField("port_control_extension", 0x0C, 0x0D, PortControlExtension),
            ByteField("alternate_bus_base", 0x0E, 0x0E),
            ByteField("alternate_bus_limit", 0x0F, 0x0F),
            ByteField("alternate_memory_base", 0x10, 0x11, mask=0xFFF0),
            ByteField("alternate_memory_limit", 0x12, 0x13, mask=0xFFF0),
            ByteField("alternate_prefetchable_memory_base", 0x14, 0x15, mask=0xFFF0),
            ByteField("alternate_prefetchable_memory_limit", 0x16, 0x17, mask=0xFFF0),
            ByteField("alternate_prefetchable_memory_base_high", 0x18, 0x1B),
            ByteField("alternate_prefetchable_memory_limit_high", 0x1C, 0x1F),
            StructureField("cxl_rcrb_base", 0x20, 0x23, CxlRcrbBase),
            ByteField("cxl_rcrb_base_high", 0x24, 0x27),
        ]

        super().__init__(data, parent_name)

    @staticmethod
    def get_size(fields: List[DataField] | None = None) -> int:
        return 0x28
