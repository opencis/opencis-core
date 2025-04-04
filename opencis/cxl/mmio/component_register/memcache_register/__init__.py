"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from typing import TypedDict, Optional, Dict
from opencis.cxl.component.cache_route_table import (
    CxlCacheIdRTCapabilityStructure,
    CacheRouteTableCapabilityStructureOptions,
)
from opencis.cxl.component.cache_id_decoder_capability import (
    CxlCacheIdDecoderCapabilityStructure,
    CxlCacheIdDecoderCapabilityStructureOptions,
)
from opencis.util.unaligned_bit_structure import (
    ShareableByteArray,
    BitMaskedBitStructure,
    StructureField,
    ByteField,
    FIELD_ATTR,
)
from opencis.cxl.component.bi_decoder import (
    CxlBIDecoderCapabilityStructure,
    CxlBIDecoderCapabilityStructureOptions,
    CxlBIRTCapabilityStructure,
    CxlBIRTCapabilityStructureOptions,
)
from .capability import (
    CxlCapabilityHeaderStructure,
    CxlCapabilityHeaderStructureOptions,
)
from .hdm_decoder_capability import (
    CxlHdmDecoderCapabilityStructure,
    CxlHdmDecoderCapabilityStructureOptions,
)
from .link_capability import CxlLinkCapabilityStructure
from .ras_capability import CxlRasCapabilityStructure


class CxlCacheMemRegisterOptions(TypedDict):
    ras: Optional[bool]
    link: Optional[bool]
    hdm_decoder: Optional[CxlHdmDecoderCapabilityStructureOptions]
    bi_route_table: Optional[CxlBIRTCapabilityStructureOptions]
    bi_decoder: Optional[CxlBIDecoderCapabilityStructureOptions]
    cache_route_table: Optional[CacheRouteTableCapabilityStructureOptions]
    cache_id_decoder: Optional[CxlCacheIdDecoderCapabilityStructureOptions]


STRUCTURE_MAP: Dict[str, BitMaskedBitStructure] = {
    "ras": CxlRasCapabilityStructure,
    "link": CxlLinkCapabilityStructure,
    "hdm_decoder": CxlHdmDecoderCapabilityStructure,
    "bi_route_table": CxlBIRTCapabilityStructure,
    "bi_decoder": CxlBIDecoderCapabilityStructure,
    "cache_route_table": CxlCacheIdRTCapabilityStructure,  # just hardcode 4N for now
    "cache_id_decoder": CxlCacheIdDecoderCapabilityStructure,
}

CXL_CACHE_MEM_REGISTER_SIZE = 0x1000


class CxlCacheMemRegister(BitMaskedBitStructure):
    def __init__(
        self,
        data: Optional[ShareableByteArray] = None,
        parent_name: Optional[str] = None,
        options: Optional[CxlCacheMemRegisterOptions] = None,
    ):
        if not options:
            options = {}

        self._capability_options = CxlCapabilityHeaderStructureOptions()
        offset = self._add_capability_header(options)
        offset = self._add_capability_structures(offset, options)
        self._add_reserved(offset)

        super().__init__(data, parent_name)

    def _add_capability_header(self, options: CxlCacheMemRegisterOptions) -> int:
        for key, value in options.items():
            if value:
                self._capability_options[key] = 0

        capability_size = CxlCapabilityHeaderStructure.get_size(options=self._capability_options)
        offset = capability_size

        self._fields = [
            StructureField(
                "capability_header",
                0,
                capability_size - 1,
                CxlCapabilityHeaderStructure,
                options=self._capability_options,
            )
        ]

        return offset

    def _add_capability_structures(
        self,
        offset: int,
        options: CxlCacheMemRegisterOptions,
    ) -> int:
        for key in self._capability_options.keys():
            # NOTE: the offset of each structure is related to the beginning of
            # the CXL Capability Header Register based on CXL 3.0 specification
            # 8.2.4
            self._capability_options[key] = offset
            (structure_class, value) = CxlCacheMemRegister.get_class_and_value(options, key)
            if isinstance(value, bool):
                structure_size = structure_class.get_size()
                value = None
            elif isinstance(value, dict):
                structure_size = structure_class.get_size_from_options(value)
            else:
                raise Exception(f'Unexpected type for options["{key}"]')
            self._fields += [
                StructureField(
                    key,
                    offset + 0x00,
                    offset + structure_size - 1,
                    structure_class,
                    options=value,
                )
            ]
            offset += structure_size
        return offset

    def _add_reserved(self, offset: int):
        self._fields += [
            ByteField(
                "reserved",
                offset,
                CXL_CACHE_MEM_REGISTER_SIZE - 1,
                attribute=FIELD_ATTR.RESERVED,
            )
        ]

    @staticmethod
    def get_class_and_value(options: Optional[CxlCapabilityHeaderStructureOptions], key: str):
        value = options.get(key)
        if not value:
            raise Exception(f'Internal Error: options.get("{key}") should be truthy')

        structure_class = STRUCTURE_MAP.get(key)
        if not structure_class:
            raise Exception(f'"{key}" is not a valid option')

        return (structure_class, value)

    @staticmethod
    def get_size_from_options(options: Optional[Dict] = None):
        return CXL_CACHE_MEM_REGISTER_SIZE
