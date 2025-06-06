"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from typing import Optional

from packet_structs import (
    RawBasePacket,
    RawCxlIoBasePacket,
    RawCxlCacheBasePacket,
    RawCxlMemBasePacket,
    RawCxlIoMemReqPacket,
    RawCxlIoCfgReqPacket,
    RawCxlIoCompletionPacket,
    RawCxlIoCompletionWithDataPacket,
    RawCxlCacheD2HReqPacket,
    RawCxlCacheD2HRspPacket,
    RawCxlCacheD2HDataPacket,
    RawCxlCacheH2DReqPacket,
    RawCxlCacheH2DRspPacket,
    RawCxlCacheH2DDataPacket,
    RawCxlMemM2SReqPacket,
    RawCxlMemM2SRwDPacket,
    RawCxlMemM2SBIRspPacket,
    RawCxlMemS2MBISnpPacket,
    RawCxlMemS2MDRSPacket,
    RawCxlMemS2MNDRPacket,
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
)
from mixin import (
    BasePacketMixin,
    CxlIoBasePacketMixin,
    CxlCacheBasePacketMixin,
    CxlMemBasePacketMixin,
)


class BasePacket(BasePacketMixin, RawBasePacket):
    pass


class CxlIoBasePacket(BasePacketMixin, CxlIoBasePacketMixin, RawCxlIoBasePacket):
    pass


class CxlCacheBasePacket(BasePacketMixin, CxlCacheBasePacketMixin, RawCxlCacheBasePacket):
    pass


class CxlMemBasePacket(BasePacketMixin, CxlMemBasePacketMixin, RawCxlMemBasePacket):
    pass


class CxlIoMemReqPacket(BasePacketMixin, CxlIoBasePacketMixin, RawCxlIoMemReqPacket):
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


class CxlIoMemRdPacket(CxlIoMemReqPacket):
    @classmethod
    def create(cls, addr: int, length: int, req_id: int = 0, tag: int = 0, ld_id: int = 0):
        # if req_id is not None:
        #     req_id = htotlp16(req_id)
        # else:
        #     req_id = 0
        # if tag is None:
        #     tag = cls.get_tag()
        # tag %= 256
        pkt = cls()
        pkt.fill(addr, length, req_id, tag)
        pkt.cxl_io_header.fmt_type = CXL_IO_FMT_TYPE.MRD_64B
        pkt.tlp_prefix.ld_id = ld_id
        pkt.system_header.payload_length = pkt.get_data_size() // 4
        return pkt


class CxlIoMemWrPacket(CxlIoMemReqPacket):
    @classmethod
    def create(cls, addr: int, data: bytes, req_id: int = 0, tag: int = 0, ld_id: int = 0):
        # if req_id is not None:
        #     req_id = htotlp16(req_id)
        # else:
        #     req_id = 0
        # if tag is None:
        #     tag = cls.get_tag()
        # tag %= 256
        pkt = cls()
        pkt.set_data(data)
        pkt.fill(addr, len(data), req_id, tag)
        pkt.cxl_io_header.fmt_type = CXL_IO_FMT_TYPE.MWR_64B
        pkt.tlp_prefix.ld_id = ld_id
        pkt.system_header.payload_length = pkt.get_size() // 4
        return pkt


class CxlIoCfgReqPacket(BasePacketMixin, CxlIoBasePacketMixin, RawCxlIoCfgReqPacket):
    def fill(self, id: int, cfg_addr: int, size: int, req_id: int, tag: int) -> "CxlIoCfgReqPacket":
        self.system_header.payload_type = SYSTEM_PAYLOAD_TYPE.CXL_IO

        self.cxl_io_header.tc = 0b000
        self.cxl_io_header.attr = 0b00
        self.cxl_io_header.at = 0b00
        self.cxl_io_header.length_upper = 0b00
        self.cxl_io_header.length_lower = 0b00000001
        # NOTE: Request ID for CfgRd and CfgWr is always 0
        self.cfg_req_header.req_id = req_id
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
        return self.cfg_req_header.get_transaction_id()


class CxlIoCfgRdPacket(CxlIoCfgReqPacket):
    @classmethod
    def create(
        cls,
        id: int,
        cfg_addr: int,
        size: int,
        is_type0: bool = True,
        req_id: Optional[int] = None,
        tag: Optional[int] = None,
        ld_id: int = 0,
    ) -> "CxlIoCfgRdPacket":
        # if req_id is not None:
        #     req_id = htotlp16(req_id)
        # else:
        #     req_id = 0
        # if tag is None:
        #     tag = cls.get_tag()
        # tag %= 256
        pkt = cls(None)
        pkt.fill(id, cfg_addr, size, req_id, tag)
        pkt.cxl_io_header.fmt_type = (
            CXL_IO_FMT_TYPE.CFG_RD0 if is_type0 else CXL_IO_FMT_TYPE.CFG_RD1
        )
        pkt.system_header.payload_length = pkt.get_size()
        pkt.tlp_prefix.ld_id = ld_id
        return pkt


class CxlIoCfgWrPacket(CxlIoCfgReqPacket):
    @classmethod
    def create(
        cls,
        id: int,
        cfg_addr: int,
        size: int,
        value: int,
        is_type0: bool = True,
        req_id: Optional[int] = None,
        tag: Optional[int] = None,
        ld_id: int = 0,
    ) -> "CxlIoCfgWrPacket":
        # if req_id is not None:
        #     req_id = htotlp16(req_id)
        # else:
        #     req_id = 0
        # if tag is None:
        #     tag = cls.get_tag()
        # tag %= 256
        offset = cfg_addr % 4
        pkt = cls(None)
        pkt.fill(id, cfg_addr, size, req_id, tag)
        pkt.cxl_io_header.fmt_type = (
            CXL_IO_FMT_TYPE.CFG_WR0 if is_type0 else CXL_IO_FMT_TYPE.CFG_WR1
        )
        pkt.tlp_prefix.ld_id = ld_id
        pkt.value = value << (8 * offset)
        pkt.system_header.payload_length = pkt.get_size()
        return pkt

    def get_value(self) -> int:
        cfg_addr, size = self.get_cfg_addr_write_info()
        offset = cfg_addr % 4
        bit_offset = (offset % 4) * 8
        bit_mask = (1 << size * 8) - 1
        return (self.value >> bit_offset) & bit_mask


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
        pkt = cls()
        pkt.system_header.payload_type = SYSTEM_PAYLOAD_TYPE.CXL_IO
        pkt.system_header.payload_length = pkt.get_size()
        pkt.cxl_io_header.fmt_type = CXL_IO_FMT_TYPE.CPL
        pkt.cxl_io_header.length_upper = 0
        pkt.cxl_io_header.length_lower = 0
        pkt.tlp_prefix.ld_id = ld_id

        pkt.cpl_header.cpl_id = htotlp16(cpl_id)
        pkt.cpl_header.status = status
        pkt.cpl_header.byte_count_upper = 0
        pkt.cpl_header.byte_count_lower = 4
        pkt.cpl_header.req_id = htotlp16(req_id)
        pkt.cpl_header.tag = tag

        return pkt

    def get_transaction_id(self) -> int:
        return self.cpl_header.get_transaction_id()


class CxlIoCompletionWithDataPacket(
    BasePacketMixin, CxlIoBasePacketMixin, RawCxlIoCompletionWithDataPacket
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
        pkt = cls()
        pkt.system_header.payload_type = SYSTEM_PAYLOAD_TYPE.CXL_IO
        pkt.cxl_io_header.fmt_type = CXL_IO_FMT_TYPE.CPL_D

        pkt.cxl_io_header.length_upper = extract_upper(pload_len // 4, 2, 10)
        pkt.cxl_io_header.length_lower = extract_lower(pload_len // 4, 8, 10)

        pkt.cpl_header.cpl_id = htotlp16(cpl_id)
        pkt.cpl_header.status = status
        pkt.cpl_header.req_id = htotlp16(req_id)
        pkt.cpl_header.tag = tag

        pkt.cpl_header.byte_count_upper = extract_upper(pload_len, 4, 12)
        pkt.cpl_header.byte_count_lower = extract_lower(pload_len, 8, 12)

        pkt.set_data(data)

        pkt.tlp_prefix.ld_id = ld_id
        pkt.system_header.payload_length = pkt.get_size()

        return pkt

    def get_transaction_id(self) -> int:
        return self.cpl_header.get_transaction_id()


########################################
class CxlCacheD2HReqPacket(BasePacketMixin, CxlCacheBasePacketMixin, RawCxlCacheD2HReqPacket):
    @classmethod
    def create(
        cls,
        addr: int,
        cache_id: int,
        opcode: CXL_CACHE_D2HREQ_OPCODE,
        cqid: int = 0,
    ) -> "CxlCacheD2HReqPacket":
        pkt = cls()
        pkt.system_header.payload_type = SYSTEM_PAYLOAD_TYPE.CXL_CACHE
        pkt.system_header.payload_length = pkt.get_size()
        pkt.cxl_cache_header.msg_class = CXL_CACHE_MSG_CLASS.D2H_REQ
        pkt.d2hreq_header.valid = 1
        pkt.d2hreq_header.cache_opcode = opcode
        pkt.d2hreq_header.cqid = cqid
        pkt.d2hreq_header.cache_id = cache_id
        if addr % 0x40:
            raise Exception("Address must be a multiple of 0x40")
        pkt.d2hreq_header.addr = addr >> 6
        return pkt

    def get_address(self) -> int:
        return self.d2hreq_header.addr << 6

    def set_cache_id(self, cache_id: int):
        self.d2hreq_header.cache_id = cache_id


class CxlCacheD2HRspPacket(BasePacketMixin, CxlCacheBasePacketMixin, RawCxlCacheD2HRspPacket):
    @classmethod
    def create(
        cls,
        uqid: int,
        opcode: CXL_CACHE_D2HRSP_OPCODE,
    ) -> "CxlCacheD2HRspPacket":
        pkt = cls()
        pkt.system_header.payload_type = SYSTEM_PAYLOAD_TYPE.CXL_CACHE
        pkt.system_header.payload_length = pkt.get_size()
        pkt.cxl_cache_header.msg_class = CXL_CACHE_MSG_CLASS.D2H_RSP
        pkt.d2hrsp_header.valid = 1
        pkt.d2hrsp_header.uqid = uqid
        pkt.d2hrsp_header.cache_opcode = opcode
        return pkt


class CxlCacheD2HDataPacket(BasePacketMixin, CxlCacheBasePacketMixin, RawCxlCacheD2HDataPacket):
    @classmethod
    def create(
        cls,
        uqid: int,
        data: int,
    ) -> "CxlCacheD2HDataPacket":
        pkt = cls()
        pkt.system_header.payload_type = SYSTEM_PAYLOAD_TYPE.CXL_CACHE
        pkt.system_header.payload_length = pkt.get_size()
        pkt.cxl_cache_header.msg_class = CXL_CACHE_MSG_CLASS.D2H_DATA
        pkt.d2hdata_header.valid = 1
        pkt.d2hdata_header.uqid = uqid
        pkt.d2hdata_header.poison = 0
        pkt.data = data
        return pkt


class CxlCacheH2DReqPacket(BasePacketMixin, CxlCacheBasePacketMixin, RawCxlCacheH2DReqPacket):
    @classmethod
    def create(
        cls,
        addr: int,
        cache_id: int,
        opcode: CXL_CACHE_H2DREQ_OPCODE,
    ) -> "CxlCacheH2DReqPacket":
        pkt = cls()
        pkt.system_header.payload_type = SYSTEM_PAYLOAD_TYPE.CXL_CACHE
        pkt.system_header.payload_length = pkt.get_size()
        pkt.cxl_cache_header.msg_class = CXL_CACHE_MSG_CLASS.H2D_REQ
        pkt.h2dreq_header.valid = 1
        pkt.h2dreq_header.cache_opcode = opcode
        pkt.h2dreq_header.cache_id = cache_id
        if addr % 0x40:
            raise Exception("Address must be a multiple of 0x40")
        pkt.h2dreq_header.addr = addr >> 6
        return pkt

    def get_address(self) -> int:
        return self.h2dreq_header.addr << 6

    def get_opcode(self) -> CXL_CACHE_H2DREQ_OPCODE:
        return self.h2dreq_header.cache_opcode


class CxlCacheH2DRspPacket(BasePacketMixin, CxlCacheBasePacketMixin, RawCxlCacheH2DRspPacket):
    @classmethod
    def create(
        cls,
        cache_id: int,
        opcode: CXL_CACHE_H2DRSP_OPCODE,
        rsp_data: CXL_CACHE_H2DRSP_CACHE_STATE,
        cqid: int = 0,
    ) -> "CxlCacheH2DRspPacket":
        pkt = cls()
        pkt.system_header.payload_type = SYSTEM_PAYLOAD_TYPE.CXL_CACHE
        pkt.system_header.payload_length = pkt.get_size()
        pkt.cxl_cache_header.msg_class = CXL_CACHE_MSG_CLASS.H2D_RSP
        pkt.h2drsp_header.valid = 1
        pkt.h2drsp_header.cache_opcode = opcode
        pkt.h2drsp_header.cache_id = cache_id
        pkt.h2drsp_header.rsp_data = rsp_data
        pkt.h2drsp_header.cqid = cqid
        return pkt

    def get_opcode(self) -> CXL_CACHE_H2DRSP_OPCODE:
        return self.h2drsp_header.cache_opcode


class CxlCacheH2DDataPacket(BasePacketMixin, CxlCacheBasePacketMixin, RawCxlCacheH2DDataPacket):
    @classmethod
    def create(
        cls,
        cache_id: int,
        data: int,
        cqid: int = 0,
    ) -> "CxlCacheH2DDataPacket":
        pkt = cls()
        pkt.system_header.payload_type = SYSTEM_PAYLOAD_TYPE.CXL_CACHE
        pkt.system_header.payload_length = pkt.get_size()
        pkt.cxl_cache_header.msg_class = CXL_CACHE_MSG_CLASS.H2D_DATA
        pkt.h2ddata_header.valid = 1
        pkt.h2ddata_header.cache_id = cache_id
        pkt.h2ddata_header.cqid = cqid
        pkt.data = data
        return pkt

    def get_cqid(self) -> int:
        return self.h2ddata_header.cqid

    def get_cache_id(self) -> int:
        return self.h2ddata_header.cache_id


########################### CXL.mem


class CxlMemM2SReqPacket(BasePacketMixin, CxlMemBasePacketMixin, RawCxlMemM2SReqPacket):
    pass


class CxlMemM2SRwDPacket(BasePacketMixin, CxlMemBasePacketMixin, RawCxlMemM2SRwDPacket):
    pass


class CxlMemM2SBIRspPacket(BasePacketMixin, CxlMemBasePacketMixin, RawCxlMemM2SBIRspPacket):
    pass


class CxlMemS2MBISnpPacket(BasePacketMixin, CxlMemBasePacketMixin, RawCxlMemS2MBISnpPacket):
    pass


class CxlMemS2MNDRPacket(BasePacketMixin, CxlMemBasePacketMixin, RawCxlMemS2MNDRPacket):
    pass


class CxlMemS2MDRSPacket(BasePacketMixin, CxlMemBasePacketMixin, RawCxlMemS2MDRSPacket):
    pass


class CxlMemMemRdPacket(BasePacketMixin, CxlMemBasePacketMixin, RawCxlMemM2SReqPacket):
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
        pkt = cls()
        pkt.system_header.payload_type = SYSTEM_PAYLOAD_TYPE.CXL_MEM
        pkt.system_header.payload_length = pkt.get_size()
        pkt.cxl_mem_header.msg_class = CXL_MEM_MSG_CLASS.M2S_REQ
        pkt.m2sreq_header.valid = 1
        pkt.m2sreq_header.mem_opcode = opcode
        pkt.m2sreq_header.meta_field = meta_field
        pkt.m2sreq_header.meta_value = meta_value
        pkt.m2sreq_header.snp_type = snp_type
        pkt.m2sreq_header.ld_id = ld_id
        if addr % 0x40:
            raise Exception("Address must be a multiple of 0x40")
        pkt.m2sreq_header.addr = addr >> 6
        return pkt


class CxlMemMemWrPacket(BasePacketMixin, CxlMemBasePacketMixin, RawCxlMemM2SRwDPacket):
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
        pkt = cls()
        pkt.system_header.payload_type = SYSTEM_PAYLOAD_TYPE.CXL_MEM
        pkt.system_header.payload_length = pkt.get_size()
        pkt.cxl_mem_header.msg_class = CXL_MEM_MSG_CLASS.M2S_RWD
        pkt.m2srwd_header.valid = 1
        pkt.m2srwd_header.mem_opcode = opcode
        pkt.m2srwd_header.meta_field = meta_field
        pkt.m2srwd_header.meta_value = meta_value
        pkt.m2srwd_header.snp_type = snp_type
        pkt.m2srwd_header.ld_id = ld_id
        if addr % 0x40:
            raise Exception("Address must be a multiple of 0x40")
        pkt.m2srwd_header.addr = addr >> 6
        pkt.data = data
        return pkt


class CxlMemBIRspPacket(BasePacketMixin, CxlMemBasePacketMixin, RawCxlMemM2SBIRspPacket):
    @classmethod
    def create(
        cls,
        opcode: CXL_MEM_M2SBIRSP_OPCODE,
        bi_id: int = 0,
        bi_tag: int = 0,
    ) -> "CxlMemBIRspPacket":
        pkt = cls()
        pkt.system_header.payload_type = SYSTEM_PAYLOAD_TYPE.CXL_MEM
        pkt.system_header.payload_length = pkt.get_size()
        pkt.cxl_mem_header.msg_class = CXL_MEM_MSG_CLASS.M2S_BIRSP
        pkt.m2sbirsp_header.valid = 1
        pkt.m2sbirsp_header.opcode = opcode
        pkt.m2sbirsp_header.low_addr = 0
        pkt.m2sbirsp_header.bi_id = bi_id
        pkt.m2sbirsp_header.bi_tag = bi_tag
        return pkt


class CxlMemBISnpPacket(BasePacketMixin, CxlMemBasePacketMixin, RawCxlMemS2MBISnpPacket):
    @staticmethod
    def get_tag():
        old_tag = CxlMemBISnpPacket.tag
        CxlMemBISnpPacket.tag += 1
        CxlMemBISnpPacket.tag %= 4096
        return old_tag

    @classmethod
    def create(
        cls,
        addr: int,
        opcode: CXL_MEM_S2MBISNP_OPCODE,
        bi_id: int = 0,
        bi_tag: int = 0,
    ) -> "CxlMemBISnpPacket":
        pkt = cls()
        pkt.system_header.payload_type = SYSTEM_PAYLOAD_TYPE.CXL_MEM
        pkt.system_header.payload_length = pkt.get_size()
        pkt.cxl_mem_header.msg_class = CXL_MEM_MSG_CLASS.S2M_BISNP
        pkt.s2mbisnp_header.valid = 1
        pkt.s2mbisnp_header.opcode = opcode
        pkt.s2mbisnp_header.bi_id = bi_id
        pkt.s2mbisnp_header.bi_tag = bi_tag or cls.get_tag()
        if addr % 0x40:
            raise Exception("Address must be a multiple of 0x40")
        pkt.s2mbisnp_header.addr = addr >> 6
        return pkt


class CxlMemMemDataPacket(BasePacketMixin, CxlMemBasePacketMixin, RawCxlMemS2MDRSPacket):
    @classmethod
    def create(
        cls,
        data: int,
        opcode: CXL_MEM_S2MDRS_OPCODE = CXL_MEM_S2MDRS_OPCODE.MEM_DATA,
        meta_field: CXL_MEM_META_FIELD = CXL_MEM_META_FIELD.NO_OP,
        meta_value: CXL_MEM_META_VALUE = CXL_MEM_META_VALUE.ANY,
        ld_id: int = 0,
    ) -> "CxlMemMemDataPacket":
        pkt = cls()
        pkt.system_header.payload_type = SYSTEM_PAYLOAD_TYPE.CXL_MEM
        pkt.system_header.payload_length = pkt.get_size()
        pkt.cxl_mem_header.msg_class = CXL_MEM_MSG_CLASS.S2M_DRS
        pkt.s2mdrs_header.valid = 1
        pkt.s2mdrs_header.opcode = opcode
        pkt.s2mdrs_header.meta_field = meta_field
        pkt.s2mdrs_header.meta_value = meta_value
        pkt.s2mdrs_header.ld_id = ld_id
        pkt.data = data
        return pkt


class CxlMemCmpPacket(BasePacketMixin, CxlMemBasePacketMixin, RawCxlMemS2MNDRPacket):
    @classmethod
    def create(
        cls,
        opcode: CXL_MEM_S2MNDR_OPCODE = CXL_MEM_S2MNDR_OPCODE.CMP,
        meta_field: CXL_MEM_META_FIELD = CXL_MEM_META_FIELD.NO_OP,
        meta_value: CXL_MEM_META_VALUE = CXL_MEM_META_VALUE.ANY,
        ld_id: int = 0,
    ) -> "CxlMemCmpPacket":
        pkt = cls()
        pkt.system_header.payload_type = SYSTEM_PAYLOAD_TYPE.CXL_MEM
        pkt.system_header.payload_length = pkt.get_size()
        pkt.cxl_mem_header.msg_class = CXL_MEM_MSG_CLASS.S2M_NDR
        pkt.s2mndr_header.valid = 1
        pkt.s2mndr_header.opcode = opcode
        pkt.s2mndr_header.meta_field = meta_field
        pkt.s2mndr_header.meta_value = meta_value
        pkt.s2mndr_header.ld_id = ld_id
        return pkt


def is_cxl_mem_data(packet) -> bool:
    return (
        packet.is_cxl_mem()
        and packet.is_s2mdr()
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
