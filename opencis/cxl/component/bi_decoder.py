"""
Copyright (c) 2024, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

# pylint: disable=duplicate-code
from enum import IntEnum
from typing import TypedDict, Optional
from opencis.cxl.component.common import CXL_COMPONENT_TYPE
from opencis.util.unaligned_bit_structure import (
    BitMaskedBitStructure,
    BitField,
    StructureField,
    FIELD_ATTR,
    ShareableByteArray,
)


class CxlBITimeoutScale(IntEnum):
    one_us = 0b0000
    ten_us = 0b0001
    hundred_us = 0b0010
    one_ms = 0b0011
    ten_ms = 0b0100
    hundred_ms = 0b0101
    one_s = 0b0110
    ten_s = 0b0111


# BI Route Table
class CxlBIRTCapabilityRegisterOptions(TypedDict):
    explicit_bi_decoder_commit_required: int


class CxlBIRTControlRegisterOptions(TypedDict):
    bi_rt_commit: int


class CxlBIRTStatusRegisterOptions(TypedDict):
    bi_rt_committed: int
    bi_rt_error_not_committed: int
    reserved1: int
    bi_rt_commit_timeout_scale: CxlBITimeoutScale
    bi_rt_commit_timeout_base: int
    reserved2: int


class CxlBIRTCapabilityStructureOptions(TypedDict):
    capability_options: CxlBIRTCapabilityRegisterOptions
    control_options: CxlBIRTControlRegisterOptions
    status_options: CxlBIRTStatusRegisterOptions
    device_type: CXL_COMPONENT_TYPE


class CxlBIRTCapabilityRegister(BitMaskedBitStructure):
    explicit_bi_rt_commit_required: int

    def __init__(
        self,
        data: Optional[ShareableByteArray] = None,
        parent_name: Optional[str] = None,
        options: Optional[CxlBIRTCapabilityStructureOptions] = None,
    ):

        options = options["capability_options"]
        explicit_bi_rt_commit_required = options["explicit_bi_rt_commit_required"]

        self._fields = [
            BitField(
                "explicit_bi_rt_commit_required",
                0,
                0,
                FIELD_ATTR.HW_INIT,
                default=explicit_bi_rt_commit_required,
            ),
            BitField("reserved", 1, 31, FIELD_ATTR.RESERVED),
        ]

        super().__init__(data, parent_name)


class CxlBIRTControlRegister(BitMaskedBitStructure):
    bi_rt_commit: int
    rsvd: int
    device_type: CXL_COMPONENT_TYPE

    def __init__(
        self,
        data: Optional[ShareableByteArray] = None,
        parent_name: Optional[str] = None,
        options: Optional[CxlBIRTCapabilityStructureOptions] = None,
    ):

        explicit_bi_rt_commit_required = options["capability_options"][
            "explicit_bi_rt_commit_required"
        ]
        options = options["control_options"]
        bi_rt_commit = 0
        if "bi_rt_commit" in options and explicit_bi_rt_commit_required:
            bi_rt_commit = options["bi_rt_commit"]

        bi_rt_commit_attr = (
            FIELD_ATTR.RESERVED if explicit_bi_rt_commit_required == 0 else FIELD_ATTR.RW
        )

        self._fields = [
            BitField("bi_rt_commit", 0, 0, bi_rt_commit_attr, default=bi_rt_commit),
            BitField("reserved", 1, 31, FIELD_ATTR.RESERVED),
        ]

        super().__init__(data, parent_name)


class CxlBIRTStatusRegister(BitMaskedBitStructure):
    bi_rt_committed: int
    bi_rt_error_not_committed: int
    reserved1: int
    bi_rt_commit_timeout_scale: CxlBITimeoutScale
    bi_rt_commit_timeout_base: int
    reserved2: int

    def __init__(
        self,
        data: Optional[ShareableByteArray] = None,
        parent_name: Optional[str] = None,
        options: Optional[CxlBIRTCapabilityStructureOptions] = None,
    ):

        explicit_bi_rt_commit_required = options["capability_options"][
            "explicit_bi_rt_commit_required"
        ]
        options = options["status_options"]
        bi_rt_committed = options["bi_rt_committed"]
        bi_rt_error_not_committed = options["bi_rt_error_not_committed"]
        bi_rt_commit_timeout_scale = options["bi_rt_commit_timeout_scale"]
        bi_rt_commit_timeout_base = options["bi_rt_commit_timeout_base"]

        bi_rt_commit_attr = (
            FIELD_ATTR.RESERVED if explicit_bi_rt_commit_required == 0 else FIELD_ATTR.RO
        )

        self._fields = [
            BitField("bi_rt_committed", 0, 0, bi_rt_commit_attr, default=bi_rt_committed),
            BitField(
                "bi_rt_error_not_committed",
                1,
                1,
                bi_rt_commit_attr,
                default=bi_rt_error_not_committed,
            ),
            BitField("reserved1", 2, 7, FIELD_ATTR.RESERVED),
            BitField(
                "bi_rt_commit_timeout_scale",
                8,
                11,
                FIELD_ATTR.HW_INIT,
                default=bi_rt_commit_timeout_scale,
            ),
            BitField(
                "bi_rt_commit_timeout_base",
                12,
                15,
                FIELD_ATTR.HW_INIT,
                default=bi_rt_commit_timeout_base,
            ),
            BitField("reserved2", 16, 31, FIELD_ATTR.RESERVED),
        ]

        super().__init__(data, parent_name)


class CxlBIRTCapabilityStructure(BitMaskedBitStructure):

    def __init__(
        self,
        data: Optional[ShareableByteArray] = None,
        parent_name: Optional[str] = None,
        options: Optional[CxlBIRTCapabilityStructureOptions] = None,
    ):
        if not options:
            raise Exception("options is required")
        self._init_global(options)

        super().__init__(data, parent_name)

    def _init_global(self, options: CxlBIRTCapabilityStructureOptions):

        self._fields = [
            StructureField(
                "capability",
                0,
                3,
                CxlBIRTCapabilityRegister,
                options=options,
            ),
            StructureField(
                "control",
                4,
                7,
                CxlBIRTControlRegister,
                options=options,
            ),
            StructureField(
                "status",
                8,
                11,
                CxlBIRTStatusRegister,
                options=options,
            ),
        ]

    @staticmethod
    def get_size_from_options(
        options: Optional[CxlBIRTCapabilityStructureOptions] = None,
    ):
        return 0x0C


# BI Decoder
class CxlBIDecoderCapabilityRegisterOptions(TypedDict):
    hdm_d_compatible: int
    explicit_bi_decoder_commit_required: int


class CxlBIDecoderControlRegisterOptions(TypedDict):
    bi_forward: int
    bi_enable: int
    bi_decoder_commit: int


class CxlBIDecoderStatusRegisterOptions(TypedDict):
    bi_decoder_committed: int
    bi_decoder_error_not_committed: int
    reserved1: int
    bi_decoder_commit_timeout_scale: CxlBITimeoutScale
    bi_decoder_commit_timeout_base: int
    reserved2: int


class CxlBIDecoderCapabilityStructureOptions(TypedDict):
    capability_options: CxlBIDecoderCapabilityRegisterOptions
    control_options: CxlBIDecoderControlRegisterOptions
    status_options: CxlBIDecoderStatusRegisterOptions
    device_type: CXL_COMPONENT_TYPE


class CxlBIDecoderCapabilityRegister(BitMaskedBitStructure):
    hdm_d_compatible: int
    explicit_bi_decoder_commit_required: int

    def __init__(
        self,
        data: Optional[ShareableByteArray] = None,
        parent_name: Optional[str] = None,
        options: Optional[CxlBIDecoderCapabilityStructureOptions] = None,
    ):

        device_type = options["device_type"]
        options = options["capability_options"]
        hdm_d_compatible = 0
        explicit_bi_decoder_commit_required = 0

        if device_type not in (CXL_COMPONENT_TYPE.DSP, CXL_COMPONENT_TYPE.R):
            hdm_d_compatible = options["hdm_d_compatible"]
        if device_type not in (CXL_COMPONENT_TYPE.D2, CXL_COMPONENT_TYPE.R):
            explicit_bi_decoder_commit_required = options["explicit_bi_decoder_commit_required"]
        self._fields = [
            BitField(
                "hdm_d_compatible",
                0,
                0,
                (
                    FIELD_ATTR.RESERVED
                    if device_type in (CXL_COMPONENT_TYPE.DSP, CXL_COMPONENT_TYPE.R)
                    else FIELD_ATTR.HW_INIT
                ),
                default=hdm_d_compatible,
            ),
            BitField(
                "explicit_bi_decoder_commit_required",
                1,
                1,
                (
                    FIELD_ATTR.RESERVED
                    if device_type in (CXL_COMPONENT_TYPE.D2, CXL_COMPONENT_TYPE.R)
                    else FIELD_ATTR.HW_INIT
                ),
                default=explicit_bi_decoder_commit_required,
            ),
            BitField("reserved", 2, 31, FIELD_ATTR.RESERVED),
        ]

        super().__init__(data, parent_name)


class CxlBIDecoderControlRegister(BitMaskedBitStructure):
    bi_forward: int
    bi_enable: int
    bi_decoder_commit: int
    rsvd: int
    device_type: CXL_COMPONENT_TYPE

    def __init__(
        self,
        data: Optional[ShareableByteArray] = None,
        parent_name: Optional[str] = None,
        options: Optional[CxlBIDecoderCapabilityStructureOptions] = None,
    ):

        device_type = options["device_type"]
        explicit_bi_decoder_commit_required = 0
        if device_type not in (CXL_COMPONENT_TYPE.D2, CXL_COMPONENT_TYPE.R):
            explicit_bi_decoder_commit_required = options["capability_options"][
                "explicit_bi_decoder_commit_required"
            ]
        options = options["control_options"]
        bi_forward = 0
        if device_type != CXL_COMPONENT_TYPE.D2:
            bi_forward = options["bi_forward"]
        bi_enable = options["bi_enable"]
        bi_decoder_commit = options["bi_decoder_commit"]

        bi_forward_attr = (
            FIELD_ATTR.RESERVED if device_type == CXL_COMPONENT_TYPE.D2 else FIELD_ATTR.RW
        )

        bi_decoder_commit_attr = (
            FIELD_ATTR.RESERVED if explicit_bi_decoder_commit_required == 0 else FIELD_ATTR.RW
        )

        self._fields = [
            BitField("bi_forward", 0, 0, bi_forward_attr, default=bi_forward),
            BitField("bi_enable", 1, 1, FIELD_ATTR.RW, default=bi_enable),
            BitField("bi_decoder_commit", 2, 2, bi_decoder_commit_attr, default=bi_decoder_commit),
            BitField("reserved", 3, 31, FIELD_ATTR.RESERVED),
        ]

        super().__init__(data, parent_name)


class CxlBIDecoderStatusRegister(BitMaskedBitStructure):
    bi_decoder_committed: int
    bi_decoder_error_not_committed: int
    reserved1: int
    bi_decoder_commit_timeout_scale: CxlBITimeoutScale
    bi_decoder_commit_timeout_base: int
    reserved2: int

    def __init__(
        self,
        data: Optional[ShareableByteArray] = None,
        parent_name: Optional[str] = None,
        options: Optional[CxlBIDecoderCapabilityStructureOptions] = None,
    ):

        options = options["status_options"]
        bi_decoder_committed = options["bi_decoder_committed"]
        bi_decoder_error_not_committed = options["bi_decoder_error_not_committed"]
        bi_decoder_commit_timeout_scale = options["bi_decoder_commit_timeout_scale"]
        bi_decoder_commit_timeout_base = options["bi_decoder_commit_timeout_base"]

        self._fields = [
            BitField("bi_decoder_committed", 0, 0, FIELD_ATTR.RO, default=bi_decoder_committed),
            BitField(
                "bi_decoder_error_not_committed",
                1,
                1,
                FIELD_ATTR.RO,
                default=bi_decoder_error_not_committed,
            ),
            BitField("reserved1", 2, 7, FIELD_ATTR.RESERVED),
            BitField(
                "bi_decoder_commit_timeout_scale",
                8,
                11,
                FIELD_ATTR.HW_INIT,
                default=bi_decoder_commit_timeout_scale,
            ),
            BitField(
                "bi_decoder_commit_timeout_base",
                12,
                15,
                FIELD_ATTR.HW_INIT,
                default=bi_decoder_commit_timeout_base,
            ),
            BitField("reserved2", 16, 31, FIELD_ATTR.RESERVED),
        ]

        super().__init__(data, parent_name)


class CxlBIDecoderCapabilityStructure(BitMaskedBitStructure):

    def __init__(
        self,
        data: Optional[ShareableByteArray] = None,
        parent_name: Optional[str] = None,
        options: Optional[CxlBIDecoderCapabilityStructureOptions] = None,
    ):
        if not options:
            raise Exception("options is required")
        self._init_global(options)

        super().__init__(data, parent_name)

    def _init_global(self, options: CxlBIDecoderCapabilityStructureOptions):

        self._fields = [
            StructureField(
                "capability",
                0,
                3,
                CxlBIDecoderCapabilityRegister,
                options=options,
            ),
            StructureField(
                "control",
                4,
                7,
                CxlBIDecoderControlRegister,
                options=options,
            ),
            StructureField(
                "status",
                8,
                11,
                CxlBIDecoderStatusRegister,
                options=options,
            ),
        ]

    @staticmethod
    def get_size_from_options(
        options: Optional[CxlBIDecoderCapabilityStructureOptions] = None,
    ):
        return 0x0C
