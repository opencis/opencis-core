"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from dataclasses import dataclass
from opencis.util.unaligned_bit_structure import (
    UnalignedBitStructure,
    BitField,
    ByteField,
    StructureField,
)


# pylint: disable=duplicate-code
@dataclass
class RegionConfiguration:
    region_base: int
    region_decode_len: int
    region_len: int
    region_block_size: int
    dsmad_handle: int
    flags: int


class DsmadHandleStruct(UnalignedBitStructure):
    reserved0: int
    nonvolatile: int
    sharable: int
    hw_managed_coherency: int
    interconnect_specific_dc_mgmt: int
    read_only: int
    reserved1: int

    _fields = [
        BitField("reserved0", 0x00, 0x01),
        BitField("nonvolatile", 0x02, 0x02),
        BitField("sharable", 0x03, 0x03),
        BitField("hw_managed_coherency", 0x04, 0x04),
        BitField("interconnect_specific_dc_mgmt", 0x05, 0x05),
        BitField("read_only", 0x06, 0x06),
        BitField("reserved1", 0x07, 0x07),
        BitField("reserved2", 0x08, 0x1F),
    ]


class RegionConfigFlags(UnalignedBitStructure):
    sanitize_on_release: int
    reserved: int

    _fields = [
        BitField("sanitize_on_release", 0x00, 0x00),
        BitField("reserved", 0x01, 0x07),
    ]


class RegionConfigStruct(UnalignedBitStructure):
    region_base: int
    region_decode_len: int
    region_len: int
    region_block_size: int
    dsmad_handle: int
    flags: int
    reserved: int

    _fields = [
        ByteField("region_base", 0x00, 0x07),
        ByteField("region_decode_len", 0x08, 0x0F),
        ByteField("region_len", 0x10, 0x17),
        ByteField("region_block_size", 0x18, 0x1F),
        StructureField(
            "dsmad_handle",
            0x20,
            0x23,
            DsmadHandleStruct,
        ),
        StructureField(
            "flags",
            0x24,
            0x24,
            RegionConfigFlags,
        ),
        ByteField("reserved", 0x25, 0x27),
    ]


@dataclass
class DynamicCapacityExtent:
    start_dpa: int
    length: int
    tag: int
    shared_extent_seq: int


class DynamicCapacityExtentStruct(UnalignedBitStructure):
    start_dpa: int
    length: int
    tag: int
    shared_extent_seq: int
    reserved: int

    _fields = [
        ByteField("start_dpa", 0x00, 0x07),
        ByteField("length", 0x08, 0x0F),
        ByteField("tag", 0x10, 0x1F),
        ByteField("shared_extent_seq", 0x20, 0x21),
        ByteField("reserved", 0x22, 0x27),
    ]
