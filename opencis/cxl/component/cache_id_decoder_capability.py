"""
Copyright (c) 2024, Eeum, Inc.
This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from typing import Optional, TypedDict

from opencis.util.unaligned_bit_structure import (
    FIELD_ATTR,
    BitMaskedBitStructure,
    BitField,
    ShareableByteArray,
    StructureField,
)


class CxlCacheIdDecoderCapabilityRegisterOptions(TypedDict):
    explicit_cache_id_decoder_cmt_required: int
    rsvd: int


class CxlCacheIdDecoderControlOptions(TypedDict):
    forward_cache_id: int
    assign_cache_id: int
    hdmd_t2_device_present: int
    cache_id_decoder_cmt: int
    rsvd: int
    hdmd_t2_device_cache_id: int
    rsvd2: int
    local_cache_id: int
    rsvd3: int


class CxlCacheIdDecoderStatusOptions(TypedDict):
    cache_id_decoder_cmtd: int
    cache_id_decoder_err_not_cmtd: int
    rsvd: int
    cache_id_decoder_cmt_timeout_scale: int
    cache_id_decoder_cmt_timeout_base: int
    rsvd2: int


class CxlCacheIdDecoderCapabilityStructureOptions(TypedDict):
    register_options: CxlCacheIdDecoderCapabilityRegisterOptions
    control_options: CxlCacheIdDecoderControlOptions
    status_options: CxlCacheIdDecoderStatusOptions


class CxlCacheIdDecoderCapability(BitMaskedBitStructure):
    def __init__(
        self,
        data: Optional[ShareableByteArray] = None,
        parent_name: Optional[str] = None,
        options: Optional[CxlCacheIdDecoderCapabilityStructureOptions] = None,
    ):
        # pylint: disable=duplicate-code
        self._fields = [
            BitField("explicit_cache_id_decoder_cmt_required", 0, 0),
            BitField("rsvd", 1, 31),
        ]

        if data:
            super().__init__(data, parent_name)
            return

        super().__init__(parent_name=parent_name)
        for reg, val in options["register_options"].items():
            setattr(self, reg, val)


class CxlCacheIdDecoderControl(BitMaskedBitStructure):
    def __init__(
        self,
        data: Optional[ShareableByteArray] = None,
        parent_name: Optional[str] = None,
        options: Optional[CxlCacheIdDecoderCapabilityStructureOptions] = None,
    ):
        # pylint: disable=duplicate-code
        cache_id_decoder_cmt_attr: FIELD_ATTR
        if options["register_options"]["explicit_cache_id_decoder_cmt_required"]:
            cache_id_decoder_cmt_attr = FIELD_ATTR.RW
        else:
            cache_id_decoder_cmt_attr = FIELD_ATTR.RESERVED

        # Must be defined within the scope of __init__, since the attributes
        # of cache_id_decoder_cmt may differ between instances

        self._fields = [
            BitField("forward_cache_id", 0, 0, FIELD_ATTR.RW),
            BitField("assign_cache_id", 1, 1, FIELD_ATTR.RW),
            BitField("hdmd_t2_device_present", 2, 2, FIELD_ATTR.RW),
            BitField("cache_id_decoder_cmt", 3, 3, cache_id_decoder_cmt_attr),
            BitField("rsvd", 4, 7, FIELD_ATTR.RESERVED),
            BitField("hdmd_t2_device_cache_id", 8, 11, FIELD_ATTR.RW),
            BitField("rsvd2", 12, 15, FIELD_ATTR.RESERVED),
            BitField("local_cache_id", 16, 19, FIELD_ATTR.RW),
            BitField("rsvd3", 20, 31, FIELD_ATTR.RESERVED),
        ]

        if data:
            super().__init__(data, parent_name)
            return

        super().__init__(parent_name=parent_name)
        for reg, val in options["control_options"].items():
            setattr(self, reg, val)


class CxlCacheIdDecoderStatus(BitMaskedBitStructure):
    def __init__(
        self,
        data: Optional[ShareableByteArray] = None,
        parent_name: Optional[str] = None,
        options: Optional[CxlCacheIdDecoderCapabilityStructureOptions] = None,
    ):
        # pylint: disable=duplicate-code
        cache_id_decoder_cmt_attr: FIELD_ATTR
        if options["register_options"]["explicit_cache_id_decoder_cmt_required"]:
            cache_id_decoder_cmt_attr = FIELD_ATTR.RW
        else:
            cache_id_decoder_cmt_attr = FIELD_ATTR.RESERVED

        self._fields = [
            BitField("cache_id_decoder_cmtd", 0, 0, cache_id_decoder_cmt_attr),
            BitField("cache_id_decoder_err_not_cmtd", 1, 1, cache_id_decoder_cmt_attr),
            BitField("rsvd", 2, 7, FIELD_ATTR.RESERVED),
            BitField("cache_id_decoder_cmt_timeout_scale", 8, 11, cache_id_decoder_cmt_attr),
            BitField("cache_id_decoder_cmt_timeout_base", 12, 15, cache_id_decoder_cmt_attr),
            BitField("rsvd2", 16, 31, FIELD_ATTR.RESERVED),
        ]

        if data:
            super().__init__(data, parent_name)
            return

        super().__init__(parent_name=parent_name)
        for reg, val in options["status_options"].items():
            setattr(self, reg, val)


class CxlCacheIdDecoderCapabilityStructure(BitMaskedBitStructure):
    def __init__(
        self,
        data: Optional[ShareableByteArray] = None,
        parent_name: Optional[str] = None,
        options: Optional[CxlCacheIdDecoderCapabilityStructureOptions] = None,
    ):
        # pylint: disable=duplicate-code
        if not options:
            raise ValueError("options is required")
        self._init_global(options)

        super().__init__(data, parent_name)

    def _init_global(self, options: CxlCacheIdDecoderCapabilityStructureOptions):
        self._fields = [
            StructureField(
                "cxl_cache_id_decoder_capability",
                0x00,
                0x03,
                CxlCacheIdDecoderCapability,
                options=options,
            ),
            StructureField(
                "cxl_cache_id_decoder_control",
                0x04,
                0x07,
                CxlCacheIdDecoderControl,
                options=options,
            ),
            StructureField(
                "cxl_cache_id_decoder_status", 0x08, 0x11, CxlCacheIdDecoderStatus, options=options
            ),
        ]

    @staticmethod
    def get_size_from_options(options: Optional[CxlCacheIdDecoderCapabilityStructureOptions]):
        return 0x12
