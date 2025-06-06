PACKETS = {
    "CxlIoMemReqPacket": [
        ("SystemHeader", "system_header"),
        ("TlpPrefix", "tlp_prefix"),
        ("CxlIoHeader", "cxl_io_header"),
        ("CxlIoMReqHeader", "mreq_header"),
        "DataField",
    ],
    "CxlIoCfgReqPacket": [
        ("SystemHeader", "system_header"),
        ("TlpPrefix", "tlp_prefix"),
        ("CxlIoHeader", "cxl_io_header"),
        ("CxlIoCfgReqHeader", "cfg_req_header"),
        "DataField",
    ],
    "CxlIoCompletionPacket": [
        ("SystemHeader", "system_header"),
        ("TlpPrefix", "tlp_prefix"),
        ("CxlIoHeader", "cxl_io_header"),
        ("CxlIoCompletionHeader", "cpl_header"),
    ],
    "CxlIoCompletionWithDataPacket": [
        ("SystemHeader", "system_header"),
        ("TlpPrefix", "tlp_prefix"),
        ("CxlIoHeader", "cxl_io_header"),
        ("CxlIoCompletionHeader", "cpl_header"),
        "DataField",
    ],
    "CxlCacheD2HReqPacket": [
        ("SystemHeader", "system_header"),
        ("CxlCacheHeader", "cxl_cache_header"),
        ("CxlCacheD2HReqHeader", "d2hreq_header"),
    ],
    "CxlCacheD2HRspPacket": [
        ("SystemHeader", "system_header"),
        ("CxlCacheHeader", "cxl_cache_header"),
        ("CxlCacheD2HRspHeader", "d2hrsp_header"),
    ],
    "CxlCacheD2HDataPacket": [
        ("SystemHeader", "system_header"),
        ("CxlCacheHeader", "cxl_cache_header"),
        ("CxlCacheD2HDataHeader", "d2hdata_header"),
        "DataField",
    ],
    "CxlCacheH2DReqPacket": [
        ("SystemHeader", "system_header"),
        ("CxlCacheHeader", "cxl_cache_header"),
        ("CxlCacheH2DReqHeader", "h2dreq_header"),
    ],
    "CxlCacheH2DRspPacket": [
        ("SystemHeader", "system_header"),
        ("CxlCacheHeader", "cxl_cache_header"),
        ("CxlCacheH2DRspHeader", "h2drsp_header"),
    ],
    "CxlCacheH2DDataPacket": [
        ("SystemHeader", "system_header"),
        ("CxlCacheHeader", "cxl_cache_header"),
        ("CxlCacheH2DDataHeader", "h2ddata_header"),
        "DataField",
    ],
}
