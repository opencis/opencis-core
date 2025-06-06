"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from typing import Optional
from packet_structs import RawCxlIoMemReqPacket, RawCxlIoCfgReqPacket
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
from mixin import (
    BasePacketMixin,
    CxlIoBasePacketMixin,
    CXL_IO_FMT_TYPE,
    CXL_IO_PROTOCOL,
    PAYLOAD_TYPE,
)


class CxlIoMemReqPacket(BasePacketMixin, CxlIoBasePacketMixin, RawCxlIoMemReqPacket):
    def fill(self, addr: int, length: int, req_id: int, tag: int):
        address_offset = addr % 4
        length_dword = (address_offset + length + 3) // 4

        self.system_header.payload_type = PAYLOAD_TYPE.CXL_IO
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
        self.system_header.payload_type = PAYLOAD_TYPE.CXL_IO

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
        pkt.system_header.payload_length = CxlIoCfgRdPacket.get_size()
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
        pkt.system_header.payload_length = CxlIoCfgWrPacket.get_size()
        return pkt

    def get_value(self) -> int:
        cfg_addr, size = self.get_cfg_addr_write_info()
        offset = cfg_addr % 4
        bit_offset = (offset % 4) * 8
        bit_mask = (1 << size * 8) - 1
        return (self.value >> bit_offset) & bit_mask
