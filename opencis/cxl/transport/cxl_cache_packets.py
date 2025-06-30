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
    _GenCxlCacheBasePacket,
    BasePacketMixin,
    CxlCacheBasePacketMixin,
):
    pass


class CxlCacheD2HReqPacket(
    _GenCxlCacheD2HReqPacket,
    BasePacketMixin,
    CxlCacheBasePacketMixin,
):
    pass


class CxlCacheCacheD2HReqPacket(
    _GenCxlCacheD2HReqPacket,
    BasePacketMixin,
    CxlCacheBasePacketMixin,
):
    @classmethod
    def create(
        cls,
        addr: int,
        cache_id: int,
        opcode: CXL_CACHE_D2HREQ_OPCODE,
        cqid: int = 0,
    ) -> "CxlCacheCacheD2HReqPacket":
        packet = super().create(
            SYSTEM_PAYLOAD_TYPE.CXL_CACHE,  # system_header__payload_type,
            CXL_CACHE_MSG_CLASS.D2H_REQ,  # cxl_cache_header__msg_class,
            1,  # d2hreq_header__valid,
            opcode,  # d2hreq_header__cache_opcode,
            cqid,  # d2hreq_header__cqid,
            cache_id,  # d2hreq_header__cache_id,
            addr >> 6,  # d2hreq_header__addr,
        )
        return packet

    def get_address(self) -> int:
        return self.d2hreq_header.addr << 6

    def set_cache_id(self, cache_id: int) -> None:
        self.d2hreq_header.cache_id = cache_id


class CxlCacheD2HRspPacket(
    _GenCxlCacheD2HRspPacket,
    BasePacketMixin,
    CxlCacheBasePacketMixin,
):
    pass


class CxlCacheCacheD2HRspPacket(
    _GenCxlCacheD2HRspPacket,
    BasePacketMixin,
    CxlCacheBasePacketMixin,
):
    @classmethod
    def create(
        cls,
        uqid: int,
        opcode: CXL_CACHE_D2HRSP_OPCODE,
    ) -> "CxlCacheCacheD2HRspPacket":
        packet = super().create(
            SYSTEM_PAYLOAD_TYPE.CXL_CACHE,  # system_header__payload_type,
            CXL_CACHE_MSG_CLASS.D2H_RSP,  # cxl_cache_header__msg_class,
            1,  # d2hrsp_header__valid,
            uqid,  # d2hrsp_header__uqid,
            opcode,  # d2hrsp_header__cache_opcode,
        )
        return packet


class CxlCacheD2HDataPacket(
    _GenCxlCacheD2HDataPacket,
    BasePacketMixin,
    CxlCacheBasePacketMixin,
    PacketDataMixin,
):
    pass


class CxlCacheCacheD2HDataPacket(
    _GenCxlCacheD2HDataPacket,
    BasePacketMixin,
    CxlCacheBasePacketMixin,
    PacketDataMixin,
):
    @classmethod
    def create(
        cls,
        uqid: int,
        data: int,
    ) -> "CxlCacheCacheD2HDataPacket":
        data = data.to_bytes(64, byteorder="little")
        packet = super().create(
            SYSTEM_PAYLOAD_TYPE.CXL_CACHE,  # system_header__payload_type,
            CXL_CACHE_MSG_CLASS.D2H_DATA,  # cxl_cache_header__msg_class,
            1,  # d2hdata_header__valid,
            uqid,  # d2hdata_header__uqid,
            0,  # d2hdata_header__poison,
            data,  # data
        )
        return packet


class CxlCacheH2DReqPacket(
    _GenCxlCacheH2DReqPacket,
    BasePacketMixin,
    CxlCacheBasePacketMixin,
):
    pass


class CxlCacheCacheH2DReqPacket(
    _GenCxlCacheH2DReqPacket,
    BasePacketMixin,
    CxlCacheBasePacketMixin,
):
    @classmethod
    def create(
        cls,
        addr: int,
        cache_id: int,
        opcode: CXL_CACHE_H2DREQ_OPCODE,
    ) -> "CxlCacheCacheH2DReqPacket":
        packet = super().create(
            SYSTEM_PAYLOAD_TYPE.CXL_CACHE,  # system_header__payload_type,
            CXL_CACHE_MSG_CLASS.H2D_REQ,  # cxl_cache_header__msg_class,
            1,  # h2dreq_header__valid,
            opcode,  # h2dreq_header__cache_opcode,
            cache_id,  # h2dreq_header__cache_id,
            addr >> 6,  # h2dreq_header__addr,
        )
        return packet

    def get_address(self) -> int:
        return self.h2dreq_header.addr << 6

    def get_opcode(self) -> CXL_CACHE_H2DREQ_OPCODE:
        return self.h2dreq_header.cache_opcode


class CxlCacheH2DRspPacket(
    _GenCxlCacheH2DRspPacket,
    BasePacketMixin,
    CxlCacheBasePacketMixin,
):
    pass


class CxlCacheCacheH2DRspPacket(
    _GenCxlCacheH2DRspPacket,
    BasePacketMixin,
    CxlCacheBasePacketMixin,
):
    @classmethod
    def create(
        cls,
        cache_id: int,
        opcode: CXL_CACHE_H2DRSP_OPCODE,
        rsp_data: CXL_CACHE_H2DRSP_CACHE_STATE,
        cqid: int = 0,
    ) -> "CxlCacheCacheH2DRspPacket":
        packet = super().create(
            SYSTEM_PAYLOAD_TYPE.CXL_CACHE,  # system_header__payload_type,
            CXL_CACHE_MSG_CLASS.H2D_RSP,  # cxl_cache_header__msg_class,
            1,  # h2drsp_header__valid,
            opcode,  # h2drsp_header__cache_opcode,
            cache_id,  # h2drsp_header__cache_id,
            rsp_data,  # h2drsp_header__rsp_data,
            cqid,  # h2drsp_header__cqid,
        )
        return packet

    def get_opcode(self) -> CXL_CACHE_H2DRSP_OPCODE:
        return self.h2drsp_header.cache_opcode


class CxlCacheH2DDataPacket(
    _GenCxlCacheH2DDataPacket,
    BasePacketMixin,
    CxlCacheBasePacketMixin,
    PacketDataMixin,
):
    pass


class CxlCacheCacheH2DDataPacket(
    _GenCxlCacheH2DDataPacket,
    BasePacketMixin,
    CxlCacheBasePacketMixin,
    PacketDataMixin,
):
    @classmethod
    def create(
        cls,
        cache_id: int,
        data: int,
        cqid: int = 0,
    ) -> "CxlCacheCacheH2DDataPacket":
        data = data.to_bytes(64, byteorder="little")
        packet = super().create(
            SYSTEM_PAYLOAD_TYPE.CXL_CACHE,  # system_header__payload_type,
            CXL_CACHE_MSG_CLASS.H2D_DATA,  # cxl_cache_header__msg_class,
            1,  # h2ddata_header__valid,
            cache_id,  # h2ddata_header__cache_id,
            cqid,  # h2ddata_header__cqid,
            data,  # data
        )
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
