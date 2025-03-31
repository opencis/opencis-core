"""
Copyright (c) 2024, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from opencis.util.unaligned_bit_structure import (
    BitMaskedBitStructure,
    BitField,
    ByteField,
    StructureField,
    FIELD_ATTR,
)

# NOTE: CXL RAS Capability is implemented as a dummy


class UncorrectableErrorStatusRegister(BitMaskedBitStructure):
    _fields = [
        BitField("cache_data_parity", 0, 0, FIELD_ATTR.RW1CS),
        BitField("cache_address_parity", 1, 1, FIELD_ATTR.RW1CS),
        BitField("cache_be_parity", 2, 2, FIELD_ATTR.RW1CS),
        BitField("cache_data_ecc", 3, 3, FIELD_ATTR.RW1CS),
        BitField("mem_data_parity", 4, 4, FIELD_ATTR.RW1CS),
        BitField("mem_address_parity", 5, 5, FIELD_ATTR.RW1CS),
        BitField("mem_be_parity", 6, 6, FIELD_ATTR.RW1CS),
        BitField("mem_data_ecc", 7, 7, FIELD_ATTR.RW1CS),
        BitField("reinit_threshold", 8, 8, FIELD_ATTR.RW1CS),
        BitField("rsvd_encoding_violation", 9, 9, FIELD_ATTR.RW1CS),
        BitField("poison_received", 10, 10, FIELD_ATTR.RW1CS),
        BitField("receiver_overflow", 11, 11, FIELD_ATTR.RW1CS),
        BitField("reserved1", 12, 13, FIELD_ATTR.RESERVED),
        BitField("intenral_error", 14, 14, FIELD_ATTR.RW1CS),
        BitField("cxl_ide_tx_error", 15, 15, FIELD_ATTR.RW1CS),
        BitField("cxl_ide_rx_error", 16, 16, FIELD_ATTR.RW1CS),
        BitField("reserved2", 17, 31, FIELD_ATTR.RESERVED),
    ]


class UncorrectableErrorMaskRegister(BitMaskedBitStructure):
    _fields = [
        BitField("cache_data_parity_mask", 0, 0, FIELD_ATTR.RWS),
        BitField("cache_address_parity_mask", 1, 1, FIELD_ATTR.RWS),
        BitField("cache_be_parity_mask", 2, 2, FIELD_ATTR.RWS),
        BitField("cache_data_ecc_mask", 3, 3, FIELD_ATTR.RWS),
        BitField("mem_data_parity_mask", 4, 4, FIELD_ATTR.RWS),
        BitField("mem_address_parity_mask", 5, 5, FIELD_ATTR.RWS),
        BitField("mem_be_parity_mask", 6, 6, FIELD_ATTR.RWS),
        BitField("mem_data_ecc_mask", 7, 7, FIELD_ATTR.RWS),
        BitField("reinit_threshold_mask", 8, 8, FIELD_ATTR.RWS),
        BitField("rsvd_encoding_violation_mask", 9, 9, FIELD_ATTR.RWS),
        BitField("poison_received_mask", 10, 10, FIELD_ATTR.RWS),
        BitField("receiver_overflow_mask", 11, 11, FIELD_ATTR.RWS),
        BitField("reserved1", 12, 13, FIELD_ATTR.RESERVED),
        BitField("intenral_error_mask", 14, 14, FIELD_ATTR.RWS),
        BitField("cxl_ide_tx_error_mask", 15, 15, FIELD_ATTR.RWS),
        BitField("cxl_ide_rx_error_mask", 16, 16, FIELD_ATTR.RWS),
        BitField("reserved2", 17, 31, FIELD_ATTR.RESERVED),
    ]


class UncorrectableErrorSeverityRegister(BitMaskedBitStructure):
    _fields = [
        BitField("cache_data_parity_severity", 0, 0, FIELD_ATTR.RWS),
        BitField("cache_address_parity_severity", 1, 1, FIELD_ATTR.RWS),
        BitField("cache_be_parity_severity", 2, 2, FIELD_ATTR.RWS),
        BitField("cache_data_ecc_severity", 3, 3, FIELD_ATTR.RWS),
        BitField("mem_data_parity_severity", 4, 4, FIELD_ATTR.RWS),
        BitField("mem_address_parity_severity", 5, 5, FIELD_ATTR.RWS),
        BitField("mem_be_parity_severity", 6, 6, FIELD_ATTR.RWS),
        BitField("mem_data_ecc_severity", 7, 7, FIELD_ATTR.RWS),
        BitField("reinit_threshold_severity", 8, 8, FIELD_ATTR.RWS),
        BitField("rsvd_encoding_violation_severity", 9, 9, FIELD_ATTR.RWS),
        BitField("poison_received_severity", 10, 10, FIELD_ATTR.RWS),
        BitField("receiver_overflow_severity", 11, 11, FIELD_ATTR.RWS),
        BitField("reserved1", 12, 13, FIELD_ATTR.RESERVED),
        BitField("intenral_error_severity", 14, 14, FIELD_ATTR.RWS),
        BitField("cxl_ide_tx_error_severity", 15, 15, FIELD_ATTR.RWS),
        BitField("cxl_ide_rx_error_severity", 16, 16, FIELD_ATTR.RWS),
        BitField("reserved2", 17, 31, FIELD_ATTR.RESERVED),
    ]


class CorrectableErrorStatusRegister(BitMaskedBitStructure):
    _fields = [
        BitField("cache_data_ecc", 0, 0, FIELD_ATTR.RW1CS),
        BitField("mem_data_ecc", 1, 1, FIELD_ATTR.RW1CS),
        BitField("crc_threshold", 2, 2, FIELD_ATTR.RW1CS),
        BitField("retry_threshold", 3, 3, FIELD_ATTR.RW1CS),
        BitField("cache_poison_received", 4, 4, FIELD_ATTR.RW1CS),
        BitField("mem_poison_received", 5, 5, FIELD_ATTR.RW1CS),
        BitField("physical_layer_error", 6, 6, FIELD_ATTR.RW1CS),
        BitField("reserved1", 7, 31, FIELD_ATTR.RESERVED),
    ]


class CorrectableErrorMaskRegister(BitMaskedBitStructure):
    _fields = [
        BitField("cache_data_ecc_mask", 0, 0, FIELD_ATTR.RWS),
        BitField("mem_data_ecc_mask", 1, 1, FIELD_ATTR.RWS),
        BitField("crc_threshold_mask", 2, 2, FIELD_ATTR.RWS),
        BitField("retry_threshold_mask", 3, 3, FIELD_ATTR.RWS),
        BitField("cache_poison_received_mask", 4, 4, FIELD_ATTR.RWS),
        BitField("mem_poison_received_mask", 5, 5, FIELD_ATTR.RWS),
        BitField("physical_layer_error_mask", 6, 6, FIELD_ATTR.RWS),
        BitField("reserved1", 7, 31, FIELD_ATTR.RESERVED),
    ]


class ErrorCapabilitiesAndControlRegister(BitMaskedBitStructure):
    _fields = [
        BitField("first_error_pointer", 0, 5, FIELD_ATTR.ROS),
        BitField("reserved1", 6, 8, FIELD_ATTR.RESERVED),
        BitField("multiple_header_recording_capability", 9, 9, FIELD_ATTR.RO),
        BitField("reserved2", 10, 12, FIELD_ATTR.RESERVED),
        BitField("poison_enabled", 13, 13, FIELD_ATTR.RWS),
        BitField("reserved3", 14, 31, FIELD_ATTR.RESERVED),
    ]


class HeaderLogRegisters(BitMaskedBitStructure):
    _fields = [
        BitField("header_log", 0, 511, FIELD_ATTR.ROS),
    ]


class CxlRasCapabilityStructure(BitMaskedBitStructure):
    _fields = [
        StructureField("uncorrectable_error_status", 0x00, 0x03, UncorrectableErrorStatusRegister),
        StructureField("uncorrectable_error_mask", 0x04, 0x07, UncorrectableErrorMaskRegister),
        StructureField(
            "uncorrectable_error_severity",
            0x08,
            0x0B,
            UncorrectableErrorSeverityRegister,
        ),
        StructureField("correctable_error_status", 0x0C, 0x0F, CorrectableErrorStatusRegister),
        StructureField("correctable_error_mask", 0x10, 0x13, CorrectableErrorMaskRegister),
        StructureField(
            "error_capability_and_control",
            0x14,
            0x17,
            ErrorCapabilitiesAndControlRegister,
        ),
        StructureField("header_log", 0x18, 0x57, HeaderLogRegisters),
        ByteField("reserved1", 0x58, 0x5F, attribute=FIELD_ATTR.RESERVED),
    ]
