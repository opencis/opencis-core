SystemHeader = [
    ('payload_type', 0, 4),
    ('payload_length', 4, 12),
]

TlpPrefix = [
    ('pcie_base_spec_defined', 0, 8),
    ('ld_id', 8, 16),
    ('reserved', 24, 8),
]

CxlIoHeader = [
    ('fmt_type', 0, 8),
    ('th', 8, 1),
    ('rsvd', 9, 1),
    ('attr_b2', 10, 1),
    ('t8', 11, 1),
    ('tc', 12, 3),
    ('t9', 15, 1),
    ('length_upper', 16, 2),
    ('at', 18, 2),
    ('attr', 20, 2),
    ('ep', 22, 1),
    ('td', 23, 1),
    ('length_lower', 24, 8),
]

CxlIoMReqHeader = [
    ('req_id', 0, 16),
    ('tag', 16, 8),
    ('first_dw_be', 24, 4),
    ('last_dw_be', 28, 4),
    ('addr_upper', 32, 56),
    ('rsvd', 88, 2),
    ('addr_lower', 90, 6),
]

