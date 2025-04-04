"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from typing import Dict, Optional, TypedDict

from opencis.util.unaligned_bit_structure import (
    ShareableByteArray,
    BitMaskedBitStructure,
    StructureField,
    ByteField,
    FIELD_ATTR,
)
from opencis.cxl.mmio.component_register.memcache_register import (
    CxlCacheMemRegister,
    CxlCacheMemRegisterOptions,
)
from opencis.cxl.component.bi_decoder import (
    CxlBIDecoderCapabilityRegisterOptions,
    CxlBIDecoderControlRegisterOptions,
    CxlBIDecoderStatusRegisterOptions,
)
from opencis.cxl.component.cxl_component import CxlComponent

CXL_COMPONENT_REGISTER_SIZE = 0x10000


class CxlComponentRegisterOptions(TypedDict):
    cxl_component: CxlComponent


class CxlComponentRegister(BitMaskedBitStructure):
    def __init__(
        self,
        data: Optional[ShareableByteArray] = None,
        parent_name: Optional[str] = None,
        options: Optional[CxlComponentRegisterOptions] = None,
    ):
        if not options:
            raise Exception("options is required")

        cxl_component = options["cxl_component"]
        cachemem_options = CxlCacheMemRegisterOptions()
        if cxl_component.get_hdm_decoder_manager():
            cachemem_options["hdm_decoder"] = {
                "hdm_decoder_manager": cxl_component.get_hdm_decoder_manager()
            }

        cachemem_options["link"] = True
        cachemem_options["ras"] = True
        if cxl_component.get_bi_decoder_options():
            cachemem_options["bi_decoder"] = cxl_component.get_bi_decoder_options()
        if cxl_component.get_bi_rt_options():
            cachemem_options["bi_route_table"] = cxl_component.get_bi_rt_options()

        self._fields = [
            ByteField("io", 0x0000, 0x0FFF, attribute=FIELD_ATTR.RESERVED),
            StructureField(
                "cachemem",
                0x1000,
                0x1FFF,
                CxlCacheMemRegister,
                options=cachemem_options,
            ),
            ByteField("cachemem_ext", 0x2000, 0xDFFF, attribute=FIELD_ATTR.RESERVED),
            ByteField("arb_mux", 0xE000, 0xE3FF, attribute=FIELD_ATTR.RESERVED),
            ByteField("reserved1", 0xE400, 0xFFFF, attribute=FIELD_ATTR.RESERVED),
        ]

        super().__init__(data, parent_name)

    @staticmethod
    def get_size_from_options(options: Optional[Dict] = None) -> int:
        return CXL_COMPONENT_REGISTER_SIZE
