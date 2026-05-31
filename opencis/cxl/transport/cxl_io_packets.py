"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from typing import Optional

from opencis.cxl.transport.common import TagCounter
from opencis.cxl.transport.packet_structs import (
    _GenCxlIoBasePacket,
    _GenCxlIoCfgRdPacket,
    _GenCxlIoCfgWrPacket,
    _GenCxlIoMemRdPacket,
    _GenCxlIoMemWrPacket,
    _GenCxlIoCompletionPacket,
)
from opencis.util.number import (
    htotlp16,
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
    CxlIoMemReqPacketMixin,
    CxlIoCfgReqPacketMixin,
)


_io_mem_tags = TagCounter(256)
_io_cfg_tags = TagCounter(256)


class CxlIoBasePacket(BasePacketMixin, CxlIoBasePacketMixin, _GenCxlIoBasePacket):
    pass


class CxlIoMemRdPacket(
    _GenCxlIoMemRdPacket,
    BasePacketMixin,
    CxlIoBasePacketMixin,
    CxlIoMemReqPacketMixin,
):
    @classmethod
    def acquire_tag(cls, tag) -> int:
        return _io_mem_tags.next(tag)

    @classmethod
    def create(
        cls, addr: int, length: int, req_id: int = 0, tag: int = None, ld_id: int = 0
    ) -> "CxlIoMemRdPacket":
        addr_upper_bytes = (addr >> 8).to_bytes(7, byteorder="big")
        addr_upper = int.from_bytes(addr_upper_bytes, byteorder="little")
        addr_lower = (addr & 0xFF) >> 2

        address_offset = addr % 4
        length_dword = (address_offset + length + 3) // 4
        bytes_enabled = (1 << length) - 1
        bytes_enabled_with_offset = bytes_enabled << address_offset
        first_dw_be = bytes_enabled_with_offset & 0xF
        last_dw_be = (
            (bytes_enabled_with_offset >> ((length_dword - 1) * 4)) & 0xF if length_dword > 1 else 0
        )
        packet = super().create(
            SYSTEM_PAYLOAD_TYPE.CXL_IO,  # system_header__payload_type,
            ld_id,  # tlp_prefix__ld_id,
            CXL_IO_FMT_TYPE.MRD_64B,  # cxl_io_header__fmt_type,
            length_dword & 0x300,  # cxl_io_header__length_upper,
            length_dword & 0xFF,  # cxl_io_header__length_lower,
            htotlp16(req_id),  # mreq_header__req_id,
            cls.acquire_tag(tag),  # mreq_header__tag,
            first_dw_be,  # mreq_header__first_dw_be,
            last_dw_be,  # mreq_header__last_dw_be,
            addr_upper,  # mreq_header__addr_upper,
            addr_lower,  # mreq_header__addr_lower,
            None,  # data
        )
        return packet


class CxlIoMemReqPacket(
    BasePacketMixin,
    CxlIoBasePacketMixin,
    CxlIoMemReqPacketMixin,
    PacketDataMixin,
):
    pass


class CxlIoMemWrPacket(
    _GenCxlIoMemWrPacket,
    BasePacketMixin,
    CxlIoBasePacketMixin,
    CxlIoMemReqPacketMixin,
    PacketDataMixin,
):
    @classmethod
    def acquire_tag(cls, tag) -> int:
        return _io_mem_tags.next(tag)

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
        addr_upper_bytes = (addr >> 8).to_bytes(7, byteorder="big")
        addr_upper = int.from_bytes(addr_upper_bytes, byteorder="little")
        addr_lower = (addr & 0xFF) >> 2

        address_offset = addr % 4
        length_dword = (address_offset + length + 3) // 4
        bytes_enabled = (1 << length) - 1
        bytes_enabled_with_offset = bytes_enabled << address_offset
        first_dw_be = bytes_enabled_with_offset & 0xF
        last_dw_be = (
            (bytes_enabled_with_offset >> ((length_dword - 1) * 4)) & 0xF if length_dword > 1 else 0
        )
        if isinstance(data, int):
            data = data.to_bytes(length, byteorder="little")
        else:
            # Already bytes — validate and zero-pad to the expected length if needed
            assert len(data) <= length, (
                f"data length {len(data)} exceeds declared length {length}"
            )
            data = data.ljust(length, b"\x00")
        packet = super().create(
            SYSTEM_PAYLOAD_TYPE.CXL_IO,  # system_header__payload_type,
            ld_id,  # tlp_prefix__ld_id,
            CXL_IO_FMT_TYPE.MWR_64B,  # cxl_io_header__fmt_type,
            length_dword & 0x300,  # cxl_io_header__length_upper,
            length_dword & 0xFF,  # cxl_io_header__length_lower,
            htotlp16(req_id),  # mreq_header__req_id,
            cls.acquire_tag(tag),  # mreq_header__tag,
            first_dw_be,  # mreq_header__first_dw_be,
            last_dw_be,  # mreq_header__last_dw_be,
            addr_upper,  # mreq_header__addr_upper,
            addr_lower,  # mreq_header__addr_lower,
            data,  # data
        )
        return packet


class CxlIoCfgReqPacket(
    BasePacketMixin,
    CxlIoBasePacketMixin,
    CxlIoCfgReqPacketMixin,
):
    pass


class CxlIoCfgRdPacket(
    _GenCxlIoCfgRdPacket,
    BasePacketMixin,
    CxlIoBasePacketMixin,
    CxlIoCfgReqPacketMixin,
):
    @classmethod
    def acquire_tag(cls, tag) -> int:
        return _io_cfg_tags.next(tag)

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
        offset = cfg_addr & 0x3
        if cfg_addr > 0xFFF:
            raise ValueError("Invalid CFG address")
        if offset + size > 4:
            raise ValueError("Invalid access size")
        first_dw_be = ((1 << size) - 1) << offset
        packet = super().create(
            SYSTEM_PAYLOAD_TYPE.CXL_IO,  # system_header__payload_type,
            ld_id,  # tlp_prefix__ld_id,
            (
                CXL_IO_FMT_TYPE.CFG_RD0 if is_type0 else CXL_IO_FMT_TYPE.CFG_RD1
            ),  # cxl_io_header__fmt_type,
            0,  # cxl_io_header__length_upper,
            1,  # cxl_io_header__length_lower,
            htotlp16(req_id),  # mreq_header__req_id,
            cls.acquire_tag(tag),  # mreq_header__tag,
            first_dw_be,  # cfg_req_header__first_dw_be,
            0,  # cfg_req_header__last_dw_be,
            htotlp16(dest_id),  # cfg_req_header__dest_id,
            (cfg_addr >> 8) & 0x0F,  # cfg_req_header__ext_reg_num,
            (cfg_addr >> 2) & 0x3F,  # cfg_req_header__reg_num,
            None,  # data
        )
        return packet


class CxlIoCfgWrPacket(
    _GenCxlIoCfgWrPacket,
    BasePacketMixin,
    CxlIoBasePacketMixin,
    CxlIoCfgReqPacketMixin,
    PacketDataMixin,
):
    @classmethod
    def acquire_tag(cls, tag) -> int:
        return _io_cfg_tags.next(tag)

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
        offset = cfg_addr & 3
        val = value << (offset * 8)
        data = val.to_bytes((val.bit_length() + 7) // 8 or 1, "little")
        offset = cfg_addr & 0x3
        if cfg_addr > 0xFFF:
            raise ValueError("Invalid CFG address")
        if offset + size > 4:
            raise ValueError("Invalid access size")

        packet = super().create(
            SYSTEM_PAYLOAD_TYPE.CXL_IO,  # system_header__payload_type,
            ld_id,  # tlp_prefix__ld_id,
            (
                CXL_IO_FMT_TYPE.CFG_WR0 if is_type0 else CXL_IO_FMT_TYPE.CFG_WR1
            ),  # cxl_io_header__fmt_type,
            0,  # cxl_io_header__length_upper,
            1,  # cxl_io_header__length_lower,
            htotlp16(req_id),  # mreq_header__req_id,
            cls.acquire_tag(tag),  # mreq_header__tag,
            ((1 << size) - 1) << offset,  # cfg_req_header__first_dw_be,
            0,  # cfg_req_header__last_dw_be,
            htotlp16(dest_id),  # cfg_req_header__dest_id,
            (cfg_addr >> 8) & 0x0F,  # cfg_req_header__ext_reg_num,
            (cfg_addr >> 2) & 0x3F,  # cfg_req_header__reg_num,
            data,
        )
        return packet

    def get_value(self) -> int:
        cfg_addr, size = self.get_cfg_addr_write_info()
        offset = cfg_addr % 4
        bit_offset = (offset % 4) * 8
        bit_mask = (1 << size * 8) - 1
        return (self.get_data_as_int() >> bit_offset) & bit_mask


class CxlIoCompletionPacket(
    _GenCxlIoCompletionPacket,
    BasePacketMixin,
    CxlIoBasePacketMixin,
    PacketDataMixin,
):
    @classmethod
    def create(
        cls,
        req_id: int,
        tag: int,
        cpl_id: int,
        data: int,
        length: int = 0,
        status: CXL_IO_CPL_STATUS = CXL_IO_CPL_STATUS.SC,
        ld_id: int = 0,
    ) -> "CxlIoCompletionPacket":
        packet = cls()
        if data is not None:
            fmt_type = CXL_IO_FMT_TYPE.CPL_D
            length_upper = extract_upper(length // 4, 2, 10)
            length_lower = extract_lower(length // 4, 8, 10)
            byte_count_upper = extract_upper(length, 4, 12)
            byte_count_lower = extract_lower(length, 8, 12)
            if length == 0:
                length = (data.bit_length() + 7) // 8 or 1
            data = data.to_bytes(length, byteorder="little")
        else:
            fmt_type = CXL_IO_FMT_TYPE.CPL
            length_upper = 0
            length_lower = 0
            byte_count_upper = 0
            byte_count_lower = 4

        packet = super().create(
            SYSTEM_PAYLOAD_TYPE.CXL_IO,  # system_header__payload_type,
            ld_id,  # tlp_prefix__ld_id,
            fmt_type,  # cxl_io_header__fmt_type,
            length_upper,  # cxl_io_header__length_upper,
            length_lower,  # cxl_io_header__length_lower,
            htotlp16(cpl_id),  # cpl_header__cpl_id,
            status,  # cpl_header__status,
            byte_count_upper,  # cpl_header__byte_count_upper,
            byte_count_lower,  # cpl_header__byte_count_lower,
            htotlp16(req_id),  # cpl_header__req_id,
            tag,  # cpl_header__tag,
            data,  # data
        )
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
