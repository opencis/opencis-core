"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from enum import IntEnum

from opencis.util.unaligned_bit_structure import (
    UnalignedBitStructure,
    BitField,
    ByteField,
    StructureField,
)


#
# Packet Definitions for PAYLOAD_TYPE.CXL
#
class PAYLOAD_TYPE(IntEnum):
    CXL = 0  # packet based on CPI
    CXL_IO = 1  # Custom packet for CXL.io
    CXL_MEM = 2  # Custom packet for CXL.mem
    CXL_CACHE = 3  # Custom packet for CXL.cache
    CCI_MCTP = 4  # Custom packet for CCI MCTP
    SIDEBAND = 15


class SystemHeaderPacket(UnalignedBitStructure):
    payload_type: PAYLOAD_TYPE
    payload_length: int
    _fields = [
        # Bit offset [00:03]
        BitField("payload_type", 0x0, 0x3),
        # Bit offset [4:15]
        BitField("payload_length", 0x4, 0xF),
    ]


SYSTEM_HEADER_START = 0x00
SYSTEM_HEADER_END = SystemHeaderPacket.get_size() - 1


class BasePacket(UnalignedBitStructure):
    system_header: SystemHeaderPacket
    _fields = [
        StructureField(
            "system_header",
            SYSTEM_HEADER_START,
            SYSTEM_HEADER_END,
            SystemHeaderPacket,
        )
    ]

    def is_cxl_io(self) -> bool:
        return self.system_header.payload_type == PAYLOAD_TYPE.CXL_IO

    def is_cxl_mem(self) -> bool:
        return self.system_header.payload_type == PAYLOAD_TYPE.CXL_MEM

    def is_cxl_cache(self) -> bool:
        return self.system_header.payload_type == PAYLOAD_TYPE.CXL_CACHE

    def is_cci(self) -> bool:
        return self.system_header.payload_type == PAYLOAD_TYPE.CCI_MCTP

    def is_sideband(self) -> bool:
        return self.system_header.payload_type == PAYLOAD_TYPE.SIDEBAND

    def get_type(self) -> str:
        return self.__class__.__name__


#
# Packet Definitions for PAYLOAD_TYPE.CXL (SPI Packet)
#
class CPI_TRANSACTION_TYPE(IntEnum):
    SINGLE_TRANSACTION = 0
    MULTI_TRANSACTION = 1


class PAYLOAD_LENGTH(IntEnum):
    BYTES_256 = 0
    BYTES_512 = 1
    BYTES_1024 = 2
    RESERVED = 3


class OP_MODE(IntEnum):
    NORMAL_MODE = 0
    LOOPBACK_MODE = 1


class CHANNEL_TYPE(IntEnum):
    REQUEST = 0
    DATA = 1
    RESPONSE = 2
    GLOBAL = 3


class CXL_PORT(IntEnum):
    DOWNSTREAM_PORT = 0
    UPSTREAM_PORT = 1


class CXL_PROTOCOL(IntEnum):
    CXL_CACHE = 0
    CXL_MEM = 1


class CXL_PROTOCOL_ID(IntEnum):
    UPSTREAM_PORT_CXL_CACHE = 0b1000
    UPSTREAM_PORT_CXL_MEM = 0b1001
    DOWNSTREAM_PORT_CXL_CACHE = 0b1010
    DOWNSTREAM_PORT_CXL_MEM = 0b1011


class CxlHeaderPacket(UnalignedBitStructure):
    cxl_protocol_id: CXL_PROTOCOL_ID
    cpi_header: int

    _fields = [
        # Byte offset [01:00]
        ByteField("cxl_protocol_id", 0, 1),
        # Byte offset [17:02]
        ByteField("cpi_header", 2, 17),
        # Byte offset [19:18]
        ByteField("reserved", 18, 19),
    ]

    @staticmethod
    def get_cxl_port(cxl_protocol_id: CXL_PROTOCOL_ID) -> CXL_PORT:
        protocol_id = int(cxl_protocol_id)
        port_value = (protocol_id >> 1) & 0x1
        return CXL_PORT(port_value)

    @staticmethod
    def get_cxl_protocol(cxl_protocol_id: CXL_PROTOCOL_ID) -> CXL_PROTOCOL:
        protocol_id = int(cxl_protocol_id)
        port_value = protocol_id & 0x1
        return CXL_PROTOCOL(port_value)
