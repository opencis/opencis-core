"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from typing import Optional

# from opencis.util.logger import logger
from opencis.cxl.transport.packet_structs import (
    RawBasePacket,
    RawBaseSidebandPacket,
    RawSidebandConnectionRequestPacket,
    RawCxlCacheBasePacket,
    RawCxlCacheD2HReqPacket,
    RawCxlCacheD2HRspPacket,
    RawCxlCacheD2HDataPacket,
    RawCxlCacheH2DReqPacket,
    RawCxlCacheH2DRspPacket,
    RawCxlCacheH2DDataPacket,
    RawCxlMemBasePacket,
    RawCxlMemM2SReqPacket,
    RawCxlMemM2SRwDPacket,
    RawCxlMemM2SBIRspPacket,
    RawCxlMemS2MBISnpPacket,
    RawCxlMemS2MDRSPacket,
    RawCxlMemS2MNDRPacket,
)
from opencis.cxl.transport.packet_constants import (
    SYSTEM_PAYLOAD_TYPE,
    SIDEBAND_TYPES,
    CXL_CACHE_MSG_CLASS,
    CXL_CACHE_D2HREQ_OPCODE,
    CXL_CACHE_D2HRSP_OPCODE,
    CXL_CACHE_H2DREQ_OPCODE,
    CXL_CACHE_H2DRSP_OPCODE,
    CXL_CACHE_H2DRSP_CACHE_STATE,
    CXL_MEM_MSG_CLASS,
    CXL_MEM_M2SREQ_OPCODE,
    CXL_MEM_M2SRWD_OPCODE,
    CXL_MEM_META_FIELD,
    CXL_MEM_META_VALUE,
    CXL_MEM_M2S_SNP_TYPE,
    CXL_MEM_M2SBIRSP_OPCODE,
    CXL_MEM_S2MBISNP_OPCODE,
    CXL_MEM_S2MDRS_OPCODE,
    CXL_MEM_S2MNDR_OPCODE,
)
from opencis.cxl.transport.mixin import (
    BasePacketMixin,
    PacketDataMixin,
    SidebandPacketMixin,
    CxlCacheBasePacketMixin,
    CxlMemBasePacketMixin,
)


class BasePacket(BasePacketMixin, RawBasePacket):
    pass


# pylint: disable=duplicate-code
# TODO: Move to a common place
class _TagCounter:
    __slots__ = ("_value", "_mod")

    def __init__(self, modulus: int) -> None:
        self._value = 0
        self._mod = modulus

    def next(self, explicit: Optional[int] = None) -> int:
        if explicit is not None:
            return explicit & (self._mod - 1)
        tag = self._value
        self._value = (self._value + 1) % self._mod
        return tag


############ SIDEBAND
class BaseSidebandPacket(
    BasePacketMixin,
    SidebandPacketMixin,
    RawBaseSidebandPacket,
):
    @classmethod
    def create(cls, type: SIDEBAND_TYPES) -> "BaseSidebandPacket":
        packet = cls()
        packet.system_header.payload_type = SYSTEM_PAYLOAD_TYPE.SIDEBAND
        packet.sideband_header.type = type
        packet.system_header.payload_length = len(packet)
        return packet


class SidebandConnectionRequestPacket(
    BasePacketMixin,
    SidebandPacketMixin,
    RawSidebandConnectionRequestPacket,
    PacketDataMixin,
):
    @classmethod
    def create(cls, port_index: int) -> "SidebandConnectionRequestPacket":
        packet = cls()
        packet.system_header.payload_type = SYSTEM_PAYLOAD_TYPE.SIDEBAND
        packet.sideband_header.type = SIDEBAND_TYPES.CONNECTION_REQUEST
        packet.set_data_as_int(port_index)
        packet.system_header.payload_length = len(packet)
        return packet


######################################## CACHE
class CxlCacheBasePacket(
    BasePacketMixin,
    CxlCacheBasePacketMixin,
    RawCxlCacheBasePacket,
):
    pass


class CxlCacheD2HReqPacket(
    BasePacketMixin,
    CxlCacheBasePacketMixin,
    RawCxlCacheD2HReqPacket,
):
    pass


class CxlCacheCacheD2HReqPacket(
    BasePacketMixin,
    CxlCacheBasePacketMixin,
    RawCxlCacheD2HReqPacket,
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

    def set_cache_id(self, cache_id: int):
        self.d2hreq_header.cache_id = cache_id


class CxlCacheD2HRspPacket(
    BasePacketMixin,
    CxlCacheBasePacketMixin,
    RawCxlCacheD2HRspPacket,
):
    pass


class CxlCacheCacheD2HRspPacket(
    BasePacketMixin,
    CxlCacheBasePacketMixin,
    RawCxlCacheD2HRspPacket,
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
    RawCxlCacheD2HDataPacket,
    PacketDataMixin,
):
    pass


class CxlCacheCacheD2HDataPacket(
    BasePacketMixin,
    CxlCacheBasePacketMixin,
    RawCxlCacheD2HDataPacket,
    PacketDataMixin,
):
    @classmethod
    def create(
        cls,
        uqid: int,
        data: int,
    ) -> "CxlCacheCacheD2HDataPacket":
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
    RawCxlCacheH2DReqPacket,
):
    pass


class CxlCacheCacheH2DReqPacket(
    BasePacketMixin,
    CxlCacheBasePacketMixin,
    RawCxlCacheH2DReqPacket,
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
    RawCxlCacheH2DRspPacket,
):
    pass


class CxlCacheCacheH2DRspPacket(
    BasePacketMixin,
    CxlCacheBasePacketMixin,
    RawCxlCacheH2DRspPacket,
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
    RawCxlCacheH2DDataPacket,
    PacketDataMixin,
):
    pass


class CxlCacheCacheH2DDataPacket(
    BasePacketMixin,
    CxlCacheBasePacketMixin,
    RawCxlCacheH2DDataPacket,
    PacketDataMixin,
):
    @classmethod
    def create(
        cls,
        cache_id: int,
        data: int,
        cqid: int = 0,
    ) -> "CxlCacheCacheH2DDataPacket":
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


######### CACHE helper ##################
def is_cxl_cache_h2d_data(packet) -> bool:
    if not packet.is_cxl_cache():
        return False
    return packet.is_h2ddata() and packet.h2ddata_header.valid == 1


def is_cxl_cache_d2h_data(packet: BasePacket) -> bool:
    if not packet.is_cxl_cache():
        return False
    return packet.is_d2hdata() and packet.d2hdata_header.valid == 1


########################### CXL.mem

_bisnp_tags = _TagCounter(4096)


class CxlMemBasePacket(
    BasePacketMixin,
    CxlMemBasePacketMixin,
    RawCxlMemBasePacket,
):
    pass


class CxlMemM2SReqPacket(
    BasePacketMixin,
    CxlMemBasePacketMixin,
    RawCxlMemM2SReqPacket,
):
    def is_mem_rd(self) -> bool:
        return self.m2sreq_header.mem_opcode == CXL_MEM_M2SREQ_OPCODE.MEM_RD

    def is_mem_inv(self) -> bool:
        return self.m2sreq_header.mem_opcode == CXL_MEM_M2SREQ_OPCODE.MEM_INV

    def get_address(self) -> int:
        return self.m2sreq_header.addr << 6


class CxlMemM2SRwDPacket(
    BasePacketMixin,
    CxlMemBasePacketMixin,
    RawCxlMemM2SRwDPacket,
    PacketDataMixin,
):
    def is_mem_wr(self) -> bool:
        return self.m2srwd_header.mem_opcode == CXL_MEM_M2SRWD_OPCODE.MEM_WR

    def get_address(self) -> int:
        return self.m2srwd_header.addr << 6


class CxlMemM2SBIRspPacket(
    BasePacketMixin,
    CxlMemBasePacketMixin,
    RawCxlMemM2SBIRspPacket,
):
    pass


class CxlMemS2MBISnpPacket(
    BasePacketMixin,
    CxlMemBasePacketMixin,
    RawCxlMemS2MBISnpPacket,
):
    def get_address(self) -> int:
        return self.s2mbisnp_header.addr << 6


class CxlMemS2MNDRPacket(
    BasePacketMixin,
    CxlMemBasePacketMixin,
    RawCxlMemS2MNDRPacket,
):
    pass


class CxlMemS2MDRSPacket(
    BasePacketMixin,
    CxlMemBasePacketMixin,
    RawCxlMemS2MDRSPacket,
    PacketDataMixin,
):
    pass


class CxlMemMemRdPacket(CxlMemM2SReqPacket):
    @classmethod
    def create(
        cls,
        addr: int,
        opcode: CXL_MEM_M2SREQ_OPCODE = CXL_MEM_M2SREQ_OPCODE.MEM_RD,
        meta_field: CXL_MEM_META_FIELD = CXL_MEM_META_FIELD.NO_OP,
        meta_value: CXL_MEM_META_VALUE = CXL_MEM_META_VALUE.ANY,
        snp_type: CXL_MEM_M2S_SNP_TYPE = CXL_MEM_M2S_SNP_TYPE.NO_OP,
        ld_id: int = 0,
    ) -> "CxlMemMemRdPacket":
        packet = cls()
        packet.system_header.payload_type = SYSTEM_PAYLOAD_TYPE.CXL_MEM
        packet.system_header.payload_length = len(packet)
        packet.cxl_mem_header.msg_class = CXL_MEM_MSG_CLASS.M2S_REQ
        packet.m2sreq_header.valid = 1
        packet.m2sreq_header.mem_opcode = opcode
        packet.m2sreq_header.meta_field = meta_field
        packet.m2sreq_header.meta_value = meta_value
        packet.m2sreq_header.snp_type = snp_type
        packet.m2sreq_header.ld_id = ld_id
        if addr & 0x3F:
            raise Exception("Address must be a multiple of 0x40")
        packet.m2sreq_header.addr = addr >> 6
        return packet

    def is_mem_rd(self) -> bool:
        return self.m2sreq_header.mem_opcode == CXL_MEM_M2SREQ_OPCODE.MEM_RD

    def is_mem_inv(self) -> bool:
        return self.m2sreq_header.mem_opcode == CXL_MEM_M2SREQ_OPCODE.MEM_INV

    def get_address(self) -> int:
        return self.m2sreq_header.addr << 6


class CxlMemMemWrPacket(CxlMemM2SRwDPacket):
    @classmethod
    def create(
        cls,
        addr: int,
        data: int,
        opcode: CXL_MEM_M2SRWD_OPCODE = CXL_MEM_M2SRWD_OPCODE.MEM_WR,
        meta_field: CXL_MEM_META_FIELD = CXL_MEM_META_FIELD.NO_OP,
        meta_value: CXL_MEM_META_VALUE = CXL_MEM_META_VALUE.ANY,
        snp_type: CXL_MEM_M2S_SNP_TYPE = CXL_MEM_M2S_SNP_TYPE.NO_OP,
        ld_id: int = 0,
    ) -> "CxlMemMemWrPacket":
        packet = cls()
        packet.system_header.payload_type = SYSTEM_PAYLOAD_TYPE.CXL_MEM
        packet.cxl_mem_header.msg_class = CXL_MEM_MSG_CLASS.M2S_RWD
        packet.m2srwd_header.valid = 1
        packet.m2srwd_header.mem_opcode = opcode
        packet.m2srwd_header.meta_field = meta_field
        packet.m2srwd_header.meta_value = meta_value
        packet.m2srwd_header.snp_type = snp_type
        packet.m2srwd_header.ld_id = ld_id
        if addr & 0x3F:
            raise Exception("Address must be a multiple of 0x40")
        packet.m2srwd_header.addr = addr >> 6

        if isinstance(data, int):
            packet.set_data_as_int(data)
        else:
            packet.set_data(data)

        packet.system_header.payload_length = len(packet)
        return packet


class CxlMemBIRspPacket(
    BasePacketMixin,
    CxlMemBasePacketMixin,
    RawCxlMemM2SBIRspPacket,
):
    @classmethod
    def create(
        cls,
        opcode: CXL_MEM_M2SBIRSP_OPCODE,
        bi_id: int = 0,
        bi_tag: int = 0,
    ) -> "CxlMemBIRspPacket":
        packet = cls()
        packet.system_header.payload_type = SYSTEM_PAYLOAD_TYPE.CXL_MEM
        packet.system_header.payload_length = len(packet)
        packet.cxl_mem_header.msg_class = CXL_MEM_MSG_CLASS.M2S_BIRSP
        packet.m2sbirsp_header.valid = 1
        packet.m2sbirsp_header.opcode = opcode
        packet.m2sbirsp_header.low_addr = 0
        packet.m2sbirsp_header.bi_id = bi_id
        packet.m2sbirsp_header.bi_tag = bi_tag
        return packet


class CxlMemBISnpPacket(
    BasePacketMixin,
    CxlMemBasePacketMixin,
    RawCxlMemS2MBISnpPacket,
):
    @classmethod
    def get_tag(cls, tag) -> int:
        return _bisnp_tags.next(tag)

    @classmethod
    def create(
        cls,
        addr: int,
        opcode: CXL_MEM_S2MBISNP_OPCODE,
        bi_id: int = 0,
        bi_tag: int = None,
    ) -> "CxlMemBISnpPacket":
        packet = cls()
        packet.system_header.payload_type = SYSTEM_PAYLOAD_TYPE.CXL_MEM
        packet.system_header.payload_length = len(packet)
        packet.cxl_mem_header.msg_class = CXL_MEM_MSG_CLASS.S2M_BISNP
        packet.s2mbisnp_header.valid = 1
        packet.s2mbisnp_header.opcode = opcode
        packet.s2mbisnp_header.bi_id = bi_id
        packet.s2mbisnp_header.bi_tag = cls.get_tag(bi_tag)
        if addr & 0x3F:
            raise Exception("Address must be a multiple of 0x40")
        packet.s2mbisnp_header.addr = addr >> 6
        return packet


class CxlMemMemDataPacket(
    BasePacketMixin,
    CxlMemBasePacketMixin,
    RawCxlMemS2MDRSPacket,
    PacketDataMixin,
):
    @classmethod
    def create(
        cls,
        data: int,
        opcode: CXL_MEM_S2MDRS_OPCODE = CXL_MEM_S2MDRS_OPCODE.MEM_DATA,
        meta_field: CXL_MEM_META_FIELD = CXL_MEM_META_FIELD.NO_OP,
        meta_value: CXL_MEM_META_VALUE = CXL_MEM_META_VALUE.ANY,
        ld_id: int = 0,
    ) -> "CxlMemMemDataPacket":
        packet = cls()
        packet.system_header.payload_type = SYSTEM_PAYLOAD_TYPE.CXL_MEM
        packet.cxl_mem_header.msg_class = CXL_MEM_MSG_CLASS.S2M_DRS
        packet.s2mdrs_header.valid = 1
        packet.s2mdrs_header.opcode = opcode
        packet.s2mdrs_header.meta_field = meta_field
        packet.s2mdrs_header.meta_value = meta_value
        packet.s2mdrs_header.ld_id = ld_id

        if isinstance(data, int):
            packet.set_data_as_int(data)
        else:
            packet.set_data(data)

        packet.system_header.payload_length = len(packet)
        return packet


class CxlMemCmpPacket(
    BasePacketMixin,
    CxlMemBasePacketMixin,
    RawCxlMemS2MNDRPacket,
):
    @classmethod
    def create(
        cls,
        opcode: CXL_MEM_S2MNDR_OPCODE = CXL_MEM_S2MNDR_OPCODE.CMP,
        meta_field: CXL_MEM_META_FIELD = CXL_MEM_META_FIELD.NO_OP,
        meta_value: CXL_MEM_META_VALUE = CXL_MEM_META_VALUE.ANY,
        ld_id: int = 0,
    ) -> "CxlMemCmpPacket":
        packet = cls()
        packet.system_header.payload_type = SYSTEM_PAYLOAD_TYPE.CXL_MEM
        packet.system_header.payload_length = len(packet)
        packet.cxl_mem_header.msg_class = CXL_MEM_MSG_CLASS.S2M_NDR
        packet.s2mndr_header.valid = 1
        packet.s2mndr_header.opcode = opcode
        packet.s2mndr_header.meta_field = meta_field
        packet.s2mndr_header.meta_value = meta_value
        packet.s2mndr_header.ld_id = ld_id
        return packet


######### MEM helper ##################
def is_cxl_mem_data(packet) -> bool:
    return (
        packet.is_cxl_mem()
        and packet.is_s2mdrs()
        and packet.s2mdrs_header.opcode == CXL_MEM_S2MDRS_OPCODE.MEM_DATA
    )


def is_cxl_mem_completion(packet) -> bool:
    return (
        packet.is_cxl_mem()
        and packet.is_s2mndr()
        and packet.s2mndr_header.opcode == CXL_MEM_S2MNDR_OPCODE.CMP
    )


def is_cxl_mem_birsp(packet) -> bool:
    return packet.is_cxl_mem() and packet.is_m2sbirsp()
