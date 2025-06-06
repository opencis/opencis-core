PACKETS = {
    "CxlIoMemReqPacket": [
        ("SystemHeader", "system_header"),
        ("SidebandHeader", "sideband_header"),
    ],
    # CXL.io
    "CxlIoMemReqPacket": [
        ("SystemHeader", "system_header"),
        ("TlpPrefix", "tlp_prefix"),
        ("CxlIoHeader", "cxl_io_header"),
        ("CxlIoMReqHeader", "mreq_header"),
        ("DataField", "data"),
    ],
    "CxlIoCfgReqPacket": [
        ("SystemHeader", "system_header"),
        ("TlpPrefix", "tlp_prefix"),
        ("CxlIoHeader", "cxl_io_header"),
        ("CxlIoCfgReqHeader", "cfg_req_header"),
        ("DataField", "value"),
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
        ("DataField", "data"),
    ],
    # CXL.cache
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
        ("DataField", "data"),
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
        ("DataField", "data"),
    ],
    # CXL.mem
    "CxlMemM2SReqPacket": [
        ("SystemHeader", "system_header"),
        ("CxlMemHeader", "cxl_mem_header"),
        ("CxlMemM2SReqHeader", "m2sreq_header"),
    ],
    "CxlMemM2SRwDPacket": [
        ("SystemHeader", "system_header"),
        ("CxlMemHeader", "cxl_mem_header"),
        ("CxlMemM2SRwDHeader", "m2srwd_header"),
        ("DataField", "data"),
    ],
    "CxlMemM2SBIRspPacket": [
        ("SystemHeader", "system_header"),
        ("CxlMemHeader", "cxl_mem_header"),
        ("CxlMemM2SBIRspHeader", "m2sbirsp_header"),
    ],
    "CxlMemS2MBISnpPacket": [
        ("SystemHeader", "system_header"),
        ("CxlMemHeader", "cxl_mem_header"),
        ("CxlMemS2MBISnpHeader", "s2mbisnp_header"),
    ],
    "CxlMemS2MNDRPacket": [
        ("SystemHeader", "system_header"),
        ("CxlMemHeader", "cxl_mem_header"),
        ("CxlMemS2MNDRHeader", "s2mndr_header"),
    ],
    "CxlMemS2MDRSPacket": [
        ("SystemHeader", "system_header"),
        ("CxlMemHeader", "cxl_mem_header"),
        ("CxlMemS2MDRSHeader", "s2mdrs_header"),
        ("DataField", "data"),
    ],
}
