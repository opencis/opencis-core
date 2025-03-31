"""
Copyright (c) 2024, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from enum import IntEnum
from opencis.util.unaligned_bit_structure import (
    BitMaskedBitStructure,
    BitField,
    ByteField,
    StructureField,
    FIELD_ATTR,
)

# NOTE: CXL Link Capability Structure is implemented as a dummy


class CxlLinkLayerCapabilityRegister(BitMaskedBitStructure):
    _fields = [
        BitField("cxl_link_version_supported", 0, 3, FIELD_ATTR.RWS),
        BitField("cxl_link_version_received", 4, 7, FIELD_ATTR.RO),
        BitField("llr_wrap_value_supported", 8, 15, FIELD_ATTR.RWS),
        BitField("llr_wrap_value_received", 16, 23, FIELD_ATTR.RO),
        BitField("num_retry_received", 24, 28, FIELD_ATTR.RO),
        BitField("num_phy_reinit_received", 29, 33, FIELD_ATTR.RO),
        BitField("wr_ptr_received", 34, 41, FIELD_ATTR.RO),
        BitField("echo_eseq_received", 42, 49, FIELD_ATTR.RO),
        BitField("num_free_buf_received", 50, 57, FIELD_ATTR.RO),
        BitField("no_ll_reset_support", 58, 58, FIELD_ATTR.RO, 1),
        BitField("reserved1", 59, 63, FIELD_ATTR.RESERVED),
    ]


class CXL_LINK_LAYER_INIT_STATE(IntEnum):
    NOT_RDY_FOR_INIT = 0b00
    PARAM_EX = 0b01
    CRD_RETURN_STALL = 0b10
    INIT_DONE = 0b11


class CxlLinkLayerControlAndStatusRegister(BitMaskedBitStructure):
    _fields = [
        BitField("ll_reset", 0, 0, FIELD_ATTR.RW),
        BitField("ll_init_stall", 1, 1, FIELD_ATTR.RWS),
        BitField("ll_crd_stall", 2, 2, FIELD_ATTR.RWS),
        BitField("init_state", 3, 4, FIELD_ATTR.RO, CXL_LINK_LAYER_INIT_STATE.INIT_DONE),
        BitField("ll_retry_buffer_consumed", 5, 12, FIELD_ATTR.RO),
        BitField("reserved1", 13, 63, FIELD_ATTR.RESERVED),
    ]


class CxlLinkLayerRxCreditControlRegister(BitMaskedBitStructure):
    _fields = [
        BitField("cache_req_credits", 0, 9, FIELD_ATTR.RW),
        BitField("cache_rsp_credits", 10, 19, FIELD_ATTR.RWS),
        BitField("cache_data_credits", 20, 29, FIELD_ATTR.RWS),
        BitField("mem_req_rsp_credits", 30, 39, FIELD_ATTR.RW),
        BitField("mem_data_credits", 40, 49, FIELD_ATTR.RWS),
        BitField("bi_credits", 50, 59, FIELD_ATTR.RWS),
        BitField("reserved1", 60, 63, FIELD_ATTR.RESERVED),
    ]


class CxlLinkLayerRxCreditReturnStatusRegister(BitMaskedBitStructure):
    _fields = [
        BitField("cache_req_credits", 0, 9, FIELD_ATTR.RW),
        BitField("cache_rsp_credits", 10, 19, FIELD_ATTR.RWS),
        BitField("cache_data_credits", 20, 29, FIELD_ATTR.RWS),
        BitField("mem_req_rsp_credits", 30, 39, FIELD_ATTR.RW),
        BitField("mem_data_credits", 40, 49, FIELD_ATTR.RWS),
        BitField("bi_credits", 50, 59, FIELD_ATTR.RWS),
        BitField("reserved1", 60, 63, FIELD_ATTR.RESERVED),
    ]


class CxlLinkLayerTxCreditControlRegister(BitMaskedBitStructure):
    _fields = [
        BitField("cache_req_credits", 0, 9, FIELD_ATTR.RW),
        BitField("cache_rsp_credits", 10, 19, FIELD_ATTR.RWS),
        BitField("cache_data_credits", 20, 29, FIELD_ATTR.RWS),
        BitField("mem_req_rsp_credits", 30, 39, FIELD_ATTR.RW),
        BitField("mem_data_credits", 40, 49, FIELD_ATTR.RWS),
        BitField("bi_credits", 50, 59, FIELD_ATTR.RWS),
        BitField("reserved1", 60, 63, FIELD_ATTR.RESERVED),
    ]


class CxlLinkLayerAckTimerControlRegister(BitMaskedBitStructure):
    _fields = [
        BitField("ack_force_threshold", 0, 7, FIELD_ATTR.RWS),
        BitField("ack_or_crd_flush_retimer", 8, 17, FIELD_ATTR.RWS),
        BitField("reserved1", 18, 63, FIELD_ATTR.RESERVED),
    ]


class CxlLinkLayerDefeatureRegister(BitMaskedBitStructure):
    _fields = [
        BitField("mdh_disable", 0, 0, FIELD_ATTR.RWS),
        BitField("reserved1", 1, 63, FIELD_ATTR.RESERVED),
    ]


class CxlLinkCapabilityStructure(BitMaskedBitStructure):
    _fields = [
        StructureField("capability", 0x00, 0x07, CxlLinkLayerCapabilityRegister),
        StructureField("control_and_status", 0x08, 0x0F, CxlLinkLayerControlAndStatusRegister),
        StructureField("rx_credit_control", 0x10, 0x17, CxlLinkLayerRxCreditControlRegister),
        StructureField("rx_credit_return_status", 0x18, 0x1F, CxlLinkLayerRxCreditControlRegister),
        StructureField("tx_credit_status", 0x20, 0x27, CxlLinkLayerTxCreditControlRegister),
        StructureField("ack_timer_control", 0x28, 0x2F, CxlLinkLayerAckTimerControlRegister),
        StructureField("defeature", 0x30, 0x37, CxlLinkLayerRxCreditControlRegister),
        ByteField("reserved1", 0x38, 0x3F, attribute=FIELD_ATTR.RESERVED),
    ]
