"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from typing import TypedDict, Optional, List
from opencis.util.unaligned_bit_structure import (
    BitMaskedBitStructure,
    BitField,
    StructureField,
    FIELD_ATTR,
    ShareableByteArray,
)


class CxlCapabilityHeaderRegisterOptions(TypedDict):
    size: Optional[int]
    pointer: Optional[int]


class CxlCapabilityHeaderRegister(BitMaskedBitStructure):
    cxl_capability_id: int
    cxl_capability_version: int
    cxl_cache_mem_version: int
    array_size: int

    def __init__(
        self,
        data: Optional[ShareableByteArray] = None,
        parent_name: Optional[str] = None,
        options: Optional[CxlCapabilityHeaderRegisterOptions] = None,
    ):
        array_size = 0
        if options:
            array_size = options.get("size", array_size)

        self._fields = [
            BitField("cxl_capability_id", 0, 15, FIELD_ATTR.RO, 0x0001),
            BitField("cxl_capability_version", 16, 19, FIELD_ATTR.RO, 0x1),
            BitField("cxl_cache_mem_version", 20, 23, FIELD_ATTR.RO, 0x1),
            BitField("array_size", 24, 31, FIELD_ATTR.RO, array_size),
        ]

        super().__init__(data, parent_name)


class CxlCapabilityItemHeaderOptions(TypedDict):
    id: int
    version: int
    pointer: int


class CxlCapabilityItemHeader(BitMaskedBitStructure):
    cxl_capability_id: int
    cxl_capability_version: int
    cxl_capability_pointer: int

    def __init__(
        self,
        data: Optional[ShareableByteArray] = None,
        parent_name: Optional[str] = None,
        options: Optional[CxlCapabilityItemHeaderOptions] = None,
    ):
        id = 0
        version = 0
        pointer = 0
        if options:
            id = options.get("id", id)
            version = options.get("version", version)
            pointer = options.get("pointer", pointer)

        self._fields = [
            BitField("cxl_capability_id", 0, 15, FIELD_ATTR.RO, id),
            BitField("cxl_capability_version", 16, 19, FIELD_ATTR.RO, version),
            BitField("cxl_capability_pointer", 20, 31, FIELD_ATTR.RO, pointer),
        ]

        super().__init__(data, parent_name)


class CxlCapabilityHeaderStructureOptions(TypedDict):
    ras: Optional[int]
    security: Optional[int]
    link: Optional[int]
    hdm_decoder: int = 0
    extended_security: Optional[int]
    ide: Optional[int]
    snoop_filter: Optional[int]
    timeout_isolation: Optional[int]
    cache_mem_extended_register: Optional[int]
    bi_route_table: Optional[int]
    bi_decoder: Optional[int]
    cache_id_route_table: Optional[int]
    cache_id_decoder: Optional[int]
    extended_hdm_decoder: Optional[int]


class CapabilityInfo(TypedDict):
    id: int
    version: int


CAPABILITY_NAME_TO_CAPABILITY_INFO_MAP = {
    "ras": CapabilityInfo(id=0x0002, version=0x2),
    "security": CapabilityInfo(id=0x0003, version=0x1),
    "link": CapabilityInfo(id=0x0004, version=0x2),
    "hdm_decoder": CapabilityInfo(id=0x0005, version=0x3),
    "extended_security": CapabilityInfo(id=0x0006, version=0x2),
    "ide": CapabilityInfo(id=0x0007, version=0x2),
    "snoop_filter": CapabilityInfo(id=0x0008, version=0x1),
    "timeout_isolation": CapabilityInfo(id=0x0009, version=0x1),
    "cache_mem_extended_register": CapabilityInfo(id=0x000A, version=0x1),
    "bi_route_table": CapabilityInfo(id=0x000B, version=0x1),
    "bi_decoder": CapabilityInfo(id=0x000C, version=0x1),
    "cache_id_route_table": CapabilityInfo(id=0x000D, version=0x1),
    "cache_id_decoder": CapabilityInfo(id=0x000E, version=0x1),
    "extended_hdm_decoder": CapabilityInfo(id=0x000F, version=0x3),
}


class CxlCapabilityIDToName:
    map: dict[int, str] = {
        v["id"]: k.replace("_", " ").title()
        for k, v in CAPABILITY_NAME_TO_CAPABILITY_INFO_MAP.items()
    }
    original_key_map: dict[int, str] = {
        v["id"]: k for k, v in CAPABILITY_NAME_TO_CAPABILITY_INFO_MAP.items()
    }

    @staticmethod
    def get(v: int) -> str:
        return CxlCapabilityIDToName.map[v]

    @staticmethod
    def get_original_name(v: int) -> str:
        return CxlCapabilityIDToName.original_key_map[v]


class CxlCapabilityHeaderStructure(BitMaskedBitStructure):
    header: CxlCapabilityHeaderRegister

    def __init__(
        self,
        data: Optional[ShareableByteArray] = None,
        parent_name: Optional[str] = None,
        options: Optional[CxlCapabilityHeaderStructureOptions] = None,
    ):
        added_fields: List[StructureField] = []
        if options:
            start = 4
            end = 7
            for key, pointer in options.items():
                if key not in CAPABILITY_NAME_TO_CAPABILITY_INFO_MAP:
                    raise Exception(f"Undefined capability {key}")
                id = CAPABILITY_NAME_TO_CAPABILITY_INFO_MAP[key]["id"]
                version = CAPABILITY_NAME_TO_CAPABILITY_INFO_MAP[key]["version"]
                item_options: CxlCapabilityItemHeaderOptions = {
                    "id": id,
                    "version": version,
                    "pointer": pointer,
                }
                added_fields.append(
                    StructureField(key, start, end, CxlCapabilityItemHeader, options=item_options)
                )
                start += 4
                end += 4

        header_options: CxlCapabilityHeaderRegisterOptions = {"size": len(added_fields)}
        self._fields = [
            StructureField("header", 0, 3, CxlCapabilityHeaderRegister, options=header_options)
        ]
        self._fields += added_fields

        super().__init__(data, parent_name)

    @staticmethod
    def get_size(fields=None, options: Optional[CxlCapabilityHeaderStructureOptions] = None):
        size = 4
        if options:
            size += len(options.keys()) * 4
        return size
