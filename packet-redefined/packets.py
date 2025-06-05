PACKETS = {
    "CxlIoMemRdPacket": [
        ("SystemHeader", "system_header"),
        ("TlpPrefix", "tlp_prefix"),
        ("CxlIoHeader", "io_header"),
        ("CxlIoMReqHeader", "mreq_header"),
    ],
    "CxlIoMemWrPacket": [
        ("SystemHeader", "system_header"),
        ("TlpPrefix", "tlp_prefix"),
        ("CxlIoHeader", "io_header"),
        ("CxlIoMReqHeader", "mreq_header"),
        "DataField",
    ],
}
