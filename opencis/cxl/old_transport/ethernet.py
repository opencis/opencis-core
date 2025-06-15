"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from opencis.util.unaligned_bit_structure import (
    UnalignedBitStructure,
    ByteField,
    StructureField,
)
from opencis.cxl.transport.common import (
    SystemHeaderPacket,
    CxlHeaderPacket,
)


class CxlEthernetPacket(UnalignedBitStructure):
    # NOTE: static attributes are for intellisense
    system_header: SystemHeaderPacket
    cxl_header: CxlHeaderPacket
    cxl_data: int
    data_parity: int

    _fields = [
        # Byte offset [03:00] - System Header
        StructureField("system_header", 0, 3, SystemHeaderPacket),
        # Byte offset [23:04] - CXL Header
        StructureField("cxl_header", 4, 23, CxlHeaderPacket),
        # Byte offset [87:24] - CXL Data
        ByteField("cxl_data", 24, 87),
        # Byte offset [99:88] - Data Parity
        ByteField("data_parity", 88, 99),
        # Byte offset [235:100] - Reserved
        ByteField("reserved", 100, 235),
    ]
