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
}
