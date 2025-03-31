"""
Copyright (c) 2024, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from typing import Optional, TypedDict, cast

from opencis.util.unaligned_bit_structure import (
    BitMaskedBitStructure,
    ShareableByteArray,
    BitField,
    FIELD_ATTR,
)


class DvsecCapabilityHeaderOptions(TypedDict):
    next_capability_offset: str


class DvsecCapabilityHeader(BitMaskedBitStructure):
    def __init__(
        self,
        data: Optional[ShareableByteArray] = None,
        parent_name: Optional[str] = None,
        options: Optional[DvsecCapabilityHeaderOptions] = None,
    ):
        next_capability_offset = 0
        if options:
            casted_options = cast(DvsecCapabilityHeaderOptions, options)
            next_capability_offset = casted_options["next_capability_offset"]

        self._fields = [
            BitField("capability_id", 0, 15, FIELD_ATTR.RO, 0x0023),
            BitField("capability_version", 16, 19, FIELD_ATTR.RO, 0x1),
            BitField("next_capability_offset", 20, 31, FIELD_ATTR.RO, next_capability_offset),
        ]

        super().__init__(data, parent_name)
