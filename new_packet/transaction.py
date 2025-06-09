"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from typing import Optional
from opencis.util.logger import logger

from new_packet.packet_structs import (
    RawBasePacket,
    RawBaseSidebandPacket,
    RawSidebandConnectionRequestPacket,
    RawCxlIoBasePacket,
    RawCxlIoMemReqPacket,
    RawCxlIoCfgReqPacket,
    RawCxlIoCompletionPacket,
    RawCxlIoCompletionWithDataPacket,
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
    RawCciBasePacket,
    RawCciMessagePacket,
    RawCciPayloadPacket,
    RawCciRequestPacket,
    RawCciResponsePacket,
)
from opencis.util.pci import (
    extract_function_from_bdf,
    extract_device_from_bdf,
    extract_bus_from_bdf,
)
from opencis.util.number import (
    htotlp16,
    tlptoh16,
    extract_upper,
    extract_lower,
)
from packet_constants import (
    SYSTEM_PAYLOAD_TYPE,
    SIDEBAND_TYPES,
    CXL_IO_FMT_TYPE,
    CXL_IO_CPL_STATUS,
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
    CCI_MSG_CLASS,
    CCI_MCTP_MESSAGE_CATEGORY,
)
from opencis.cxl.cci.common import (
    CCI_FM_API_COMMAND_OPCODE,
)
from mixin import (
    BasePacketMixin,
    SidebandPacketMixin,
    CxlIoBasePacketMixin,
    CxlCacheBasePacketMixin,
    CxlMemBasePacketMixin,
    CciBasePacketMixin,
    PacketFieldMixin,
    PacketDataMixin,
)


class BasePacket(BasePacketMixin, RawBasePacket):
    pass


############ SIDEBAND
class BaseSidebandPacket(BasePacketMixin, SidebandPacketMixin, RawBaseSidebandPacket):
    @classmethod
    def create(cls, type: SIDEBAND_TYPES) -> "BaseSidebandPacket":
        packet = cls()
        packet.system_header.payload_type = SYSTEM_PAYLOAD_TYPE.SIDEBAND
        packet.sideband_header.type = type
        packet.system_header.payload_length = len(packet)
        return packet


class SidebandConnectionRequestPacket(
    BasePacketMixin, SidebandPacketMixin, RawSidebandConnectionRequestPacket, PacketDataMixin
):
    @classmethod
    def create(cls, port_index: int) -> "SidebandConnectionRequestPacket":
        packet = cls()
        packet.system_header.payload_type = SYSTEM_PAYLOAD_TYPE.SIDEBAND
        packet.sideband_header.type = SIDEBAND_TYPES.CONNECTION_REQUEST
        packet.set_data_as_int(port_index)
        packet.system_header.payload_length = len(packet)
        return packet


######## IO
class CxlIoBasePacket(BasePacketMixin, CxlIoBasePacketMixin, RawCxlIoBasePacket):
    pass


class CxlIoMemReqPacket(
    BasePacketMixin, CxlIoBasePacketMixin, RawCxlIoMemReqPacket, PacketDataMixin
):
    _tag_counter: int = 0

    @classmethod
    def get_tag(cls, tag) -> int:
        if tag is None:
            tag = CxlIoMemReqPacket._tag_counter
            CxlIoMemReqPacket._tag_counter = (CxlIoMemReqPacket._tag_counter + 1) % 256
        return tag

    def fill(self, addr: int, length: int, req_id: int, tag: int):
        address_offset = addr % 4
        length_dword = (address_offset + length + 3) // 4

        self.system_header.payload_type = SYSTEM_PAYLOAD_TYPE.CXL_IO
        self.cxl_io_header.length_upper = length_dword & 0x300
        self.cxl_io_header.length_lower = length_dword & 0xFF
        self.mreq_header.req_id = req_id
        self.mreq_header.tag = tag

        bytes_enabled = (1 << length) - 1
        bytes_enabled_with_offset = bytes_enabled << address_offset
        self.mreq_header.first_dw_be = bytes_enabled_with_offset & 0xF
        self.mreq_header.last_dw_be = (
            (bytes_enabled_with_offset >> ((length_dword - 1) * 4)) & 0xF if length_dword > 1 else 0
        )

        addr_upper_bytes = (addr >> 8).to_bytes(7, byteorder="big")
        self.mreq_header.addr_upper = int.from_bytes(addr_upper_bytes, byteorder="little")
        self.mreq_header.addr_lower = (addr & 0xFF) >> 2

    def get_address(self) -> int:
        addr = 0
        addr_upper_bytes = self.mreq_header.addr_upper.to_bytes(7, byteorder="little")
        addr |= int.from_bytes(addr_upper_bytes, byteorder="big") << 8
        addr |= self.mreq_header.addr_lower << 2
        return addr

    def get_data_size(self) -> int:
        return ((self.cxl_io_header.length_upper << 8) | self.cxl_io_header.length_lower) * 4

    def get_transaction_id(self) -> int:
        return self.build_transaction_id(self.mreq_header.req_id, self.mreq_header.tag)


class CxlIoMemRdPacket(CxlIoMemReqPacket):
    @classmethod
    def create(cls, addr: int, length: int, req_id: int = 0, tag: int = None, ld_id: int = 0):
        packet = cls()
        packet.fill(addr, length, htotlp16(req_id), super().get_tag(tag))
        packet.cxl_io_header.fmt_type = CXL_IO_FMT_TYPE.MRD_64B
        packet.tlp_prefix.ld_id = ld_id
        packet.system_header.payload_length = packet.get_size()
        return packet


class CxlIoMemWrPacket(CxlIoMemReqPacket):
    @classmethod
    def create(
        cls,
        addr: int,
        length: int,
        data: bytes | int,
        req_id: int = 0,
        tag: int = None,
        ld_id: int = 0,
    ):
        packet = cls()
        if isinstance(data, int):
            packet.set_data_as_int(data, length)
            length = (data.bit_length() + 7) // 8 or 1
        else:
            packet.set_data(data)
            length = len(data)
        packet.fill(addr, length, htotlp16(req_id), super().get_tag(tag))
        packet.cxl_io_header.fmt_type = CXL_IO_FMT_TYPE.MWR_64B
        packet.tlp_prefix.ld_id = ld_id
        packet.system_header.payload_length = packet.get_size()
        return packet


class CxlIoCfgReqPacket(
    BasePacketMixin, CxlIoBasePacketMixin, RawCxlIoCfgReqPacket, PacketDataMixin
):
    _tag_counter: int = 0

    @classmethod
    def get_tag(cls, tag) -> int:
        if tag is None:
            tag = CxlIoCfgReqPacket._tag_counter
            CxlIoCfgReqPacket._tag_counter = (CxlIoCfgReqPacket._tag_counter + 1) % 256
        return tag

    def fill(self, id: int, cfg_addr: int, size: int, req_id: int, tag: int) -> "CxlIoCfgReqPacket":
        self.system_header.payload_type = SYSTEM_PAYLOAD_TYPE.CXL_IO

        self.cxl_io_header.tc = 0b000
        self.cxl_io_header.attr = 0b00
        self.cxl_io_header.at = 0b00
        self.cxl_io_header.length_upper = 0b00
        self.cxl_io_header.length_lower = 0b00000001
        # NOTE: Request ID for CfgRd and CfgWr is always 0
        self.cfg_req_header.req_id = htotlp16(req_id)
        self.cfg_req_header.tag = tag

        # compute byte-enable bits
        if cfg_addr > 0xFFF:
            raise Exception("Invalid CXL.io CFG addr")
        offset = cfg_addr & 0x03
        if (offset + size) > 4:
            raise Exception("Invalid CXL.io CFG access size")
        first_dw_be = 0
        for _ in range(size):
            first_dw_be |= 1 << offset
            offset += 1

        self.cfg_req_header.first_dw_be = first_dw_be
        self.cfg_req_header.last_dw_be = 0b0000
        self.cfg_req_header.dest_id = htotlp16(id)
        self.cfg_req_header.ext_reg_num = (cfg_addr >> 8) & 0x0F
        self.cfg_req_header.reg_num = (cfg_addr >> 2) & 0x3F
        return self

    def get_cfg_addr_read_info(self) -> int:
        reg_num = (self.cfg_req_header.ext_reg_num << 6) | self.cfg_req_header.reg_num
        return reg_num << 2, 4

    def get_cfg_addr_write_info(self):
        reg_num = (self.cfg_req_header.ext_reg_num << 6) | self.cfg_req_header.reg_num
        be = self.cfg_req_header.first_dw_be
        b, pos = 1, 0
        while be & b == 0:
            b = b << 1
            pos += 1
        cfg_addr = (reg_num << 2) + pos
        size = 0
        while be != 0:
            be = be & (be - 1)
            size += 1
        return cfg_addr, size

    def get_bus(self):
        dest_id = tlptoh16(self.cfg_req_header.dest_id)
        return extract_bus_from_bdf(dest_id)

    def get_device(self):
        dest_id = tlptoh16(self.cfg_req_header.dest_id)
        return extract_device_from_bdf(dest_id)

    def get_function(self):
        dest_id = tlptoh16(self.cfg_req_header.dest_id)
        return extract_function_from_bdf(dest_id)

    def get_transaction_id(self) -> int:
        return self.build_transaction_id(self.cfg_req_header.req_id, self.cfg_req_header.tag)


class CxlIoCfgRdPacket(CxlIoCfgReqPacket):
    @classmethod
    def create(
        cls,
        id: int,
        cfg_addr: int,
        size: int,
        is_type0: bool = True,
        req_id: int = 0,
        tag: Optional[int] = None,
        ld_id: int = 0,
    ) -> "CxlIoCfgRdPacket":
        packet = cls(None)
        packet.fill(id, cfg_addr, size, req_id, super().get_tag(tag))
        packet.cxl_io_header.fmt_type = (
            CXL_IO_FMT_TYPE.CFG_RD0 if is_type0 else CXL_IO_FMT_TYPE.CFG_RD1
        )
        packet.system_header.payload_length = packet.get_size()
        packet.tlp_prefix.ld_id = ld_id
        return packet


class CxlIoCfgWrPacket(CxlIoCfgReqPacket):
    @classmethod
    def create(
        cls,
        id: int,
        cfg_addr: int,
        size: int,
        value: int,
        is_type0: bool = True,
        req_id: Optional[int] = 0,
        tag: Optional[int] = None,
        ld_id: int = 0,
    ) -> "CxlIoCfgWrPacket":
        offset = cfg_addr % 4
        packet = cls(None)
        value = value << (8 * offset)
        packet.set_data_as_int(value)
        packet.fill(id, cfg_addr, size, req_id, super().get_tag(tag))
        packet.cxl_io_header.fmt_type = (
            CXL_IO_FMT_TYPE.CFG_WR0 if is_type0 else CXL_IO_FMT_TYPE.CFG_WR1
        )
        packet.tlp_prefix.ld_id = ld_id
        packet.system_header.payload_length = packet.get_size()
        return packet

    def get_value(self) -> int:
        cfg_addr, size = self.get_cfg_addr_write_info()
        offset = cfg_addr % 4
        bit_offset = (offset % 4) * 8
        bit_mask = (1 << size * 8) - 1
        return (self.get_data_as_int() >> bit_offset) & bit_mask


from mixin import BasePacketMixin, CxlIoBasePacketMixin, CXL_IO_FMT_TYPE, SYSTEM_PAYLOAD_TYPE


class CxlIoCompletionPacket(BasePacketMixin, CxlIoBasePacketMixin, RawCxlIoCompletionPacket):
    @classmethod
    def create(
        cls,
        req_id: int,
        tag: int,
        cpl_id: int = 0,
        status: CXL_IO_CPL_STATUS = CXL_IO_CPL_STATUS.SC,
        ld_id: int = 0,
    ) -> "CxlIoCompletionPacket":
        packet = cls()
        packet.system_header.payload_type = SYSTEM_PAYLOAD_TYPE.CXL_IO
        packet.system_header.payload_length = packet.get_size()
        packet.cxl_io_header.fmt_type = CXL_IO_FMT_TYPE.CPL
        packet.cxl_io_header.length_upper = 0
        packet.cxl_io_header.length_lower = 0
        packet.tlp_prefix.ld_id = ld_id

        packet.cpl_header.cpl_id = htotlp16(cpl_id)
        packet.cpl_header.status = status
        packet.cpl_header.byte_count_upper = 0
        packet.cpl_header.byte_count_lower = 4
        packet.cpl_header.req_id = htotlp16(req_id)
        packet.cpl_header.tag = tag

        return packet

    def get_transaction_id(self) -> int:
        return self.build_transaction_id(self.cpl_header.req_id, self.cpl_header.tag)


class CxlIoCompletionWithDataPacket(
    BasePacketMixin, CxlIoBasePacketMixin, RawCxlIoCompletionWithDataPacket, PacketDataMixin
):
    @classmethod
    def create(
        cls,
        req_id: int,
        tag: int,
        data: int,
        cpl_id: int = 0,
        status: CXL_IO_CPL_STATUS = CXL_IO_CPL_STATUS.SC,
        pload_len: int = 0x04,
        ld_id: int = 0,
    ) -> "CxlIoCompletionWithDataPacket":
        packet = cls()
        packet.system_header.payload_type = SYSTEM_PAYLOAD_TYPE.CXL_IO
        packet.cxl_io_header.fmt_type = CXL_IO_FMT_TYPE.CPL_D

        packet.cxl_io_header.length_upper = extract_upper(pload_len // 4, 2, 10)
        packet.cxl_io_header.length_lower = extract_lower(pload_len // 4, 8, 10)

        packet.cpl_header.cpl_id = htotlp16(cpl_id)
        packet.cpl_header.status = status
        packet.cpl_header.req_id = htotlp16(req_id)
        packet.cpl_header.tag = tag

        packet.cpl_header.byte_count_upper = extract_upper(pload_len, 4, 12)
        packet.cpl_header.byte_count_lower = extract_lower(pload_len, 8, 12)

        if hasattr(data, "__int__"):
            packet.set_data_as_int(int(data))
        else:
            packet.set_data(bytes(data))
        #     if isinstance(data, int):
        #         logger.info(f"!!!DATA i: {data:x}")
        #         packet.set_data_as_int(data)
        #     else:
        #         logger.info(f"!!!DATA b: {data}")
        #         packet.set_data(data)

        packet.tlp_prefix.ld_id = ld_id
        packet.system_header.payload_length = packet.get_size()

        return packet

    def get_transaction_id(self) -> int:
        return self.build_transaction_id(self.cpl_header.req_id, self.cpl_header.tag)


######### IO helper ##################


def is_cxl_io_completion_status_sc(packet) -> bool:
    if not packet.is_cxl_io():
        return False
    if packet.is_cpld():
        return True
    if not packet.is_cpl():
        return False
    return packet.cpl_header.status == CXL_IO_CPL_STATUS.SC


def is_cxl_io_completion_status_ur(packet) -> bool:
    if not packet.is_cxl_io():
        return False
    if not packet.is_cpl():
        return False
    return packet.cpl_header.status == CXL_IO_CPL_STATUS.UR


######################################## CACHE
class CxlCacheBasePacket(BasePacketMixin, CxlCacheBasePacketMixin, RawCxlCacheBasePacket):
    pass


class CxlCacheD2HReqPacket(BasePacketMixin, CxlCacheBasePacketMixin, RawCxlCacheD2HReqPacket):
    pass


class CxlCacheCacheD2HReqPacket(BasePacketMixin, CxlCacheBasePacketMixin, RawCxlCacheD2HReqPacket):
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
        packet.system_header.payload_length = packet.get_size()
        packet.cxl_cache_header.msg_class = CXL_CACHE_MSG_CLASS.D2H_REQ
        packet.d2hreq_header.valid = 1
        packet.d2hreq_header.cache_opcode = opcode
        packet.d2hreq_header.cqid = cqid
        packet.d2hreq_header.cache_id = cache_id
        if addr % 0x40:
            raise Exception("Address must be a multiple of 0x40")
        packet.d2hreq_header.addr = addr >> 6
        return packet

    def get_address(self) -> int:
        return self.d2hreq_header.addr << 6

    def set_cache_id(self, cache_id: int):
        self.d2hreq_header.cache_id = cache_id


class CxlCacheD2HRspPacket(BasePacketMixin, CxlCacheBasePacketMixin, RawCxlCacheD2HRspPacket):
    pass


class CxlCacheCacheD2HRspPacket(BasePacketMixin, CxlCacheBasePacketMixin, RawCxlCacheD2HRspPacket):
    @classmethod
    def create(
        cls,
        uqid: int,
        opcode: CXL_CACHE_D2HRSP_OPCODE,
    ) -> "CxlCacheCacheD2HRspPacket":
        packet = cls()
        packet.system_header.payload_type = SYSTEM_PAYLOAD_TYPE.CXL_CACHE
        packet.system_header.payload_length = packet.get_size()
        packet.cxl_cache_header.msg_class = CXL_CACHE_MSG_CLASS.D2H_RSP
        packet.d2hrsp_header.valid = 1
        packet.d2hrsp_header.uqid = uqid
        packet.d2hrsp_header.cache_opcode = opcode
        return packet


class CxlCacheD2HDataPacket(
    BasePacketMixin, CxlCacheBasePacketMixin, RawCxlCacheD2HDataPacket, PacketDataMixin
):
    pass


class CxlCacheCacheD2HDataPacket(
    BasePacketMixin, CxlCacheBasePacketMixin, RawCxlCacheD2HDataPacket, PacketDataMixin
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

        packet.system_header.payload_length = packet.get_size()
        return packet


class CxlCacheH2DReqPacket(BasePacketMixin, CxlCacheBasePacketMixin, RawCxlCacheH2DReqPacket):
    pass


class CxlCacheCacheH2DReqPacket(BasePacketMixin, CxlCacheBasePacketMixin, RawCxlCacheH2DReqPacket):
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
        if addr % 0x40:
            raise Exception("Address must be a multiple of 0x40")
        packet.h2dreq_header.addr = addr >> 6
        packet.system_header.payload_length = packet.get_size()
        return packet

    def get_address(self) -> int:
        return self.h2dreq_header.addr << 6

    def get_opcode(self) -> CXL_CACHE_H2DREQ_OPCODE:
        return self.h2dreq_header.cache_opcode


class CxlCacheH2DRspPacket(BasePacketMixin, CxlCacheBasePacketMixin, RawCxlCacheH2DRspPacket):
    pass


class CxlCacheCacheH2DRspPacket(BasePacketMixin, CxlCacheBasePacketMixin, RawCxlCacheH2DRspPacket):
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
        packet.system_header.payload_length = packet.get_size()
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
    BasePacketMixin, CxlCacheBasePacketMixin, RawCxlCacheH2DDataPacket, PacketDataMixin
):
    pass


class CxlCacheCacheH2DDataPacket(
    BasePacketMixin, CxlCacheBasePacketMixin, RawCxlCacheH2DDataPacket, PacketDataMixin
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

        packet.system_header.payload_length = packet.get_size()
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
class CxlMemBasePacket(BasePacketMixin, CxlMemBasePacketMixin, RawCxlMemBasePacket):
    pass


class CxlMemM2SReqPacket(BasePacketMixin, CxlMemBasePacketMixin, RawCxlMemM2SReqPacket):
    def is_mem_rd(self) -> bool:
        return self.m2sreq_header.mem_opcode == CXL_MEM_M2SREQ_OPCODE.MEM_RD

    def is_mem_inv(self) -> bool:
        return self.m2sreq_header.mem_opcode == CXL_MEM_M2SREQ_OPCODE.MEM_INV

    def get_address(self) -> int:
        return self.m2sreq_header.addr << 6


class CxlMemM2SRwDPacket(
    BasePacketMixin, CxlMemBasePacketMixin, RawCxlMemM2SRwDPacket, PacketDataMixin
):
    def is_mem_wr(self) -> bool:
        return self.m2srwd_header.mem_opcode == CXL_MEM_M2SRWD_OPCODE.MEM_WR

    def get_address(self) -> int:
        return self.m2srwd_header.addr << 6


class CxlMemM2SBIRspPacket(BasePacketMixin, CxlMemBasePacketMixin, RawCxlMemM2SBIRspPacket):
    pass


class CxlMemS2MBISnpPacket(BasePacketMixin, CxlMemBasePacketMixin, RawCxlMemS2MBISnpPacket):
    def get_address(self) -> int:
        return self.s2mbisnp_header.addr << 6


class CxlMemS2MNDRPacket(BasePacketMixin, CxlMemBasePacketMixin, RawCxlMemS2MNDRPacket):
    pass


class CxlMemS2MDRSPacket(
    BasePacketMixin, CxlMemBasePacketMixin, RawCxlMemS2MDRSPacket, PacketDataMixin
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
        packet.system_header.payload_length = packet.get_size()
        packet.cxl_mem_header.msg_class = CXL_MEM_MSG_CLASS.M2S_REQ
        packet.m2sreq_header.valid = 1
        packet.m2sreq_header.mem_opcode = opcode
        packet.m2sreq_header.meta_field = meta_field
        packet.m2sreq_header.meta_value = meta_value
        packet.m2sreq_header.snp_type = snp_type
        packet.m2sreq_header.ld_id = ld_id
        if addr % 0x40:
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
        if addr % 0x40:
            raise Exception("Address must be a multiple of 0x40")
        packet.m2srwd_header.addr = addr >> 6

        if isinstance(data, int):
            packet.set_data_as_int(data)
        else:
            packet.set_data(data)

        packet.system_header.payload_length = packet.get_size()
        return packet


class CxlMemBIRspPacket(BasePacketMixin, CxlMemBasePacketMixin, RawCxlMemM2SBIRspPacket):
    @classmethod
    def create(
        cls,
        opcode: CXL_MEM_M2SBIRSP_OPCODE,
        bi_id: int = 0,
        bi_tag: int = 0,
    ) -> "CxlMemBIRspPacket":
        packet = cls()
        packet.system_header.payload_type = SYSTEM_PAYLOAD_TYPE.CXL_MEM
        packet.system_header.payload_length = packet.get_size()
        packet.cxl_mem_header.msg_class = CXL_MEM_MSG_CLASS.M2S_BIRSP
        packet.m2sbirsp_header.valid = 1
        packet.m2sbirsp_header.opcode = opcode
        packet.m2sbirsp_header.low_addr = 0
        packet.m2sbirsp_header.bi_id = bi_id
        packet.m2sbirsp_header.bi_tag = bi_tag
        return packet


class CxlMemBISnpPacket(BasePacketMixin, CxlMemBasePacketMixin, RawCxlMemS2MBISnpPacket):
    _tag_counter: int = 0

    @classmethod
    def get_tag(cls, bi_tag) -> int:
        if bi_tag is None:
            bi_tag = cls._tag_counter
            cls._tag_counter = (cls._tag_counter + 1) % 4096
        return bi_tag

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
        packet.system_header.payload_length = packet.get_size()
        packet.cxl_mem_header.msg_class = CXL_MEM_MSG_CLASS.S2M_BISNP
        packet.s2mbisnp_header.valid = 1
        packet.s2mbisnp_header.opcode = opcode
        packet.s2mbisnp_header.bi_id = bi_id
        packet.s2mbisnp_header.bi_tag = cls.get_tag(bi_tag)
        if addr % 0x40:
            raise Exception("Address must be a multiple of 0x40")
        packet.s2mbisnp_header.addr = addr >> 6
        return packet


class CxlMemMemDataPacket(
    BasePacketMixin, CxlMemBasePacketMixin, RawCxlMemS2MDRSPacket, PacketDataMixin
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

        packet.system_header.payload_length = packet.get_size()
        return packet


class CxlMemCmpPacket(BasePacketMixin, CxlMemBasePacketMixin, RawCxlMemS2MNDRPacket):
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
        packet.system_header.payload_length = packet.get_size()
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


############## CCI

class CciPayload:
    def __init__(self, packet, base_offset_bits, fields):
        self._packet = packet  # Instance of PacketBuffer (or subclass)
        self._base = base_offset_bits
        self._fields = {name: (offset, width) for name, offset, width in fields}

    def __getattr__(self, name):
        if name in self._fields:
            offset, width = self._fields[name]
            return self._packet.read_bits(self._base + offset, width)
        raise AttributeError(f"{name} not found")

    def __setattr__(self, name, value):
        if name in {'_packet', '_base', '_fields'}:
            super().__setattr__(name, value)
        elif name in self._fields:
            offset, width = self._fields[name]
            self._packet.write_bits(self._base + offset, width, value)
        else:
            raise AttributeError(f"{name} not found")

class CciBasePacket(BasePacketMixin, CciBasePacketMixin, RawCciBasePacket):
    pass


class CciMessagePacket(BasePacketMixin, CciBasePacketMixin, RawCciMessagePacket, PacketDataMixin):
    @classmethod
    def create(
        cls,
        data: bytes,
        message_category: CCI_MCTP_MESSAGE_CATEGORY,
        opcode: int,
        message_tag: int = 0,
        vendor_specific_status: int = 0,
        return_code: int = 0,
        background_operation: int = 0,
    ) -> "CciMessagePacket":
        packet = cls()
        packet.cci_msg_header.message_category = message_category
        packet.cci_msg_header.command_opcode = opcode
        packet.cci_msg_header.message_tag = message_tag
        packet.cci_msg_header.vendor_specific_extended_status = vendor_specific_status
        packet.cci_msg_header.return_code = return_code
        packet.cci_msg_header.background_operation = background_operation

        length = len(data)
        packet.cci_msg_header.message_payload_length_high = (length >> 16) & 0x1F
        packet.cci_msg_header.message_payload_length_low = length & 0xFFFF
        packet.set_data(data)
        return packet

    def get_message_payload_length(self) -> int:
        return self.message_payload_length_high << 16 | self.message_payload_length_low

    def get_total_size(self) -> int:
        return len(self)

    def get_payload_size(self) -> int:
        return self.cci_msg_header.get_message_payload_length()

    def get_payload(self) -> bytes:
        return self.get_data()


class CciPayloadPacket(BasePacketMixin, CciBasePacketMixin, RawCciPayloadPacket, PacketDataMixin):
    def get_packet(self):
        return CciMessagePacket(self.get_data())

    @classmethod
    def create(cls, data: bytes, index: int = 0) -> "CciPayloadPacket":
        packet = cls()
        packet.cci_header.port_index = index
        packet.system_header.payload_type = SYSTEM_PAYLOAD_TYPE.CCI_MCTP

        if isinstance(data, CciMessagePacket):
            packet.set_data(int.from_bytes(bytes(data.cci_msg_header) + data.get_data(), "little"))
        else:
            packet.set_data(
                int.from_bytes(
                    bytes(data.system_header) + bytes(data.cci_header) + data.get_data(), "little"
                )
            )

        packet.system_header.payload_length = len(packet)
        return packet


class CciRequestPacket(BasePacketMixin, CciBasePacketMixin, RawCciRequestPacket, PacketFieldMixin, PacketDataMixin):
    def get_command_opcode(self) -> int:
        return self.cci_msg_header.command_opcode

    def initialize_common_headers(self):
        self.cci_header.msg_class = CCI_MSG_CLASS.REQ
        self.system_header.payload_type = SYSTEM_PAYLOAD_TYPE.CCI_MCTP
        self.cci_msg_header.message_category = CCI_MCTP_MESSAGE_CATEGORY.REQUEST
        self.cci_msg_header.message_tag = 0
        self.cci_msg_header.command_opcode = 0
        self.cci_msg_header.message_payload_length_high = 0
        self.cci_msg_header.message_payload_length_low = 0
        self.cci_msg_header.return_code = 0
        self.cci_msg_header.vendor_specific_extended_status = 0
        self.cci_msg_header.background_operation = 0
        self.system_header.payload_length = len(self)

    def populate_header_from_ccimessage(self, cci_message):
        header = cci_message.cci_msg_header
        self.cci_msg_header.message_category = header.message_category
        self.cci_msg_header.message_tag = header.message_tag
        self.cci_msg_header.command_opcode = header.command_opcode
        self.cci_msg_header.message_payload_length_high = header.message_payload_length_high
        self.cci_msg_header.message_payload_length_low = header.message_payload_length_low
        self.cci_msg_header.return_code = header.return_code
        self.cci_msg_header.vendor_specific_extended_status = header.vendor_specific_extended_status
        self.cci_msg_header.background_operation = header.background_operation

    @classmethod
    def create_packet(cls, command_opcode: int, payload_length: int = 0) -> "CciRequestPacket":
        packet = cls()
        packet.initialize_common_headers()
        packet.cci_msg_header.command_opcode = command_opcode
        packet.cci_msg_header.message_payload_length_low = payload_length & 0xFFFF
        packet.cci_msg_header.message_payload_length_high = (payload_length >> 16) & 0x1F
        return packet


class GetLdInfoRequestPacket(CciRequestPacket):
    @classmethod
    def create(cls) -> "GetLdInfoRequestPacket":
        return cls.create_packet(CCI_FM_API_COMMAND_OPCODE.GET_LD_INFO)

    @classmethod
    def create_from_cci_message(cls, cci_message: CciMessagePacket) -> "GetLdInfoRequestPacket":
        packet = cls()
        packet.initialize_common_headers()
        packet.populate_header_from_ccimessage(cci_message)
        offset = packet.get_byte_offset(packet.cci_msg_header)
        packet.set_bytes(offset, bytes(cci_message))
        packet.cci_msg_header.command_opcode = CCI_FM_API_COMMAND_OPCODE.GET_LD_INFO
        return packet


class GetLdAllocationsRequestPacket(CciRequestPacket):
    _fields = [
        ("start_ld_id", 0, 7),
        ("ld_allocation_list_limit", 8, 8),
    ]

    def __init__(self):
        super().__init__()
        _, last_offset, last_width = self._fields[-1]
        payload_bits = last_offset + last_width
        payload_bytes = (payload_bits + 7) // 8
        self.set_data(b'\x00' * payload_bytes)

        self.payload = CciPayload(self, self.payload_bit_offset, self._fields)

    @classmethod
    def create(
        cls, start_ld_id: int = 0, ld_allocation_list_limit: int = 0
    ) -> "GetLdAllocationsRequestPacket":
        packet = cls()
        packet.initialize_common_headers()
        packet.cci_msg_header.command_opcode = CCI_FM_API_COMMAND_OPCODE.GET_LD_ALLOCATIONS
        packet.payload.start_ld_id = start_ld_id
        packet.payload.ld_allocation_list_limit = ld_allocation_list_limit
        return packet

    @classmethod
    def create_from_cci_message(
        cls, cci_message: CciMessagePacket
    ) -> "GetLdAllocationsRequestPacket":
        packet = cls()
        packet.initialize_common_headers()
        packet.populate_header_from_ccimessage(cci_message)
        packet.cci_msg_header.command_opcode = CCI_FM_API_COMMAND_OPCODE.GET_LD_ALLOCATIONS
        data = cci_message.get_data()
        packet.get_ld_allocations_request.start_ld_id = int.from_bytes(data[0], "little")
        packet.get_ld_allocations_request.ld_allocation_list_limit = int.from_bytes(data[1], "little")
        return packet


class SetLdAllocationsRequestPacket(CciRequestPacket):
    @classmethod
    def create(
        cls, number_of_lds: int, start_ld_id: int = 0, ld_allocation_list: int = 0
    ) -> "SetLdAllocationsRequestPacket":
        if number_of_lds < 1:
            raise ValueError("Number of LDs must be greater than 0")
        payload_length = 4 + 16 * number_of_lds
        packet = cls.create_packet(CCI_FM_API_COMMAND_OPCODE.SET_LD_ALLOCATIONS, payload_length)

        payload = packet.set_ld_allocations_request_payload
        payload.number_of_lds = number_of_lds
        payload.start_ld_id = start_ld_id
        payload.reserved = 0

        packet.set_dynamic_field_length(number_of_lds * 2 * 8)
        packet.ld_allocation_list = ld_allocation_list
        packet.system_header.payload_length = len(packet)

        return packet

    @classmethod
    def create_from_cci_message(
        cls, cci_message: CciMessagePacket
    ) -> "SetLdAllocationsRequestPacket":
        packet = cls()
        packet.initialize_common_headers()
        packet.populate_header_from_ccimessage(cci_message)

        cci_payload = cci_message.get_data()
        packet.set_ld_allocations_request_payload.reset(cci_payload[:payload_size])
        raw_list = cci_payload[payload_size:]
        packet.ld_allocation_list = [
            int.from_bytes(raw_list[i : i + 8], "little") for i in range(0, len(raw_list), 8)
        ]

        packet.set_dynamic_field_length(
            packet.set_ld_allocations_request_payload.number_of_lds * 2 * 8
        )
        packet.system_header.payload_length = len(packet)

        return packet


class CciResponsePacket(BasePacketMixin, CciBasePacketMixin, RawCciResponsePacket, PacketDataMixin):
    def get_command_opcode(self) -> int:
        return self.cci_msg_header.command_opcode

    def initialize_common_headers(self):
        self.cci_header.msg_class = CCI_MSG_CLASS.RSP
        self.system_header.payload_type = SYSTEM_PAYLOAD_TYPE.CCI_MCTP
        self.system_header.payload_length = len(self)

    def reset_header_data_defaults(self):
        self.cci_msg_header.message_category = CCI_MCTP_MESSAGE_CATEGORY.RESPONSE
        self.cci_msg_header.message_tag = 0
        self.cci_msg_header.command_opcode = 0
        self.cci_msg_header.message_payload_length_high = 0
        self.cci_msg_header.message_payload_length_low = 0
        self.cci_msg_header.return_code = 0
        self.cci_msg_header.vendor_specific_extended_status = 0
        self.cci_msg_header.background_operation = 0

    @classmethod
    def create_packet(cls, command_opcode: int, payload_length: int = 0) -> "CciResponsePacket":
        packet = cls()
        packet.initialize_common_headers()
        packet.reset_header_data_defaults()
        packet.cci_msg_header.command_opcode = command_opcode
        packet.cci_msg_header.message_payload_length_low = payload_length & 0xFFFF
        packet.cci_msg_header.message_payload_length_high = (payload_length >> 16) & 0x1F
        return packet

    def create_ccimessage(self, payload_bytes: bytes) -> "CciMessagePacket":
        header = CciMessageHeaderPacket()
        header.message_category = self.cci_msg_header.message_category
        header.message_tag = self.cci_msg_header.message_tag
        header.command_opcode = self.cci_msg_header.command_opcode
        header.message_payload_length_high = self.cci_msg_header.message_payload_length_high
        header.message_payload_length_low = self.cci_msg_header.message_payload_length_low
        header.return_code = self.cci_msg_header.return_code
        header.vendor_specific_extended_status = self.cci_msg_header.vendor_specific_extended_status
        header.background_operation = self.cci_msg_header.background_operation
        return CciMessagePacket.create(header, payload_bytes)


class GetLdInfoResponsePacket(CciResponsePacket):
    _fields = [
        ("number_of_lds", 0, 7),
        ("memory_granularity", 8, 15),
        ("start_ld_id", 16, 23),
        ("ld_allocation_list_length", 24, 31),
    ]

    def payload_to_bytes(self, byteorder: str) -> bytes:
        return (
            self.payload.memory_size.to_bytes(8, byteorder)
            + self.payload.ld_count.to_bytes(2, byteorder)
            + self.payload.qos_telemetry_capability.to_bytes(1, byteorder)
        )

    @classmethod
    def create(cls, memory_size: int, ld_count: int, message_tag: int) -> "GetLdInfoResponsePacket":
        packet = cls.create_packet(CCI_FM_API_COMMAND_OPCODE.GET_LD_INFO, payload_length=11)
        packet.cci_msg_header.message_tag = message_tag
        packet.payload.memory_size = memory_size
        packet.payload.ld_count = ld_count
        packet.payload.qos_telemetry_capability = 0
        return packet

    def create_ccimessage(self) -> "CciMessagePacket":
        return super().create_ccimessage(self.payload_to_bytes("little"))

    def get_memory_size(self) -> int:
        return self.payload.memory_size

    def get_ld_count(self) -> int:
        return self.payload.ld_count

    def get_qos_telemetry_capability(self) -> int:
        return self.payload.qos_telemetry_capability

    def get_payload_size(self) -> int:
        return self.payload.get_size()


class GetLdAllocationsResponsePacket(CciResponsePacket):
    def payload_to_bytes(self, byteorder: str) -> bytes:
        fields = self.get_ld_allocations_response_payload
        header_bytes = b"".join(
            [
                fields.number_of_lds.to_bytes(1, byteorder),
                fields.memory_granularity.to_bytes(1, byteorder),
                fields.start_ld_id.to_bytes(1, byteorder),
                fields.ld_allocation_list_length.to_bytes(1, byteorder),
            ]
        )
        return header_bytes + self.get_ld_allocation_list()

    @classmethod
    def create(
        cls,
        number_of_lds: int,
        memory_granularity: int,
        start_ld_id: int,
        ld_allocation_list_length: int,
        ld_allocation_list: int,
        message_tag: int,
    ) -> "GetLdAllocationsResponsePacket":
        payload_length = 4 + ld_allocation_list_length * 16
        packet = cls.create_packet(CCI_FM_API_COMMAND_OPCODE.GET_LD_ALLOCATIONS, payload_length)
        packet.cci_msg_header.message_tag = message_tag

        payload = packet.get_ld_allocations_response_payload
        payload.number_of_lds = number_of_lds
        payload.memory_granularity = memory_granularity
        payload.start_ld_id = start_ld_id
        payload.ld_allocation_list_length = ld_allocation_list_length

        packet.set_dynamic_field_length(ld_allocation_list_length * 2 * 8)
        packet.ld_allocation_list = ld_allocation_list
        packet.system_header.payload_length = len(packet)

        return packet

    def create_ccimessage(self) -> "CciMessagePacket":
        return super().create_ccimessage(self.payload_to_bytes("little"))


class SetLdAllocationsResponsePacket(CciResponsePacket):
    def payload_to_bytes(self) -> bytes:
        payload = self.set_ld_allocations_response_payload
        return (
            payload.number_of_lds.to_bytes(1, "little")
            + payload.start_ld_id.to_bytes(1, "little")
            + payload.reserved.to_bytes(2, "little")
            + self.ld_allocation_list
        )

    @classmethod
    def create(
        cls, number_of_lds: int, start_ld_id: int, ld_allocation_list: int, message_tag: int
    ) -> "SetLdAllocationsResponsePacket":
        payload_length = 4 + 16 * number_of_lds
        packet = cls.create_packet(CCI_FM_API_COMMAND_OPCODE.SET_LD_ALLOCATIONS, payload_length)
        packet.cci_msg_header.message_tag = message_tag

        payload = packet.set_ld_allocations_response_payload
        payload.number_of_lds = number_of_lds
        payload.start_ld_id = start_ld_id
        payload.reserved = 0

        packet.set_dynamic_field_length(number_of_lds * 2 * 8)
        packet.ld_allocation_list = ld_allocation_list
        packet.system_header.payload_length = len(packet)

        return packet

    def create_ccimessage(self) -> "CciMessagePacket":
        return super().create_ccimessage(self.payload_to_bytes())
