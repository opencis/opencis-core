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
    _GenCxlMemBasePacket,
    BasePacketMixin,
    CxlMemBasePacketMixin,
):
    pass


class CxlMemM2SReqPacket(
    _GenCxlMemM2SReqPacket,
    BasePacketMixin,
    CxlMemBasePacketMixin,
):
    def is_mem_rd(self) -> bool:
        return self.m2sreq_header.mem_opcode == CXL_MEM_M2SREQ_OPCODE.MEM_RD

    def is_mem_inv(self) -> bool:
        return self.m2sreq_header.mem_opcode == CXL_MEM_M2SREQ_OPCODE.MEM_INV

    def get_address(self) -> int:
        return self.m2sreq_header.addr << 6


class CxlMemM2SRwDPacket(
    _GenCxlMemM2SRwDPacket,
    BasePacketMixin,
    CxlMemBasePacketMixin,
    PacketDataMixin,
):
    def is_mem_wr(self) -> bool:
        return self.m2srwd_header.mem_opcode == CXL_MEM_M2SRWD_OPCODE.MEM_WR

    def get_address(self) -> int:
        return self.m2srwd_header.addr << 6


class CxlMemM2SBIRspPacket(
    _GenCxlMemM2SBIRspPacket,
    BasePacketMixin,
    CxlMemBasePacketMixin,
):
    pass


class CxlMemS2MBISnpPacket(
    _GenCxlMemS2MBISnpPacket,
    BasePacketMixin,
    CxlMemBasePacketMixin,
):
    def get_address(self) -> int:
        return self.s2mbisnp_header.addr << 6


class CxlMemS2MNDRPacket(
    _GenCxlMemS2MNDRPacket,
    BasePacketMixin,
    CxlMemBasePacketMixin,
):
    pass


class CxlMemS2MDRSPacket(
    _GenCxlMemS2MDRSPacket,
    BasePacketMixin,
    CxlMemBasePacketMixin,
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
        packet = super().create(
            SYSTEM_PAYLOAD_TYPE.CXL_MEM,  # system_header__payload_type,
            CXL_MEM_MSG_CLASS.M2S_REQ,  # cxl_mem_header__msg_class,
            1,  # m2sreq_header__valid,
            opcode,  # m2sreq_header__mem_opcode,
            meta_field,  # m2sreq_header__meta_field,
            meta_value,  # m2sreq_header__meta_value,
            snp_type,  # m2sreq_header__snp_type,
            ld_id,  # m2sreq_header__ld_id,
            addr >> 6,  # m2sreq_header__addr,
            None,  # data
        )
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
        data = data.to_bytes(64, byteorder="little")
        packet = super().create(
            SYSTEM_PAYLOAD_TYPE.CXL_MEM,  # system_header__payload_type,
            CXL_MEM_MSG_CLASS.M2S_RWD,  # cxl_mem_header__msg_class,
            1,  # m2srwd_header__valid,
            opcode,  # m2srwd_header__mem_opcode,
            meta_field,  # m2srwd_header__meta_field,
            meta_value,  # m2srwd_header__meta_value,
            snp_type,  # m2srwd_header__snp_type,
            ld_id,  # m2srwd_header__ld_id,
            addr >> 6,  # m2srwd_header__addr,
            data,
        )
        return packet

    def assign(
        self,
        addr: int,
        data: int,
        opcode: CXL_MEM_M2SRWD_OPCODE = CXL_MEM_M2SRWD_OPCODE.MEM_WR,
        meta_field: CXL_MEM_META_FIELD = CXL_MEM_META_FIELD.NO_OP,
        meta_value: CXL_MEM_META_VALUE = CXL_MEM_META_VALUE.ANY,
        snp_type: CXL_MEM_M2S_SNP_TYPE = CXL_MEM_M2S_SNP_TYPE.NO_OP,
        ld_id: int = 0,
    ) -> "CxlMemMemWrPacket":
        data = data.to_bytes(64, byteorder="little")
        packet = super().assign(
            SYSTEM_PAYLOAD_TYPE.CXL_MEM,  # system_header__payload_type,
            CXL_MEM_MSG_CLASS.M2S_RWD,  # cxl_mem_header__msg_class,
            1,  # m2srwd_header__valid,
            opcode,  # m2srwd_header__mem_opcode,
            meta_field,  # m2srwd_header__meta_field,
            meta_value,  # m2srwd_header__meta_value,
            snp_type,  # m2srwd_header__snp_type,
            ld_id,  # m2srwd_header__ld_id,
            addr >> 6,  # m2srwd_header__addr,
            data,
        )
        return packet


class CxlMemBIRspPacket(
    _GenCxlMemM2SBIRspPacket,
    BasePacketMixin,
    CxlMemBasePacketMixin,
):
    @classmethod
    def create(
        cls,
        opcode: CXL_MEM_M2SBIRSP_OPCODE,
        bi_id: int = 0,
        bi_tag: int = 0,
    ) -> "CxlMemBIRspPacket":
        packet = super().create(
            SYSTEM_PAYLOAD_TYPE.CXL_MEM,  # system_header__payload_type,
            CXL_MEM_MSG_CLASS.M2S_BIRSP,  # cxl_mem_header__msg_class,
            1,  # m2sbirsp_header__valid,
            opcode,  # m2sbirsp_header__opcode,
            0,  # m2sbirsp_header__low_addr,
            bi_id,  # m2sbirsp_header__bi_id,
            bi_tag,  # m2sbirsp_header__bi_tag
        )
        return packet


class CxlMemBISnpPacket(
    _GenCxlMemS2MBISnpPacket,
    BasePacketMixin,
    CxlMemBasePacketMixin,
):
    @classmethod
    def acquire_tag(cls, tag) -> int:
        return _bisnp_tags.next(tag)

    @classmethod
    def create(
        cls,
        addr: int,
        opcode: CXL_MEM_S2MBISNP_OPCODE,
        bi_id: int = 0,
        bi_tag: int = None,
    ) -> "CxlMemBISnpPacket":
        packet = super().create(
            SYSTEM_PAYLOAD_TYPE.CXL_MEM,  # system_header__payload_type,
            CXL_MEM_MSG_CLASS.S2M_BISNP,  # cxl_mem_header__msg_class,
            1,  # s2mbisnp_header__valid,
            opcode,  # s2mbisnp_header__opcode,
            bi_id,  # s2mbisnp_header__bi_id,
            cls.acquire_tag(bi_tag),  # s2mbisnp_header__bi_tag,
            addr >> 6,  # s2mbisnp_header__addr
        )
        return packet


class CxlMemMemDataPacket(
    _GenCxlMemS2MDRSPacket,
    BasePacketMixin,
    CxlMemBasePacketMixin,
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
        data = data.to_bytes(64, byteorder="little")
        packet = super().create(
            SYSTEM_PAYLOAD_TYPE.CXL_MEM,  # system_header__payload_type,
            CXL_MEM_MSG_CLASS.S2M_DRS,  # cxl_mem_header__msg_class,
            1,  # s2mdrs_header__valid,
            opcode,  # s2mdrs_header__opcode,
            meta_field,  # s2mdrs_header__meta_field,
            meta_value,  # s2mdrs_header__,
            ld_id,  # s2mdrs_header__ld_id,
            data,  # data
        )
        return packet


class CxlMemCmpPacket(
    _GenCxlMemS2MNDRPacket,
    BasePacketMixin,
    CxlMemBasePacketMixin,
):
    @classmethod
    def create(
        cls,
        opcode: CXL_MEM_S2MNDR_OPCODE = CXL_MEM_S2MNDR_OPCODE.CMP,
        meta_field: CXL_MEM_META_FIELD = CXL_MEM_META_FIELD.NO_OP,
        meta_value: CXL_MEM_META_VALUE = CXL_MEM_META_VALUE.ANY,
        ld_id: int = 0,
    ) -> "CxlMemCmpPacket":
        packet = super().create(
            SYSTEM_PAYLOAD_TYPE.CXL_MEM,  # system_header__payload_type,
            CXL_MEM_MSG_CLASS.S2M_NDR,  # cxl_mem_header__msg_class,
            1,  # s2mndr_header__valid,
            opcode,  # s2mndr_header__opcode,
            meta_field,  # s2mndr_header__meta_field,
            meta_value,  # s2mndr_header__meta_value,
            ld_id,  # s2mndr_header__ld_id,
        )
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
