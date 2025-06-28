"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

# from opencis.util.logger import logger
from opencis.cxl.transport.common import TagCounter
from opencis.cxl.transport.packet_structs import (
    _GenCxlMemBasePacket,
    _GenCxlMemM2SReqPacket,
    _GenCxlMemM2SRwDPacket,
    _GenCxlMemM2SBIRspPacket,
    _GenCxlMemS2MBISnpPacket,
    _GenCxlMemS2MDRSPacket,
    _GenCxlMemS2MNDRPacket,
)
from opencis.cxl.transport.packet_constants import (
    SYSTEM_PAYLOAD_TYPE,
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
    CxlMemBasePacketMixin,
)


_bisnp_tags = TagCounter(4096)


class CxlMemBasePacket(
    BasePacketMixin,
    CxlMemBasePacketMixin,
    _GenCxlMemBasePacket,
):
    pass


class CxlMemM2SReqPacket(
    BasePacketMixin,
    CxlMemBasePacketMixin,
    _GenCxlMemM2SReqPacket,
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
    _GenCxlMemM2SRwDPacket,
    PacketDataMixin,
):
    def is_mem_wr(self) -> bool:
        return self.m2srwd_header.mem_opcode == CXL_MEM_M2SRWD_OPCODE.MEM_WR

    def get_address(self) -> int:
        return self.m2srwd_header.addr << 6


class CxlMemM2SBIRspPacket(
    BasePacketMixin,
    CxlMemBasePacketMixin,
    _GenCxlMemM2SBIRspPacket,
):
    pass


class CxlMemS2MBISnpPacket(
    BasePacketMixin,
    CxlMemBasePacketMixin,
    _GenCxlMemS2MBISnpPacket,
):
    def get_address(self) -> int:
        return self.s2mbisnp_header.addr << 6


class CxlMemS2MNDRPacket(
    BasePacketMixin,
    CxlMemBasePacketMixin,
    _GenCxlMemS2MNDRPacket,
):
    pass


class CxlMemS2MDRSPacket(
    BasePacketMixin,
    CxlMemBasePacketMixin,
    _GenCxlMemS2MDRSPacket,
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
        # pylint: disable=duplicate-code
        packet = cls()
        packet.system_header.payload_type = SYSTEM_PAYLOAD_TYPE.CXL_MEM
        packet.cxl_mem_header.msg_class = CXL_MEM_MSG_CLASS.M2S_RWD
        packet.m2srwd_header.valid = 1
        packet.m2srwd_header.mem_opcode = opcode
        packet.m2srwd_header.meta_field = meta_field
        packet.m2srwd_header.meta_value = meta_value
        packet.m2srwd_header.snp_type = snp_type
        packet.m2srwd_header.ld_id = ld_id
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
    _GenCxlMemM2SBIRspPacket,
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
    _GenCxlMemS2MBISnpPacket,
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
        packet.s2mbisnp_header.addr = addr >> 6
        return packet


class CxlMemMemDataPacket(
    BasePacketMixin,
    CxlMemBasePacketMixin,
    _GenCxlMemS2MDRSPacket,
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
        # pylint: disable=duplicate-code
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
    _GenCxlMemS2MNDRPacket,
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


# ------------------------------ Helper Functions ------------------------------#
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
