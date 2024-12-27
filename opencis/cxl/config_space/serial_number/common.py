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
    StructureField,
)


class DeviceSNCapabilityHeaderOptions(TypedDict):
    next_capability_offset: int


class DeviceSNCapabilityHeader(BitMaskedBitStructure):
    def __init__(
        self,
        data: Optional[ShareableByteArray] = None,
        parent_name: Optional[str] = None,
        options: Optional[DeviceSNCapabilityHeaderOptions] = None,
    ):
        next_capability_offset = 0
        if options:
            casted_options = cast(DeviceSNCapabilityHeaderOptions, options)
            next_capability_offset = casted_options["next_capability_offset"]

        self._fields = [
            BitField("capability_id", 0, 15, FIELD_ATTR.RO, 0x0003),
            BitField("capability_version", 16, 19, FIELD_ATTR.RO, 0x1),
            BitField("next_capability_offset", 20, 31, FIELD_ATTR.RO, next_capability_offset),
        ]

        super().__init__(data, parent_name)


class DeviceSNHeaderOptions(TypedDict):
    serial_number: str


class DeviceSNHeader(BitMaskedBitStructure):
    def __init__(
        self,
        data: Optional[ShareableByteArray] = None,
        parent_name: Optional[str] = None,
        options: DeviceSNHeaderOptions = None,
    ):
        sn_int = 0
        if options:
            sn = options["serial_number"]
            try:
                sn_int = int(sn, base=16)
            except Exception as e:
                raise Exception(
                    f"Failed to convert device SN: {sn} into an int. "
                    "Check if it is a valid hex string."
                ) from e
        sn_low = sn_int & 0xFFFFFFFF
        sn_high = (sn_int >> 32) & 0xFFFFFFFF
        self._fields = [
            BitField("serial_number_low", 0, 31, FIELD_ATTR.RO, sn_low),
            BitField("serial_number_high", 32, 63, FIELD_ATTR.RO, sn_high),
        ]
        super().__init__(data, parent_name)


class DeviceSNCapabilityOptions(TypedDict):
    next: int
    sn: str


class DeviceSNCapability(BitMaskedBitStructure):
    def __init__(
        self,
        data: Optional[ShareableByteArray] = None,
        parent_name: Optional[str] = None,
        options: Optional[DeviceSNCapabilityOptions] = None,
    ):
        header_options = DeviceSNCapabilityHeaderOptions()
        sn_options = DeviceSNHeaderOptions()
        if options:
            header_options["next_capability_offset"] = options["next"]
            sn_options["serial_number"] = options["sn"]

        self._fields = [
            StructureField(
                "capability_header", 0, 3, DeviceSNCapabilityHeader, options=header_options
            ),
            StructureField("serial_number_header", 4, 11, DeviceSNHeader, options=sn_options),
        ]

        super().__init__(data, parent_name)

    @staticmethod
    def get_size(fields=None) -> int:
        return 12
