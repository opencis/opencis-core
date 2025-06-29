"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

PACKETS = {
    "BasePacket": {
        "layout": [
            ("SystemHeader", "system_header"),
        ],
        "create_args": {},
    },
    # Sideband
    "BaseSidebandPacket": {
        "layout": [
            ("SystemHeader", "system_header"),
            ("SidebandHeader", "sideband_header"),
        ],
        "create_args": {},
    },
    "SidebandConnectionRequestPacket": {
        "layout": [
            ("SystemHeader", "system_header"),
            ("SidebandHeader", "sideband_header"),
        ],
        "create_args": {},
    },
    # CXL.io
    "CxlIoBasePacket": {
        "layout": [
            ("SystemHeader", "system_header"),
            ("TlpPrefix", "tlp_prefix"),
            ("CxlIoHeader", "cxl_io_header"),
        ],
        "create_args": {},
    },
    "CxlIoMemRdPacket": {
        "layout": [
            ("SystemHeader", "system_header"),
            ("TlpPrefix", "tlp_prefix"),
            ("CxlIoHeader", "cxl_io_header"),
            ("CxlIoMReqHeader", "mreq_header"),
        ],
        "create_args": {
            "SystemHeader": ["payload_type"],
            "TlpPrefix": ["ld_id"],
            "CxlIoHeader": ["fmt_type", "length_upper", "length_lower"],
            "CxlIoMReqHeader": [
                "req_id",
                "tag",
                "first_dw_be",
                "last_dw_be",
                "addr_upper",
                "addr_lower",
            ],
        },
    },
    "CxlIoMemWrPacket": {
        "layout": [
            ("SystemHeader", "system_header"),
            ("TlpPrefix", "tlp_prefix"),
            ("CxlIoHeader", "cxl_io_header"),
            ("CxlIoMReqHeader", "mreq_header"),
        ],
        "create_args": {
            "SystemHeader": ["payload_type"],
            "TlpPrefix": ["ld_id"],
            "CxlIoHeader": ["fmt_type", "length_upper", "length_lower"],
            "CxlIoMReqHeader": [
                "req_id",
                "tag",
                "first_dw_be",
                "last_dw_be",
                "addr_upper",
                "addr_lower",
            ],
        },
    },
    "CxlIoCfgRdPacket": {
        "layout": [
            ("SystemHeader", "system_header"),
            ("TlpPrefix", "tlp_prefix"),
            ("CxlIoHeader", "cxl_io_header"),
            ("CxlIoCfgReqHeader", "cfg_req_header"),
        ],
        "create_args": {
            "SystemHeader": ["payload_type"],
            "TlpPrefix": ["ld_id"],
            "CxlIoHeader": ["fmt_type", "length_upper", "length_lower"],
            "CxlIoCfgReqHeader": [
                "req_id",
                "tag",
                "first_dw_be",
                "last_dw_be",
                "dest_id",
                "ext_reg_num",
                "reg_num",
            ],
        },
    },
    "CxlIoCfgWrPacket": {
        "layout": [
            ("SystemHeader", "system_header"),
            ("TlpPrefix", "tlp_prefix"),
            ("CxlIoHeader", "cxl_io_header"),
            ("CxlIoCfgReqHeader", "cfg_req_header"),
        ],
        "create_args": {
            "SystemHeader": ["payload_type"],
            "TlpPrefix": ["ld_id"],
            "CxlIoHeader": ["fmt_type", "length_upper", "length_lower"],
            "CxlIoCfgReqHeader": [
                "req_id",
                "tag",
                "first_dw_be",
                "last_dw_be",
                "dest_id",
                "ext_reg_num",
                "reg_num",
            ],
        },
    },
    "CxlIoCompletionPacket": {
        "layout": [
            ("SystemHeader", "system_header"),
            ("TlpPrefix", "tlp_prefix"),
            ("CxlIoHeader", "cxl_io_header"),
            ("CxlIoCompletionHeader", "cpl_header"),
        ],
        "create_args": {
            "SystemHeader": ["payload_type"],
            "TlpPrefix": ["ld_id"],
            "CxlIoHeader": ["fmt_type", "length_upper", "length_lower"],
            "CxlIoCompletionHeader": [
                "cpl_id",
                "status",
                "byte_count_upper",
                "byte_count_lower",
                "req_id",
                "tag",
            ],
        },
    },
    # CXL.cache
    "CxlCacheBasePacket": {
        "layout": [
            ("SystemHeader", "system_header"),
            ("CxlCacheHeader", "cxl_cache_header"),
        ],
        "create_args": {},
    },
    "CxlCacheD2HReqPacket": {
        "layout": [
            ("SystemHeader", "system_header"),
            ("CxlCacheHeader", "cxl_cache_header"),
            ("CxlCacheD2HReqHeader", "d2hreq_header"),
        ],
        "create_args": {
            "SystemHeader": ["payload_type"],
            "CxlCacheHeader": ["msg_class"],
            "CxlCacheD2HReqHeader": [
                "valid",
                "cache_opcode",
                "cqid",
                "cache_id",
                "addr",
            ],
        },
    },
    "CxlCacheD2HRspPacket": {
        "layout": [
            ("SystemHeader", "system_header"),
            ("CxlCacheHeader", "cxl_cache_header"),
            ("CxlCacheD2HRspHeader", "d2hrsp_header"),
        ],
        "create_args": {
            "SystemHeader": ["payload_type"],
            "CxlCacheHeader": ["msg_class"],
            "CxlCacheD2HRspHeader": [
                "valid",
                "uqid",
                "cache_opcode",
            ],
        },
    },
    "CxlCacheD2HDataPacket": {
        "layout": [
            ("SystemHeader", "system_header"),
            ("CxlCacheHeader", "cxl_cache_header"),
            ("CxlCacheD2HDataHeader", "d2hdata_header"),
        ],
        "create_args": {
            "SystemHeader": ["payload_type"],
            "CxlCacheHeader": ["msg_class"],
            "CxlCacheD2HDataHeader": [
                "valid",
                "uqid",
                "poison",
            ],
        },
    },
    "CxlCacheH2DReqPacket": {
        "layout": [
            ("SystemHeader", "system_header"),
            ("CxlCacheHeader", "cxl_cache_header"),
            ("CxlCacheH2DReqHeader", "h2dreq_header"),
        ],
        "create_args": {
            "SystemHeader": ["payload_type"],
            "CxlCacheHeader": ["msg_class"],
            "CxlCacheH2DReqHeader": [
                "valid",
                "cache_opcode",
                "cache_id",
                "addr",
            ],
        },
    },
    "CxlCacheH2DRspPacket": {
        "layout": [
            ("SystemHeader", "system_header"),
            ("CxlCacheHeader", "cxl_cache_header"),
            ("CxlCacheH2DRspHeader", "h2drsp_header"),
        ],
        "create_args": {
            "SystemHeader": ["payload_type"],
            "CxlCacheHeader": ["msg_class"],
            "CxlCacheH2DRspHeader": [
                "valid",
                "cache_opcode",
                "cache_id",
                "rsp_data",
                "cqid",
            ],
        },
    },
    "CxlCacheH2DDataPacket": {
        "layout": [
            ("SystemHeader", "system_header"),
            ("CxlCacheHeader", "cxl_cache_header"),
            ("CxlCacheH2DDataHeader", "h2ddata_header"),
        ],
        "create_args": {
            "SystemHeader": ["payload_type"],
            "CxlCacheHeader": ["msg_class"],
            "CxlCacheH2DDataHeader": [
                "valid",
                "cache_id",
                "cqid",
            ],
        },
    },
    # CXL.mem
    "CxlMemBasePacket": {
        "layout": [
            ("SystemHeader", "system_header"),
            ("CxlMemHeader", "cxl_mem_header"),
        ],
        "create_args": {},
    },
    "CxlMemM2SReqPacket": {
        "layout": [
            ("SystemHeader", "system_header"),
            ("CxlMemHeader", "cxl_mem_header"),
            ("CxlMemM2SReqHeader", "m2sreq_header"),
        ],
        "create_args": {
            "SystemHeader": ["payload_type"],
            "CxlMemHeader": ["msg_class"],
            "CxlMemM2SReqHeader": [
                "valid",
                "mem_opcode",
                "meta_field",
                "meta_value",
                "snp_type",
                "ld_id",
                "addr",
            ],
        },
    },
    "CxlMemM2SRwDPacket": {
        "layout": [
            ("SystemHeader", "system_header"),
            ("CxlMemHeader", "cxl_mem_header"),
            ("CxlMemM2SRwDHeader", "m2srwd_header"),
        ],
        "create_args": {
            "SystemHeader": ["payload_type"],
            "CxlMemHeader": ["msg_class"],
            "CxlMemM2SRwDHeader": [
                "valid",
                "mem_opcode",
                "meta_field",
                "meta_value",
                "snp_type",
                "ld_id",
                "addr",
            ],
        },
    },
    "CxlMemM2SBIRspPacket": {
        "layout": [
            ("SystemHeader", "system_header"),
            ("CxlMemHeader", "cxl_mem_header"),
            ("CxlMemM2SBIRspHeader", "m2sbirsp_header"),
        ],
        "create_args": {
            "SystemHeader": ["payload_type"],
            "CxlMemHeader": ["msg_class"],
            "CxlMemM2SBIRspHeader": [
                "valid",
                "opcode",
                "low_addr",
                "bi_id",
                "bi_tag",
            ],
        },
    },
    "CxlMemS2MBISnpPacket": {
        "layout": [
            ("SystemHeader", "system_header"),
            ("CxlMemHeader", "cxl_mem_header"),
            ("CxlMemS2MBISnpHeader", "s2mbisnp_header"),
        ],
        "create_args": {
            "SystemHeader": ["payload_type"],
            "CxlMemHeader": ["msg_class"],
            "CxlMemS2MBISnpHeader": [
                "valid",
                "opcode",
                "bi_id",
                "bi_tag",
                "addr",
            ],
        },
    },
    "CxlMemS2MNDRPacket": {
        "layout": [
            ("SystemHeader", "system_header"),
            ("CxlMemHeader", "cxl_mem_header"),
            ("CxlMemS2MNDRHeader", "s2mndr_header"),
        ],
        "create_args": {
            "SystemHeader": ["payload_type"],
            "CxlMemHeader": ["msg_class"],
            "CxlMemS2MNDRHeader": [
                "valid",
                "opcode",
                "meta_field",
                "meta_value",
                "ld_id",
            ],
        },
    },
    "CxlMemS2MDRSPacket": {
        "layout": [
            ("SystemHeader", "system_header"),
            ("CxlMemHeader", "cxl_mem_header"),
            ("CxlMemS2MDRSHeader", "s2mdrs_header"),
        ],
        "create_args": {
            "SystemHeader": ["payload_type"],
            "CxlMemHeader": ["msg_class"],
            "CxlMemS2MDRSHeader": [
                "valid",
                "opcode",
                "meta_field",
                "meta_value",
                "ld_id",
            ],
        },
    },
    # CCI
    "CciBasePacket": {
        "layout": [
            ("SystemHeader", "system_header"),
            ("CciHeader", "cci_header"),
        ],
        "create_args": {},
    },
    "CciMessagePacket": {
        "layout": [
            ("CciMessageHeader", "cci_msg_header"),
        ],
        "create_args": {},
    },
    "CciPayloadPacket": {
        "layout": [
            ("SystemHeader", "system_header"),
            ("CciHeader", "cci_header"),
        ],
        "create_args": {},
    },
    "CciRequestPacket": {
        "layout": [
            ("SystemHeader", "system_header"),
            ("CciHeader", "cci_header"),
            ("CciMessageHeader", "cci_msg_header"),
        ],
        "create_args": {},
    },
    "CciResponsePacket": {
        "layout": [
            ("SystemHeader", "system_header"),
            ("CciHeader", "cci_header"),
            ("CciMessageHeader", "cci_msg_header"),
        ],
        "create_args": {},
    },
}
