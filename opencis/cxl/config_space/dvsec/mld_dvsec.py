"""
Copyright (c) 2024-2025, Eeum, Inc.

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
        BitField("dvsec_length", 20, 31, FIELD_ATTR.RO, 0x010),
    ]


class MldDvsecOptions(TypedDict):
    header: DvsecCapabilityHeaderOptions


# cxl_extension_dvsec_for_ports.py looks similar
# pylint: disable=duplicate-code
class MldDvsec(BitMaskedBitStructure):
    def __init__(
        self,
        data: Optional[ShareableByteArray] = None,
        parent_name: Optional[str] = None,
        options: Optional[MldDvsecOptions] = None,
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
            ByteField("dvsec_header2", 0x08, 0x09, attribute=FIELD_ATTR.RO, default=0x0009),
            ByteField("number_of_lds_supported", 0x0A, 0x0B, attribute=FIELD_ATTR.HW_INIT),
            ByteField("ld_id_hot_reset_vector", 0x0C, 0x0D, attribute=FIELD_ATTR.RW),
            ByteField("reserved1", 0x0E, 0x0F, attribute=FIELD_ATTR.RESERVED),
        ]

        super().__init__(data, parent_name)

    @staticmethod
    def get_size(fields: List[DataField] | None = None) -> int:
        return 0x10
