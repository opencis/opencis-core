"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from enum import IntEnum
from typing import Union

from opencis.util.unaligned_bit_structure import (
    UnalignedBitStructure,
    ByteField,
)


class CdatHeader(UnalignedBitStructure):
    length: int
    revision: int
    checksum: int
    sequence: int

    _fields = [
        ByteField("length", 0, 3),
        ByteField("revision", 4, 4),
        ByteField("checksum", 5, 5),
        ByteField("reserved1", 6, 11),
        ByteField("sequence", 12, 15),
    ]


class DSMAS_FLAG(IntEnum):
    NON_VOLATILE = 0b10


class DeviceScopedMemoryAffinity(UnalignedBitStructure):
    type: int
    length: int
    dsmad_handle: int
    flags: int
    dpa_base: int
    dpa_length: int

    _fields = [
        ByteField("type", 0, 0, default=0),
        ByteField("reserved1", 1, 1),
        ByteField("length", 2, 3, default=24),
        ByteField("dsmad_handle", 4, 4),
        ByteField("flags", 5, 5),
        ByteField("reserved", 6, 7),
        ByteField("dpa_base", 8, 15),
        ByteField("dpa_length", 16, 23),
    ]


class HMAT_SLLB_DATA_TYPE(IntEnum):
    ACCESS_LATENCY = 0
    READ_LATENCY = 1
    WRITE_LATENCY = 2
    ACCESS_BANDWIDTH = 3
    READ_BANDWIDTH = 4
    WRITE_BANDWIDTH = 5


class HMAT_SLLB_FLAG(IntEnum):
    MEMORY = 0x00
    FIRST_LEVEL_MEMORY_SIDE_CACHE = 0x01
    SECOND_LEVEL_MEMORY_SIDE_CACHE = 0x02
    THIRD_LEVEL_MEMORY_SIDE_CACHE = 0x03
    MINIMUM_SIZE_TRANSFER_TO_ACHIEVE_VALUES = 0x10
    NON_SEQUENTIAL_TRANSFER = 0x20


class DeviceScropedLatencyBandwidthInformation(UnalignedBitStructure):
    type: int
    length: int
    handle: int
    flags: int
    data_type: int
    entry_base_unit: int
    entry0: int
    entry1: int
    entry2: int

    _fields = [
        ByteField("type", 0, 0, default=1),
        ByteField("reserved1", 1, 1),
        ByteField("length", 2, 3, default=24),
        ByteField("handle", 4, 4),
        ByteField("flags", 5, 5),
        ByteField("date_type", 6, 6),
        ByteField("reserved2", 7, 7),
        ByteField("entry_base_unit", 8, 15),
        ByteField("entry0", 16, 17),
        ByteField("entry1", 18, 19),
        ByteField("entry2", 20, 21),
        ByteField("reserved3", 22, 23),
    ]


class DeviceScopedMemorySideCacheInformation(UnalignedBitStructure):
    pass


class DeviceScopedEfiMemoryType(UnalignedBitStructure):
    type: int
    length: int
    dsmas_handle: int
    efi_memory_type_and_attribute: int
    dpa_offset: int
    dpa_length: int

    _fields = [
        ByteField("type", 0, 0, default=0),
        ByteField("reserved1", 1, 1),
        ByteField("length", 2, 3, default=24),
        ByteField("dsmas_handle", 4, 4),
        ByteField("efi_memory_type_and_attribute", 5, 5),
        ByteField("reserved", 6, 7),
        ByteField("dpa_offset", 8, 15),
        ByteField("dpa_length", 16, 23),
    ]


CDAT_ENTRY = Union[
    DeviceScopedMemoryAffinity,
    DeviceScropedLatencyBandwidthInformation,
    DeviceScopedMemorySideCacheInformation,
    DeviceScopedEfiMemoryType,
]
