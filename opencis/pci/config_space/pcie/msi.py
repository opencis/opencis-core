"""
Copyright (c) 2024, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from typing import Dict, TypedDict, Optional
from enum import IntEnum
from opencis.util.unaligned_bit_structure import (
    BitMaskedBitStructure,
    BitField,
    ByteField,
    StructureField,
    FIELD_ATTR,
    ShareableByteArray,
)


class MsiCapabilityHeaderOptions(TypedDict):
    next_capability_offset: Optional[int]


class MsiCapabilityHeader(BitMaskedBitStructure):
    capability_id: int
    next_capability_offset: int

    def __init__(
        self,
        data: Optional[ShareableByteArray] = None,
        parent_name: Optional[str] = None,
        options: Optional[MsiCapabilityHeaderOptions] = None,
    ):
        if options is None:
            options = MsiCapabilityHeaderOptions()
        next_capability_offset = options.get("next_capability_offset", 0)

        self._fields = [
            BitField("capability_id", 0, 7, FIELD_ATTR.RO, 0x05),
            BitField("next_capability_offset", 8, 15, FIELD_ATTR.RO, next_capability_offset),
        ]

        super().__init__(data, parent_name)

    @staticmethod
    def get_size_from_options(_: Optional[Dict] = None) -> int:
        return 2


class MSI_VECTORS(IntEnum):
    ONE_VECTOR = 0b000
    TWO_VECTORS = 0b001
    FOUR_VECTORS = 0b010
    EIGHT_VECTORS = 0b011
    SIXTEEN_VECTORS = 0b100
    THIRTY_TWO_VECTORS = 0b101


# TOOD: Support supplying capability values as an option
class MessageControlRegister(BitMaskedBitStructure):
    _fields = [
        BitField("msi_enable", 0, 0, FIELD_ATTR.RW),
        BitField(
            "multiple_message_capable",
            1,
            3,
            FIELD_ATTR.RO,
            MSI_VECTORS.THIRTY_TWO_VECTORS,
        ),
        BitField("multiple_message_enable", 4, 6),
        BitField("sixty_four_bit_address_capable", 7, 7, FIELD_ATTR.RO, 1),
        BitField("per_vector_masking_capable", 8, 8, FIELD_ATTR.RO, 1),
        BitField("extended_message_data_capable", 9, 9, FIELD_ATTR.RO, 1),
        BitField("extended_message_data_enable", 10, 10, FIELD_ATTR.RW),
        BitField("reserved1", 11, 15, FIELD_ATTR.RESERVED),
    ]


class MsiCapabilityOptions(TypedDict):
    next_capability_offset: Optional[int]


class MsiCapability(BitMaskedBitStructure):
    capability_header: MsiCapabilityHeader
    message_control: MessageControlRegister

    def __init__(
        self,
        data: Optional[ShareableByteArray] = None,
        parent_name: Optional[str] = None,
        options: Optional[MsiCapabilityOptions] = None,
    ):
        if not options:
            options = MsiCapabilityOptions()

        next_capability_offset = options.get("next_capability_offset", 0)
        header_options: MsiCapabilityHeaderOptions = {
            "next_capability_offset": next_capability_offset,
        }

        self._fields = [
            StructureField(
                "capability_header",
                0x00,
                0x01,
                MsiCapabilityHeader,
                options=header_options,
            ),
            StructureField("message_control", 0x02, 0x03, MessageControlRegister),
            ByteField("message_address", 0x04, 0x07, FIELD_ATTR.RW),
            ByteField("message_upper_address", 0x08, 0x0B, FIELD_ATTR.RW),
            ByteField("message_data", 0x0C, 0x0D, FIELD_ATTR.RW),
            ByteField("extended_message_data", 0x0E, 0x0F, FIELD_ATTR.RW),
            ByteField("mask_bits", 0x10, 0x13, FIELD_ATTR.RW),
            ByteField("pending_bits", 0x14, 0x17, FIELD_ATTR.RW),
        ]

        super().__init__(data, parent_name)

    @staticmethod
    def get_size_from_options(_: Optional[Dict] = None) -> int:
        return 0x18
