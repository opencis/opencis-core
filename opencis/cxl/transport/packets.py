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
    "CxlIoMemReqPacket": {
        "layout": [
            ("SystemHeader", "system_header"),
            ("TlpPrefix", "tlp_prefix"),
            ("CxlIoHeader", "cxl_io_header"),
            ("CxlIoMReqHeader", "mreq_header"),
        ],
        "create_args": {
            "SystemHeader": ["payload_type", "payload_length"],
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
    "CxlIoCfgReqPacket": {
        "layout": [
            ("SystemHeader", "system_header"),
            ("TlpPrefix", "tlp_prefix"),
            ("CxlIoHeader", "cxl_io_header"),
            ("CxlIoCfgReqHeader", "cfg_req_header"),
        ],
        "create_args": {
            "SystemHeader": ["payload_type", "payload_length"],
            "TlpPrefix": ["ld_id"],
            "CxlIoHeader": [
                "fmt_type",
                "tc",
                "attr",
                "at",
                "length_upper",
                "length_lower"
            ],
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
            "SystemHeader": ["payload_type", "payload_length"],
            "TlpPrefix": ["ld_id"],
            "CxlIoHeader": [
                "fmt_type",
                "length_upper",
                "length_lower"
            ],
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
    # TODO: GET RID OF IT
    "CxlIoCompletionWithDataPacket": {
        "layout": [
            ("SystemHeader", "system_header"),
            ("TlpPrefix", "tlp_prefix"),
            ("CxlIoHeader", "cxl_io_header"),
            ("CxlIoCompletionHeader", "cpl_header"),
        ],
        "create_args": {
            "SystemHeader": ["payload_type", "payload_length"],
            "TlpPrefix": ["ld_id"],
            "CxlIoHeader": [
                "fmt_type",
                "length_upper",
                "length_lower"
            ],
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
        "create_args": {
            "CxlCacheHeader": ["cache_op"],
        },
    },
    "CxlCacheD2HReqPacket": {
        "layout": [
            ("SystemHeader", "system_header"),
            ("CxlCacheHeader", "cxl_cache_header"),
            ("CxlCacheD2HReqHeader", "d2hreq_header"),
        ],
        "create_args": {
            "CxlCacheD2HReqHeader": ["request_id"],
        },
    },
    "CxlCacheD2HRspPacket": {
        "layout": [
            ("SystemHeader", "system_header"),
            ("CxlCacheHeader", "cxl_cache_header"),
            ("CxlCacheD2HRspHeader", "d2hrsp_header"),
        ],
        "create_args": {
            "CxlCacheD2HRspHeader": ["response_code"],
        },
    },
    "CxlCacheD2HDataPacket": {
        "layout": [
            ("SystemHeader", "system_header"),
            ("CxlCacheHeader", "cxl_cache_header"),
            ("CxlCacheD2HDataHeader", "d2hdata_header"),
        ],
        "create_args": {
            "CxlCacheD2HDataHeader": ["data_length"],
        },
    },
    "CxlCacheH2DReqPacket": {
        "layout": [
            ("SystemHeader", "system_header"),
            ("CxlCacheHeader", "cxl_cache_header"),
            ("CxlCacheH2DReqHeader", "h2dreq_header"),
        ],
        "create_args": {
            "CxlCacheH2DReqHeader": ["request_type"],
        },
    },
    "CxlCacheH2DRspPacket": {
        "layout": [
            ("SystemHeader", "system_header"),
            ("CxlCacheHeader", "cxl_cache_header"),
            ("CxlCacheH2DRspHeader", "h2drsp_header"),
        ],
        "create_args": {
            "CxlCacheH2DRspHeader": ["status_code"],
        },
    },
    "CxlCacheH2DDataPacket": {
        "layout": [
            ("SystemHeader", "system_header"),
            ("CxlCacheHeader", "cxl_cache_header"),
            ("CxlCacheH2DDataHeader", "h2ddata_header"),
        ],
        "create_args": {
            "CxlCacheH2DDataHeader": ["data_field"],
        },
    },
    # CXL.mem
    "CxlMemBasePacket": {
        "layout": [
            ("SystemHeader", "system_header"),
            ("CxlMemHeader", "cxl_mem_header"),
        ],
        "create_args": {
            "CxlMemHeader": ["mem_op"],
        },
    },
    "CxlMemM2SReqPacket": {
        "layout": [
            ("SystemHeader", "system_header"),
            ("CxlMemHeader", "cxl_mem_header"),
            ("CxlMemM2SReqHeader", "m2sreq_header"),
        ],
        "create_args": {
            "CxlMemM2SReqHeader": ["meta_field", "ld_id"],
        },
    },
    "CxlMemM2SRwDPacket": {
        "layout": [
            ("SystemHeader", "system_header"),
            ("CxlMemHeader", "cxl_mem_header"),
            ("CxlMemM2SRwDHeader", "m2srwd_header"),
        ],
        "create_args": {
            "CxlMemM2SRwDHeader": ["rw_flag"],
        },
    },
    "CxlMemM2SBIRspPacket": {
        "layout": [
            ("SystemHeader", "system_header"),
            ("CxlMemHeader", "cxl_mem_header"),
            ("CxlMemM2SBIRspHeader", "m2sbirsp_header"),
        ],
        "create_args": {
            "CxlMemM2SBIRspHeader": ["status"],
        },
    },
    "CxlMemS2MBISnpPacket": {
        "layout": [
            ("SystemHeader", "system_header"),
            ("CxlMemHeader", "cxl_mem_header"),
            ("CxlMemS2MBISnpHeader", "s2mbisnp_header"),
        ],
        "create_args": {
            "CxlMemS2MBISnpHeader": ["snp_code"],
        },
    },
    "CxlMemS2MNDRPacket": {
        "layout": [
            ("SystemHeader", "system_header"),
            ("CxlMemHeader", "cxl_mem_header"),
            ("CxlMemS2MNDRHeader", "s2mndr_header"),
        ],
        "create_args": {
            "CxlMemS2MNDRHeader": ["ndr_code"],
        },
    },
    "CxlMemS2MDRSPacket": {
        "layout": [
            ("SystemHeader", "system_header"),
            ("CxlMemHeader", "cxl_mem_header"),
            ("CxlMemS2MDRSHeader", "s2mdrs_header"),
        ],
        "create_args": {
            "CxlMemS2MDRSHeader": ["rsp_code"],
        },
    },
    # CCI
    "CciBasePacket": {
        "layout": [
            ("SystemHeader", "system_header"),
            ("CciHeader", "cci_header"),
        ],
        "create_args": {
            "CciHeader": ["cci_op"],
        },
    },
    "CciMessagePacket": {
        "layout": [
            ("CciMessageHeader", "cci_msg_header"),
        ],
        "create_args": {
            "CciMessageHeader": ["msg_type"],
        },
    },
    "CciPayloadPacket": {
        "layout": [
            ("SystemHeader", "system_header"),
            ("CciHeader", "cci_header"),
        ],
        "create_args": {
            "CciHeader": ["payload_len"],
        },
    },
    "CciRequestPacket": {
        "layout": [
            ("SystemHeader", "system_header"),
            ("CciHeader", "cci_header"),
            ("CciMessageHeader", "cci_msg_header"),
        ],
        "create_args": {
            "CciMessageHeader": ["request_id"],
        },
    },
    "CciResponsePacket": {
        "layout": [
            ("SystemHeader", "system_header"),
            ("CciHeader", "cci_header"),
            ("CciMessageHeader", "cci_msg_header"),
        ],
        "create_args": {
            "CciMessageHeader": ["response_id"],
        },
    },
}
