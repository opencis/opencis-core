"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from enum import IntEnum
from typing import Optional, Dict, TypedDict, List, cast

from opencis.util.unaligned_bit_structure import (
    ShareableByteArray,
    BitMaskedBitStructure,
    BitField,
    ByteField,
    StructureField,
    FIELD_ATTR,
)
from opencis.cxl.config_space.dvsec.common import (
    DvsecCapabilityHeader,
    DvsecCapabilityHeaderOptions,
)


class BLOCK_IDENTIFIER(IntEnum):
    EMPTY = 0x00
    COMPONENT_REGISTER = 0x01
    BAR_VIRTUALIZATION_ACL_REGISTER = 0x02
    CXL_DEVICE_REGISTER = 0x03
    CPMU_REGISTER = 0x04


class RegisterLocatorDvsecHeader1(BitMaskedBitStructure):
    def __init__(
        self,
        data: Optional[ShareableByteArray] = None,
        parent_name: Optional[str] = None,
        options: Optional[Dict] = None,
    ):
        if "length" not in options:
            raise Exception('options["length"] is missing from RegisterLocatorDvsecHeader1')

        length = options["length"]
        self._fields = [
            BitField("dvsec_vendor_id", 0, 15, FIELD_ATTR.RO, 0x1E98),
            BitField("dvsec_revision_id", 16, 19, FIELD_ATTR.RO, 0x0),
            BitField("dvsec_length", 20, 31, FIELD_ATTR.RO, length),
        ]

        super().__init__(data, parent_name)


class RegisterOffsetOptions(TypedDict):
    bir: int
    block_identifier: BLOCK_IDENTIFIER
    block_offset: int


class RegisterOffset(BitMaskedBitStructure):
    def __init__(
        self,
        data: Optional[ShareableByteArray] = None,
        parent_name: Optional[str] = None,
        options: Optional[RegisterOffsetOptions] = None,
    ):
        bir = 0
        block_identifier = 0
        offset_low = 0
        offset_high = 0

        if options:
            register = cast(RegisterOffsetOptions, options)
            bir = register["bir"]
            block_identifier = register["block_identifier"]
            block_offset = register["block_offset"]

            if block_offset & 0xFFFF > 0:
                raise Exception("options.register.offset must be 64-KB aligned")
            offset_low = (block_offset >> 16) & 0xFFFF
            offset_high = block_offset >> 32

        self._fields = [
            BitField("register_bir", 0, 2, FIELD_ATTR.HW_INIT, bir),
            BitField("reserved1", 3, 7, FIELD_ATTR.RESERVED),
            BitField("register_block_identifier", 8, 15, FIELD_ATTR.HW_INIT, block_identifier),
            BitField("register_block_offset_low", 16, 31, FIELD_ATTR.HW_INIT, offset_low),
            BitField("register_block_offset_high", 32, 63, FIELD_ATTR.HW_INIT, offset_high),
        ]

        super().__init__(data, parent_name)


class DvsecRegisterLocatorOptions(TypedDict):
    registers: List[RegisterOffsetOptions]
    header: Optional[DvsecCapabilityHeaderOptions]


class DvsecRegisterLocator(BitMaskedBitStructure):
    def __init__(
        self,
        data: Optional[ShareableByteArray] = None,
        parent_name: Optional[str] = None,
        options: Optional[DvsecRegisterLocatorOptions] = None,
    ):
        if not options or "registers" not in options.keys():
            raise Exception('options["registers"] is missing from DvsecRegisterLocator')

        header_options = None
        if options:
            header_options = options.get("header")

        registers = options["registers"]
        length = DvsecRegisterLocator.get_size_from_options(options)
        self._fields = [
            StructureField(
                "capability_header", 0, 3, DvsecCapabilityHeader, options=header_options
            ),
            StructureField(
                "dvsec_header1",
                4,
                7,
                RegisterLocatorDvsecHeader1,
                options={"length": length},
            ),
            ByteField("dvsec_header2", 8, 9, attribute=FIELD_ATTR.RO, default=0x0008),
            ByteField("reserved1", 0xA, 0xB, attribute=FIELD_ATTR.RESERVED),
        ]

        for idx, register_option in enumerate(registers):
            self._fields.append(
                StructureField(
                    f"register_block{idx+1}_offset",
                    0x0C + idx * 8,
                    0x13 + idx * 8,
                    RegisterOffset,
                    options=register_option,
                )
            )

        super().__init__(data, parent_name)

    @staticmethod
    def get_size_from_options(options: Optional[DvsecRegisterLocatorOptions]):
        if not options or "registers" not in options.keys():
            raise Exception('options["registers"] is missing from DvsecRegisterLocator')
        registers = cast(List[RegisterOffsetOptions], options["registers"])
        length = 0xC + len(registers) * 8
        return length
