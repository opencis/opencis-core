"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

SystemHeader = [
    ("payload_type", 0, 4),
    ("payload_length", 4, 12),
]

SidebandHeader = [
    ("type", 0, 8),
]

TlpPrefix = [
    ("pcie_base_spec_defined", 0, 8),
    ("ld_id", 8, 16),
    ("reserved", 24, 8),
]

CxlIoHeader = [
    ("fmt_type", 0, 8),
    ("th", 8, 1),
    ("rsvd", 9, 1),
    ("attr_b2", 10, 1),
    ("t8", 11, 1),
    ("tc", 12, 3),
    ("t9", 15, 1),
    ("length_upper", 16, 2),
    ("at", 18, 2),
    ("attr", 20, 2),
    ("ep", 22, 1),
    ("td", 23, 1),
    ("length_lower", 24, 8),
]

CxlIoMReqHeader = [
    ("req_id", 0, 16),
    ("tag", 16, 8),
    ("first_dw_be", 24, 4),
    ("last_dw_be", 28, 4),
    ("addr_upper", 32, 56),
    ("rsvd", 88, 2),
    ("addr_lower", 90, 6),
]

CxlIoCfgReqHeader = [
    ("req_id", 0, 16),
    ("tag", 16, 8),
    ("first_dw_be", 24, 4),
    ("last_dw_be", 28, 4),
    ("dest_id", 32, 16),
    ("ext_reg_num", 48, 4),
    ("rsvd", 52, 4),
    ("r", 56, 2),
    ("reg_num", 58, 6),
]

CxlIoCompletionHeader = [
    ("cpl_id", 0, 16),
    ("byte_count_upper", 16, 4),
    ("bcm", 20, 1),
    ("status", 21, 3),
    ("byte_count_lower", 24, 8),
    ("req_id", 32, 16),
    ("tag", 48, 8),
    ("lower_addr", 56, 7),
    ("rsvd", 63, 1),
]

CxlCacheHeader = [
    ("port_index", 0, 8),
    ("msg_class", 8, 8),
]

CxlCacheD2HReqHeader = [
    ("valid", 0, 1),
    ("cache_opcode", 1, 5),
    ("cqid", 6, 12),
    ("nt", 18, 1),
    ("cache_id", 19, 4),
    ("addr", 23, 46),
    ("rsvd", 69, 3),
]

CxlCacheD2HRspHeader = [
    ("valid", 0, 1),
    ("cache_opcode", 1, 5),
    ("uqid", 6, 12),
    ("rsvd", 18, 6),
]

CxlCacheD2HDataHeader = [
    ("valid", 0, 1),
    ("uqid", 1, 12),
    ("bogus", 13, 1),
    ("poison", 14, 1),
    ("bep", 15, 1),
    ("rsvd", 16, 8),
]

CxlCacheH2DReqHeader = [
    ("valid", 0, 1),
    ("cache_opcode", 1, 3),
    ("addr", 4, 46),
    ("uqid", 50, 12),
    ("cache_id", 62, 4),
    ("rsvd", 66, 6),
]

CxlCacheH2DRspHeader = [
    ("valid", 0, 1),
    ("cache_opcode", 1, 4),
    ("rsp_data", 5, 12),
    ("rsp_pre", 17, 2),
    ("cqid", 19, 12),
    ("cache_id", 31, 4),
    ("rsvd", 35, 5),
]

CxlCacheH2DDataHeader = [
    ("valid", 0, 1),
    ("cqid", 1, 12),
    ("poison", 13, 1),
    ("go_err", 14, 1),
    ("cache_id", 15, 4),
    ("rsvd", 19, 5),
]

CxlMemHeader = [
    ("port_index", 0, 8),
    ("msg_class", 8, 8),
]

CxlMemM2SReqHeader = [
    ("valid", 0, 1),
    ("mem_opcode", 1, 4),
    ("snp_type", 5, 3),
    ("meta_field", 8, 2),
    ("meta_value", 10, 2),
    ("tag", 12, 16),
    ("addr", 28, 46),
    ("ld_id", 74, 4),
    ("rsvd", 78, 20),
    ("tc", 98, 2),
    ("padding", 100, 4),
]

CxlMemM2SRwDHeader = [
    ("valid", 0, 1),
    ("mem_opcode", 1, 4),
    ("snp_type", 5, 3),
    ("meta_field", 8, 2),
    ("meta_value", 10, 2),
    ("tag", 12, 16),
    ("addr", 28, 46),
    ("poison", 74, 1),
    ("bep", 75, 1),
    ("ld_id", 76, 4),
    ("rsvd", 80, 22),
    ("tc", 102, 2),
]

CxlMemM2SBIRspHeader = [
    ("valid", 0, 1),
    ("opcode", 1, 4),
    ("bi_id", 5, 12),
    ("bi_tag", 17, 12),
    ("low_addr", 29, 2),
    ("rsvd", 31, 9),
]

CxlMemS2MBISnpHeader = [
    ("valid", 0, 1),
    ("opcode", 1, 4),
    ("bi_id", 5, 12),
    ("bi_tag", 17, 12),
    ("addr", 29, 46),
    ("rsvd", 75, 5),
]

CxlMemS2MNDRHeader = [
    ("valid", 0, 1),
    ("opcode", 1, 3),
    ("meta_field", 4, 2),
    ("meta_value", 6, 2),
    ("tag", 8, 16),
    ("ld_id", 24, 4),
    ("dev_load", 28, 2),
    ("rsvd", 30, 10),
]

CxlMemS2MDRSHeader = [
    ("valid", 0, 1),
    ("opcode", 1, 3),
    ("meta_field", 4, 2),
    ("meta_value", 6, 2),
    ("tag", 8, 16),
    ("poison", 24, 1),
    ("ld_id", 25, 4),
    ("dev_load", 29, 2),
    ("rsvd", 31, 9),
]

CciHeader = [
    ("port_index", 0, 8),
    ("msg_class", 8, 8),
]

CciMessageHeader = [
    ("message_category", 0, 4),
    ("reserved0", 4, 4),
    ("message_tag", 8, 8),
    ("reserved1", 16, 8),
    ("command_opcode", 24, 16),
    ("message_payload_length_low", 40, 16),
    ("message_payload_length_high", 56, 5),
    ("reserved2", 61, 2),
    ("background_operation", 63, 1),
    ("return_code", 64, 16),
    ("vendor_specific_extended_status", 80, 16),
]
