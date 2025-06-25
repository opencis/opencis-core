"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from opencis.cxl.transport.packet_structs import (
    _GenCxlCacheBasePacket,
    _GenCxlCacheD2HReqPacket,
    _GenCxlCacheD2HRspPacket,
    _GenCxlCacheD2HDataPacket,
    _GenCxlCacheH2DReqPacket,
    _GenCxlCacheH2DRspPacket,
    _GenCxlCacheH2DDataPacket,
)
from opencis.cxl.transport.packet_constants import (
    SYSTEM_PAYLOAD_TYPE,
    CXL_CACHE_MSG_CLASS,
    CXL_CACHE_D2HREQ_OPCODE,
    CXL_CACHE_D2HRSP_OPCODE,
    CXL_CACHE_H2DREQ_OPCODE,
    CXL_CACHE_H2DRSP_OPCODE,
    CXL_CACHE_H2DRSP_CACHE_STATE,
)
from opencis.cxl.transport.mixin import (
    BasePacketMixin,
    PacketDataMixin,
    CxlCacheBasePacketMixin,
)


class CxlCacheBasePacket(
    BasePacketMixin,
    CxlCacheBasePacketMixin,
    _GenCxlCacheBasePacket,
):
    pass


class CxlCacheD2HReqPacket(
    BasePacketMixin,
    CxlCacheBasePacketMixin,
    _GenCxlCacheD2HReqPacket,
):
    pass


class CxlCacheCacheD2HReqPacket(
    BasePacketMixin,
    CxlCacheBasePacketMixin,
    _GenCxlCacheD2HReqPacket,
):
    @classmethod
    def create(
        cls,
        addr: int,
        cache_id: int,
        opcode: CXL_CACHE_D2HREQ_OPCODE,
        cqid: int = 0,
    ) -> "CxlCacheCacheD2HReqPacket":
        packet = cls()
        packet.system_header.payload_type = SYSTEM_PAYLOAD_TYPE.CXL_CACHE
        packet.system_header.payload_length = len(packet)
        packet.cxl_cache_header.msg_class = CXL_CACHE_MSG_CLASS.D2H_REQ
        packet.d2hreq_header.valid = 1
        packet.d2hreq_header.cache_opcode = opcode
        packet.d2hreq_header.cqid = cqid
        packet.d2hreq_header.cache_id = cache_id
        if addr & 0x3F:
            raise Exception("Address must be a multiple of 0x40")
        packet.d2hreq_header.addr = addr >> 6
        return packet

    def get_address(self) -> int:
        return self.d2hreq_header.addr << 6

    def set_cache_id(self, cache_id: int) -> None:
        self.d2hreq_header.cache_id = cache_id


class CxlCacheD2HRspPacket(
    BasePacketMixin,
    CxlCacheBasePacketMixin,
    _GenCxlCacheD2HRspPacket,
):
    pass


class CxlCacheCacheD2HRspPacket(
    BasePacketMixin,
    CxlCacheBasePacketMixin,
    _GenCxlCacheD2HRspPacket,
):
    @classmethod
    def create(
        cls,
        uqid: int,
        opcode: CXL_CACHE_D2HRSP_OPCODE,
    ) -> "CxlCacheCacheD2HRspPacket":
        packet = cls()
        packet.system_header.payload_type = SYSTEM_PAYLOAD_TYPE.CXL_CACHE
        packet.system_header.payload_length = len(packet)
        packet.cxl_cache_header.msg_class = CXL_CACHE_MSG_CLASS.D2H_RSP
        packet.d2hrsp_header.valid = 1
        packet.d2hrsp_header.uqid = uqid
        packet.d2hrsp_header.cache_opcode = opcode
        return packet


class CxlCacheD2HDataPacket(
    BasePacketMixin,
    CxlCacheBasePacketMixin,
    _GenCxlCacheD2HDataPacket,
    PacketDataMixin,
):
    pass


class CxlCacheCacheD2HDataPacket(
    BasePacketMixin,
    CxlCacheBasePacketMixin,
    _GenCxlCacheD2HDataPacket,
    PacketDataMixin,
):
    @classmethod
    def create(
        cls,
        uqid: int,
        data: int,
    ) -> "CxlCacheCacheD2HDataPacket":
        # pylint: disable=duplicate-code
        packet = cls()
        packet.system_header.payload_type = SYSTEM_PAYLOAD_TYPE.CXL_CACHE
        packet.cxl_cache_header.msg_class = CXL_CACHE_MSG_CLASS.D2H_DATA
        packet.d2hdata_header.valid = 1
        packet.d2hdata_header.uqid = uqid
        packet.d2hdata_header.poison = 0

        if isinstance(data, int):
            packet.set_data_as_int(data)
        else:
            packet.set_data(data)

        packet.system_header.payload_length = len(packet)
        return packet


class CxlCacheH2DReqPacket(
    BasePacketMixin,
    CxlCacheBasePacketMixin,
    _GenCxlCacheH2DReqPacket,
):
    pass


class CxlCacheCacheH2DReqPacket(
    BasePacketMixin,
    CxlCacheBasePacketMixin,
    _GenCxlCacheH2DReqPacket,
):
    @classmethod
    def create(
        cls,
        addr: int,
        cache_id: int,
        opcode: CXL_CACHE_H2DREQ_OPCODE,
    ) -> "CxlCacheCacheH2DReqPacket":
        packet = cls()
        packet.system_header.payload_type = SYSTEM_PAYLOAD_TYPE.CXL_CACHE
        packet.cxl_cache_header.msg_class = CXL_CACHE_MSG_CLASS.H2D_REQ
        packet.h2dreq_header.valid = 1
        packet.h2dreq_header.cache_opcode = opcode
        packet.h2dreq_header.cache_id = cache_id
        if addr & 0x3F:
            raise Exception("Address must be a multiple of 0x40")
        packet.h2dreq_header.addr = addr >> 6
        packet.system_header.payload_length = len(packet)
        return packet

    def get_address(self) -> int:
        return self.h2dreq_header.addr << 6

    def get_opcode(self) -> CXL_CACHE_H2DREQ_OPCODE:
        return self.h2dreq_header.cache_opcode


class CxlCacheH2DRspPacket(
    BasePacketMixin,
    CxlCacheBasePacketMixin,
    _GenCxlCacheH2DRspPacket,
):
    pass


class CxlCacheCacheH2DRspPacket(
    BasePacketMixin,
    CxlCacheBasePacketMixin,
    _GenCxlCacheH2DRspPacket,
):
    @classmethod
    def create(
        cls,
        cache_id: int,
        opcode: CXL_CACHE_H2DRSP_OPCODE,
        rsp_data: CXL_CACHE_H2DRSP_CACHE_STATE,
        cqid: int = 0,
    ) -> "CxlCacheCacheH2DRspPacket":
        packet = cls()
        packet.system_header.payload_type = SYSTEM_PAYLOAD_TYPE.CXL_CACHE
        packet.system_header.payload_length = len(packet)
        packet.cxl_cache_header.msg_class = CXL_CACHE_MSG_CLASS.H2D_RSP
        packet.h2drsp_header.valid = 1
        packet.h2drsp_header.cache_opcode = opcode
        packet.h2drsp_header.cache_id = cache_id
        packet.h2drsp_header.rsp_data = rsp_data
        packet.h2drsp_header.cqid = cqid
        return packet

    def get_opcode(self) -> CXL_CACHE_H2DRSP_OPCODE:
        return self.h2drsp_header.cache_opcode


class CxlCacheH2DDataPacket(
    BasePacketMixin,
    CxlCacheBasePacketMixin,
    _GenCxlCacheH2DDataPacket,
    PacketDataMixin,
):
    pass


class CxlCacheCacheH2DDataPacket(
    BasePacketMixin,
    CxlCacheBasePacketMixin,
    _GenCxlCacheH2DDataPacket,
    PacketDataMixin,
):
    @classmethod
    def create(
        cls,
        cache_id: int,
        data: int,
        cqid: int = 0,
    ) -> "CxlCacheCacheH2DDataPacket":
        # pylint: disable=duplicate-code
        packet = cls()
        packet.system_header.payload_type = SYSTEM_PAYLOAD_TYPE.CXL_CACHE
        packet.cxl_cache_header.msg_class = CXL_CACHE_MSG_CLASS.H2D_DATA
        packet.h2ddata_header.valid = 1
        packet.h2ddata_header.cache_id = cache_id
        packet.h2ddata_header.cqid = cqid

        if isinstance(data, int):
            packet.set_data_as_int(data)
        else:
            packet.set_data(data)

        packet.system_header.payload_length = len(packet)
        return packet

    def get_cqid(self) -> int:
        return self.h2ddata_header.cqid

    def get_cache_id(self) -> int:
        return self.h2ddata_header.cache_id


# ------------------------------ Helper Functions ------------------------------#
def is_cxl_cache_h2d_data(packet) -> bool:
    if not packet.is_cxl_cache():
        return False
    return packet.is_h2ddata() and packet.h2ddata_header.valid == 1


def is_cxl_cache_d2h_data(packet) -> bool:
    if not packet.is_cxl_cache():
        return False
    return packet.is_d2hdata() and packet.d2hdata_header.valid == 1
