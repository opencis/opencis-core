"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from typing import Optional

from opencis.cxl.transport.common import TagCounter
from opencis.cxl.transport.packet_structs import (
    _GenCxlIoBasePacket,
    _GenCxlIoMemReqPacket,
    _GenCxlIoCfgReqPacket,
    _GenCxlIoCompletionPacket,
    _GenCxlIoCompletionWithDataPacket,
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
from opencis.cxl.transport.packet_constants import (
    SYSTEM_PAYLOAD_TYPE,
    CXL_IO_FMT_TYPE,
    CXL_IO_CPL_STATUS,
)
from opencis.cxl.transport.mixin import (
    BasePacketMixin,
    PacketDataMixin,
    CxlIoBasePacketMixin,
)


_io_mem_tags = TagCounter(256)
_io_cfg_tags = TagCounter(256)


class CxlIoBasePacket(BasePacketMixin, CxlIoBasePacketMixin, _GenCxlIoBasePacket):
    pass


class CxlIoMemReqPacket(
    BasePacketMixin,
    CxlIoBasePacketMixin,
    _GenCxlIoMemReqPacket,
    PacketDataMixin,
):
    @classmethod
    def get_tag(cls, tag) -> int:
        return _io_mem_tags.next(tag)

    def _fill_common(self, addr: int, length: int, req_id: int, tag: int) -> None:
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
    def create(
        cls, addr: int, length: int, req_id: int = 0, tag: int = None, ld_id: int = 0
    ) -> "CxlIoMemRdPacket":
        packet = cls()
        packet._fill_common(addr, length, htotlp16(req_id), super().get_tag(tag))
        packet.cxl_io_header.fmt_type = CXL_IO_FMT_TYPE.MRD_64B
        packet.tlp_prefix.ld_id = ld_id
        packet.system_header.payload_length = len(packet)
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
    ) -> "CxlIoMemWrPacket":
        packet = cls()
        if isinstance(data, int):
            packet.set_data_as_int(data, length)
        else:
            packet.set_data(data)
            length = len(data)
        packet._fill_common(addr, length, htotlp16(req_id), super().get_tag(tag))
        packet.cxl_io_header.fmt_type = CXL_IO_FMT_TYPE.MWR_64B
        packet.tlp_prefix.ld_id = ld_id
        packet.system_header.payload_length = len(packet)
        return packet


class CxlIoCfgReqPacket(
    BasePacketMixin,
    CxlIoBasePacketMixin,
    _GenCxlIoCfgReqPacket,
    PacketDataMixin,
):
    @classmethod
    def get_tag(cls, tag) -> int:
        return _io_cfg_tags.next(tag)

    def _fill_common(
        self, dest_id: int, cfg_addr: int, size: int, req_id: int, tag: int
    ) -> "CxlIoCfgReqPacket":
        self.system_header.payload_type = SYSTEM_PAYLOAD_TYPE.CXL_IO

        self.cxl_io_header.tc = 0b000
        self.cxl_io_header.attr = 0b00
        self.cxl_io_header.at = 0b00
        self.cxl_io_header.length_upper = 0b00
        self.cxl_io_header.length_lower = 0b00000001
        self.cfg_req_header.req_id = htotlp16(req_id)
        self.cfg_req_header.tag = tag

        # compute byte-enable bits
        if cfg_addr > 0xFFF:
            raise ValueError("Invalid CFG address")
        offset = cfg_addr & 0x3
        if offset + size > 4:
            raise ValueError("Invalid access size")

        first_dw_be = 0
        for i in range(size):
            first_dw_be |= 1 << (offset + i)
        self.cfg_req_header.first_dw_be = first_dw_be
        self.cfg_req_header.last_dw_be = 0

        self.cfg_req_header.dest_id = htotlp16(dest_id)
        self.cfg_req_header.ext_reg_num = (cfg_addr >> 8) & 0x0F
        self.cfg_req_header.reg_num = (cfg_addr >> 2) & 0x3F
        return self

    def get_cfg_addr_read_info(self) -> tuple[int, int]:
        reg_num = (self.cfg_req_header.ext_reg_num << 6) | self.cfg_req_header.reg_num
        return reg_num << 2, 4

    def get_cfg_addr_write_info(self) -> tuple[int, int]:
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

    def get_bus(self) -> int:
        dest_id = tlptoh16(self.cfg_req_header.dest_id)
        return extract_bus_from_bdf(dest_id)

    def get_device(self) -> int:
        dest_id = tlptoh16(self.cfg_req_header.dest_id)
        return extract_device_from_bdf(dest_id)

    def get_function(self) -> int:
        dest_id = tlptoh16(self.cfg_req_header.dest_id)
        return extract_function_from_bdf(dest_id)

    def get_transaction_id(self) -> int:
        return self.build_transaction_id(self.cfg_req_header.req_id, self.cfg_req_header.tag)


class CxlIoCfgRdPacket(CxlIoCfgReqPacket):
    @classmethod
    def create(
        cls,
        dest_id: int,
        cfg_addr: int,
        size: int,
        is_type0: bool = True,
        req_id: int = 0,
        tag: Optional[int] = None,
        ld_id: int = 0,
    ) -> "CxlIoCfgRdPacket":
        packet = cls()
        packet._fill_common(dest_id, cfg_addr, size, req_id, super().get_tag(tag))
        packet.cxl_io_header.fmt_type = (
            CXL_IO_FMT_TYPE.CFG_RD0 if is_type0 else CXL_IO_FMT_TYPE.CFG_RD1
        )
        packet.system_header.payload_length = len(packet)
        packet.tlp_prefix.ld_id = ld_id
        return packet


class CxlIoCfgWrPacket(CxlIoCfgReqPacket):
    @classmethod
    def create(
        cls,
        dest_id: int,
        cfg_addr: int,
        size: int,
        value: int,
        is_type0: bool = True,
        req_id: Optional[int] = 0,
        tag: Optional[int] = None,
        ld_id: int = 0,
    ) -> "CxlIoCfgWrPacket":
        packet = cls()
        packet.set_data_as_int(value << ((cfg_addr & 0x3) * 8))
        packet._fill_common(dest_id, cfg_addr, size, req_id, super().get_tag(tag))
        packet.cxl_io_header.fmt_type = (
            CXL_IO_FMT_TYPE.CFG_WR0 if is_type0 else CXL_IO_FMT_TYPE.CFG_WR1
        )
        packet.tlp_prefix.ld_id = ld_id
        packet.system_header.payload_length = len(packet)
        return packet

    def get_value(self) -> int:
        cfg_addr, size = self.get_cfg_addr_write_info()
        offset = cfg_addr % 4
        bit_offset = (offset % 4) * 8
        bit_mask = (1 << size * 8) - 1
        return (self.get_data_as_int() >> bit_offset) & bit_mask


class CxlIoCompletionPacket(
    BasePacketMixin,
    CxlIoBasePacketMixin,
    _GenCxlIoCompletionPacket,
):
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
        packet.system_header.payload_length = len(packet)
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
    BasePacketMixin,
    CxlIoBasePacketMixin,
    _GenCxlIoCompletionWithDataPacket,
    PacketDataMixin,
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
            packet.set_data_as_int(int(data), pload_len)
        else:
            packet.set_data(bytes(data))

        packet.tlp_prefix.ld_id = ld_id
        packet.system_header.payload_length = len(packet)

        return packet

    def get_transaction_id(self) -> int:
        return self.build_transaction_id(self.cpl_header.req_id, self.cpl_header.tag)


# ------------------------------ Helper Functions ------------------------------#
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
