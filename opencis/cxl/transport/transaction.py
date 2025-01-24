"""
 Copyright (c) 2024, Eeum, Inc.

 This software is licensed under the terms of the Revised BSD License.
 See LICENSE for details.
"""

from enum import IntEnum
from typing import cast, Optional

from opencis.cxl.cci.common import CCI_FM_API_COMMAND_OPCODE
from opencis.util.unaligned_bit_structure import (
    UnalignedBitStructure,
    BitField,
    ByteField,
    DynamicByteField,
    StructureField,
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
from opencis.cxl.transport.common import (
    BasePacket,
    SYSTEM_HEADER_END,
    PAYLOAD_TYPE,
)


#
# Packet Definitions for PAYLOAD_TYPE.SIDEBAND
#
class SIDEBAND_TYPES(IntEnum):
    CONNECTION_REQUEST = 0
    CONNECTION_ACCEPT = 1
    CONNECTION_REJECT = 2
    CONNECTION_DISCONNECTED = 3


class SidebandHeaderPacket(UnalignedBitStructure):
    type: SIDEBAND_TYPES
    _fields = [ByteField("type", 0, 0)]


SIDEBAND_HEADER_START = SYSTEM_HEADER_END + 1
SIDEBAND_HEADER_END = SIDEBAND_HEADER_START + SidebandHeaderPacket.get_size() - 1
SIDEBAND_FIELD_START = SIDEBAND_HEADER_END + 1


class BaseSidebandPacket(BasePacket):
    sideband_header: SidebandHeaderPacket
    _fields = BasePacket._fields + [
        StructureField(
            "sideband_header",
            SIDEBAND_HEADER_START,
            SIDEBAND_HEADER_END,
            SidebandHeaderPacket,
        ),
    ]

    @staticmethod
    def create(type: SIDEBAND_TYPES) -> "BaseSidebandPacket":
        packet = BaseSidebandPacket()
        packet.system_header.payload_type = PAYLOAD_TYPE.SIDEBAND
        packet.system_header.payload_length = len(packet)
        packet.sideband_header.type = type
        return packet

    def get_type(self) -> SIDEBAND_TYPES:
        return self.sideband_header.type

    def is_connection_request(self) -> bool:
        return self.get_type() == SIDEBAND_TYPES.CONNECTION_REQUEST

    def is_connection_accept(self) -> bool:
        return self.get_type() == SIDEBAND_TYPES.CONNECTION_ACCEPT

    def is_connection_reject(self) -> bool:
        return self.get_type() == SIDEBAND_TYPES.CONNECTION_REJECT


class SidebandConnectionRequestPacket(BasePacket):
    sideband_header: SidebandHeaderPacket
    port: int

    _fields = BasePacket._fields + [
        StructureField(
            "sideband_header",
            SIDEBAND_HEADER_START,
            SIDEBAND_HEADER_END,
            SidebandHeaderPacket,
        ),
        ByteField("port", SIDEBAND_FIELD_START, SIDEBAND_FIELD_START + 0x00),
    ]

    @staticmethod
    def create(port_index: int) -> "SidebandConnectionRequestPacket":
        packet = SidebandConnectionRequestPacket()
        packet.system_header.payload_type = PAYLOAD_TYPE.SIDEBAND
        packet.system_header.payload_length = len(packet)
        packet.sideband_header.type = SIDEBAND_TYPES.CONNECTION_REQUEST
        packet.port = port_index
        return packet


#
# Packet Definitions for PAYLOAD_TYPE.CXL_IO
#
class CXL_IO_PROTOCOL(IntEnum):
    MEM_RD = 0
    MEM_WR = 1
    CFG_RD = 2  # NOTE: Assume CFG_RD is CFG_RD0
    CFG_WR = 3  # NOTE: Assume CFG_WR is CFG_WR0
    CPL = 4
    CPLD = 5
    CFG_RD1 = 6
    CFG_WR1 = 7
    CPL_MEM = 8
    CPLD_MEM = 9


class CXL_IO_FMT_TYPE(IntEnum):
    MRD_32B = 0b00000000
    MRD_64B = 0b00100000
    MRD_LK_32B = 0b00000001
    MRD_LK_64B = 0b00100001
    MWR_32B = 0b01000000
    MWR_64B = 0b01100000
    IO_RD = 0b00000010
    IO_WR = 0b01000010
    CFG_RD0 = 0b00000100
    CFG_WR0 = 0b01000100
    CFG_RD1 = 0b00000101
    CFG_WR1 = 0b01000101
    TCFG_RD = 0b00011011
    D_MRW_32B = 0b01011011
    D_MRW_64B = 0b01111011
    CPL = 0b00001010
    CPL_D = 0b01001010
    CPL_LK = 0b00001011
    CPL_D_LK = 0b01001011
    FETCH_ADD_32B = 0b01001100
    FETCH_ADD_64B = 0b01101100
    SWAP_32B = 0b01001101
    SWAP_64B = 0b01101101
    CAS_32B = 0b01001110
    CAS_64B = 0b01101110


class TLP_Prefix(UnalignedBitStructure):
    pcie_base_spec_defined: int
    ld_id: int
    reserved: int

    _fields = [
        BitField("pcie_base_spec_defined", 0, 7),  # 8 bits: PCIe Base Specification Defined
        BitField("ld_id", 8, 23),  # 16 bits: LD-ID[15:0]
        BitField("reserved", 24, 31),  # 8 bits: Reserved
    ]


class CxlIoHeader(UnalignedBitStructure):
    fmt_type: CXL_IO_FMT_TYPE
    t9: int
    tc: int
    t8: int
    attr_b2: int
    rsvd: int
    th: int
    td: int
    ep: int
    attr: int
    at: int
    length_upper: int
    length_lower: int
    _fields = [
        BitField("fmt_type", 0, 7),
        BitField("th", 8, 8),
        BitField("rsvd", 9, 9),
        BitField("attr_b2", 10, 10),
        BitField("t8", 11, 11),
        BitField("tc", 12, 14),
        BitField("t9", 15, 15),
        BitField("length_upper", 16, 17),
        BitField("at", 18, 19),
        BitField("attr", 20, 21),
        BitField("ep", 22, 22),
        BitField("td", 23, 23),
        BitField("length_lower", 24, 31),
    ]


TLP_Prefix_START = SYSTEM_HEADER_END + 1
TLP_Prefix_END = TLP_Prefix_START + TLP_Prefix.get_size() - 1

CXL_IO_BASE_HEADER_START = TLP_Prefix_END + 1
CXL_IO_BASE_HEADER_END = CXL_IO_BASE_HEADER_START + CxlIoHeader.get_size() - 1
CXL_IO_BASE_FIELD_START = CXL_IO_BASE_HEADER_END + 1


class CxlIoBasePacket(BasePacket):
    tag: int = 0
    tlp_prefix: TLP_Prefix
    cxl_io_header: CxlIoHeader
    _fields = BasePacket._fields + [
        StructureField("tlp_prefix", TLP_Prefix_START, TLP_Prefix_END, TLP_Prefix),
        StructureField(
            "cxl_io_header",
            CXL_IO_BASE_HEADER_START,
            CXL_IO_BASE_HEADER_END,
            CxlIoHeader,
        ),
    ]

    def is_cfg_type0(self) -> bool:
        return self.cxl_io_header.fmt_type in (
            CXL_IO_FMT_TYPE.CFG_RD0,
            CXL_IO_FMT_TYPE.CFG_WR0,
        )

    def is_cfg_type1(self) -> bool:
        return self.cxl_io_header.fmt_type in (
            CXL_IO_FMT_TYPE.CFG_RD1,
            CXL_IO_FMT_TYPE.CFG_WR1,
        )

    def is_cfg_read(self) -> bool:
        return self.cxl_io_header.fmt_type in (
            CXL_IO_FMT_TYPE.CFG_RD0,
            CXL_IO_FMT_TYPE.CFG_RD1,
        )

    def is_cfg_write(self) -> bool:
        return self.cxl_io_header.fmt_type in (
            CXL_IO_FMT_TYPE.CFG_WR0,
            CXL_IO_FMT_TYPE.CFG_WR1,
        )

    def is_cpl(self) -> bool:
        return self.cxl_io_header.fmt_type == CXL_IO_FMT_TYPE.CPL

    def is_cpld(self) -> bool:
        return self.cxl_io_header.fmt_type == CXL_IO_FMT_TYPE.CPL_D

    def is_cfg(self) -> bool:
        return (
            self.is_cfg_type0()
            or self.is_cfg_type1()
            or self.cxl_io_header.fmt_type == CXL_IO_FMT_TYPE.CPL
            or self.cxl_io_header.fmt_type == CXL_IO_FMT_TYPE.CPL_D
        )

    def is_mmio(self) -> bool:
        return self.cxl_io_header.fmt_type in (
            CXL_IO_FMT_TYPE.MRD_32B,
            CXL_IO_FMT_TYPE.MRD_64B,
            CXL_IO_FMT_TYPE.MWR_32B,
            CXL_IO_FMT_TYPE.MWR_64B,
        )

    def is_mem_read(self) -> bool:
        return self.cxl_io_header.fmt_type in (
            CXL_IO_FMT_TYPE.MRD_32B,
            CXL_IO_FMT_TYPE.MRD_64B,
        )

    def is_mem_write(self) -> bool:
        return self.cxl_io_header.fmt_type in (
            CXL_IO_FMT_TYPE.MWR_32B,
            CXL_IO_FMT_TYPE.MWR_64B,
        )

    @staticmethod
    def get_tag() -> int:
        old_tag = CxlIoBasePacket.tag
        CxlIoBasePacket.tag += 1
        CxlIoBasePacket.tag %= 256
        return old_tag

    @staticmethod
    def build_transaction_id(req_id: int, tag: int) -> int:
        tid = (req_id << 8) | tag
        return tid

    def get_transaction_id(self) -> int:
        raise Exception("get_transaction_id must be implemented by a child class")


class CxlIoMReqHeader(UnalignedBitStructure):
    req_id: int
    tag: int
    first_dw_be: int
    last_dw_be: int
    addr_upper: int
    addr_lower: int
    ph: int
    _fields = [
        BitField("req_id", 0, 15),
        BitField("tag", 16, 23),
        BitField("first_dw_be", 24, 27),
        BitField("last_dw_be", 28, 31),
        BitField("addr_upper", 32, 87),
        BitField("rsvd", 88, 89),
        BitField("addr_lower", 90, 95),
    ]

    def get_transaction_id(self) -> int:
        return CxlIoBasePacket.build_transaction_id(self.req_id, self.tag)


CXL_IO_MREQ_HEADER_START = CXL_IO_BASE_FIELD_START
CXL_IO_MREQ_HEADER_END = CXL_IO_MREQ_HEADER_START + CxlIoMReqHeader.get_size() - 1
CXL_IO_MREQ_FIELD_START = CXL_IO_MREQ_HEADER_END + 1


class CxlIoMemReqPacket(CxlIoBasePacket):
    mreq_header: CxlIoMReqHeader
    _fields = CxlIoBasePacket._fields + [
        StructureField(
            "mreq_header",
            CXL_IO_MREQ_HEADER_START,
            CXL_IO_MREQ_HEADER_END,
            CxlIoMReqHeader,
        ),
    ]

    def fill(self, addr: int, length: int, req_id: int, tag: int) -> "CxlIoMemRdPacket":
        address_offset = addr % 4

        # `length` field from the TLP header is measured in DWORDs.
        length_dword = (address_offset + length + 3) // 4

        self.system_header.payload_type = PAYLOAD_TYPE.CXL_IO
        self.cxl_io_header.length_upper = length_dword & 0x300
        self.cxl_io_header.length_lower = length_dword & 0xFF
        self.mreq_header.req_id = req_id
        self.mreq_header.tag = tag

        bytes_enabled = (1 << length) - 1
        bytes_enabled_with_offset = bytes_enabled << address_offset
        first_be = bytes_enabled_with_offset & 0xF
        last_be = 0
        if length_dword > 1:
            last_be = (bytes_enabled_with_offset >> (length_dword - 1) * 4) & 0xF
        self.mreq_header.first_dw_be = first_be
        self.mreq_header.last_dw_be = last_be

        addr_upper_bytes = (addr >> 8).to_bytes(7, byteorder="big")
        self.mreq_header.addr_upper = int.from_bytes(addr_upper_bytes, byteorder="little")
        self.mreq_header.addr_lower = (addr & 0xFF) >> 2

    def get_transaction_id(self) -> int:
        return self.mreq_header.get_transaction_id()

    def get_address(self) -> int:
        addr = 0
        addr_upper_bytes = self.mreq_header.addr_upper.to_bytes(7, byteorder="little")
        addr |= int.from_bytes(addr_upper_bytes, byteorder="big") << 8
        addr |= self.mreq_header.addr_lower << 2
        return addr

    def get_data_size(self) -> int:
        size = (self.cxl_io_header.length_upper << 8) | (self.cxl_io_header.length_lower & 0xFF)
        return size * 4


class CxlIoMemRdPacket(CxlIoMemReqPacket):
    @classmethod
    def create(
        cls,
        addr: int,
        length: int,
        req_id: Optional[int] = None,
        tag: Optional[int] = None,
        ld_id: int = 0,
    ) -> "CxlIoMemRdPacket":
        if req_id is not None:
            req_id = htotlp16(req_id)
        else:
            req_id = 0
        if tag is None:
            tag = cls.get_tag()
        tag %= 256

        packet = CxlIoMemRdPacket()
        packet.fill(addr, length, req_id, tag)
        packet.cxl_io_header.fmt_type = CXL_IO_FMT_TYPE.MRD_64B
        packet.tlp_prefix.ld_id = ld_id
        packet.system_header.payload_length = CxlIoMemRdPacket.get_size()
        return packet


class CxlIoMemWrPacket(CxlIoMemReqPacket):
    data: int
    # TODO: Support dynamic data size. Fixed to 8 for now.
    _fields = CxlIoMemReqPacket._fields + [
        DynamicByteField("data", CXL_IO_MREQ_FIELD_START, 0x0),
    ]

    @classmethod
    def create(
        cls,
        addr: int,
        length: int,
        data: int,
        req_id: Optional[int] = None,
        tag: Optional[int] = None,
        ld_id: int = 0,
    ) -> "CxlIoMemWrPacket":
        if req_id is not None:
            req_id = htotlp16(req_id)
        else:
            req_id = 0
        if tag is None:
            tag = cls.get_tag()
        tag %= 256

        packet = CxlIoMemWrPacket()
        packet.fill(addr, length, req_id, tag)
        packet.cxl_io_header.fmt_type = CXL_IO_FMT_TYPE.MWR_64B
        packet.tlp_prefix.ld_id = ld_id
        packet.set_dynamic_field_length(length)
        packet.data = data
        packet.system_header.payload_length = len(packet)
        return packet


class CxlIoCfgReqHeader(UnalignedBitStructure):
    req_id: int
    tag: int
    first_dw_be: int
    last_dw_be: int
    dest_id: int
    ext_reg_num: int
    rsvd: int
    r: int
    reg_num: int
    _fields = [
        BitField("req_id", 0, 15),
        BitField("tag", 16, 23),
        BitField("first_dw_be", 24, 27),
        BitField("last_dw_be", 28, 31),
        BitField("dest_id", 32, 47),
        BitField("ext_reg_num", 48, 51),
        BitField("rsvd", 52, 55),
        BitField("r", 56, 57),
        BitField("reg_num", 58, 63),
    ]

    def get_transaction_id(self) -> int:
        return CxlIoBasePacket.build_transaction_id(self.req_id, self.tag)


CXL_IO_CFG_REQ_HEADER_START = CXL_IO_BASE_FIELD_START
CXL_IO_CFG_REQ_HEADER_END = CXL_IO_CFG_REQ_HEADER_START + CxlIoCfgReqHeader.get_size() - 1
CXL_IO_CFG_REQ_FIELD_START = CXL_IO_CFG_REQ_HEADER_END + 1


class CxlIoCfgReqPacket(CxlIoBasePacket):
    cfg_req_header: CxlIoCfgReqHeader
    _fields = CxlIoBasePacket._fields + [
        StructureField(
            "cfg_req_header",
            CXL_IO_CFG_REQ_HEADER_START,
            CXL_IO_CFG_REQ_HEADER_END,
            CxlIoCfgReqHeader,
        ),
    ]

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
    _fields = CxlIoCfgReqPacket._fields

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
        if req_id is not None:
            req_id = htotlp16(req_id)
        else:
            req_id = 0
        if tag is None:
            tag = cls.get_tag()
        tag %= 256

        packet = CxlIoCfgRdPacket()
        packet.fill(id, cfg_addr, size, req_id, tag)
        packet.cxl_io_header.fmt_type = (
            CXL_IO_FMT_TYPE.CFG_RD0 if is_type0 else CXL_IO_FMT_TYPE.CFG_RD1
        )
        packet.system_header.payload_length = CxlIoCfgRdPacket.get_size()
        packet.tlp_prefix.ld_id = ld_id
        return packet


class CxlIoCfgWrPacket(CxlIoCfgReqPacket):
    value: int
    _fields = CxlIoCfgReqPacket._fields + [
        ByteField("value", CXL_IO_CFG_REQ_FIELD_START, CXL_IO_CFG_REQ_FIELD_START + 0x03),
    ]

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
        if req_id is not None:
            req_id = htotlp16(req_id)
        else:
            req_id = 0
        if tag is None:
            tag = cls.get_tag()
        tag %= 256

        offset = cfg_addr % 4
        packet = CxlIoCfgWrPacket()
        packet.fill(id, cfg_addr, size, req_id, tag)
        packet.cxl_io_header.fmt_type = (
            CXL_IO_FMT_TYPE.CFG_WR0 if is_type0 else CXL_IO_FMT_TYPE.CFG_WR1
        )
        packet.tlp_prefix.ld_id = ld_id
        packet = cast(CxlIoCfgWrPacket, packet)
        packet.value = value << (8 * offset)
        packet.system_header.payload_length = CxlIoCfgWrPacket.get_size()
        return packet

    def get_value(self) -> int:
        cfg_addr, size = self.get_cfg_addr_write_info()
        offset = cfg_addr % 4
        bit_offset = (offset % 4) * 8
        bit_mask = (1 << size * 8) - 1
        return (self.value >> bit_offset) & bit_mask


class CXL_IO_CPL_STATUS(IntEnum):
    SC = 0b000
    UR = 0b001
    RRS = 0b010
    CA = 0b100


class CxlIoCompletionHeader(UnalignedBitStructure):
    cpl_id: int
    byte_count_upper: int
    bcm: int
    status: CXL_IO_CPL_STATUS
    byte_count_lower: int
    req_id: int
    tag: int
    rsvd: int
    lower_addr: int
    _fields = [
        BitField("cpl_id", 0, 15),
        BitField("byte_count_upper", 16, 19),
        BitField("bcm", 20, 20),
        BitField("status", 21, 23),
        BitField("byte_count_lower", 24, 31),
        BitField("req_id", 32, 47),
        BitField("tag", 48, 55),
        BitField("lower_addr", 56, 62),
        BitField("rsvd", 63, 63),
    ]

    def get_transaction_id(self) -> int:
        return CxlIoBasePacket.build_transaction_id(self.req_id, self.tag)


CXL_IO_CPL_HEADER_START = CXL_IO_BASE_FIELD_START
CXL_IO_CPL_HEADER_END = CXL_IO_CPL_HEADER_START + CxlIoCompletionHeader.get_size() - 1
CXL_IO_CPL_FIELD_START = CXL_IO_CPL_HEADER_END + 1


class CxlIoCompletionPacket(CxlIoBasePacket):
    cpl_header: CxlIoCompletionHeader
    _fields = CxlIoBasePacket._fields + [
        StructureField(
            "cpl_header",
            CXL_IO_CPL_HEADER_START,
            CXL_IO_CPL_HEADER_END,
            CxlIoCompletionHeader,
        ),
    ]

    @staticmethod
    def create(
        req_id: int,
        tag: int,
        cpl_id: int = 0,
        status: CXL_IO_CPL_STATUS = CXL_IO_CPL_STATUS.SC,
        ld_id: int = 0,
    ) -> "CxlIoCompletionPacket":
        packet = CxlIoCompletionPacket()
        packet.system_header.payload_type = PAYLOAD_TYPE.CXL_IO
        packet.system_header.payload_length = len(packet)
        packet.cxl_io_header.fmt_type = CXL_IO_FMT_TYPE.CPL
        packet.cxl_io_header.length_upper = 0b000
        packet.cxl_io_header.length_lower = 0b00000000
        packet.tlp_prefix.ld_id = ld_id

        packet.cpl_header.cpl_id = htotlp16(cpl_id)
        packet.cpl_header.status = status
        packet.cpl_header.byte_count_upper = 0
        packet.cpl_header.byte_count_lower = 4
        packet.cpl_header.req_id = htotlp16(req_id)
        packet.cpl_header.tag = tag
        return packet

    def get_transaction_id(self) -> int:
        return self.cpl_header.get_transaction_id()


class CxlIoCompletionWithDataPacket(CxlIoBasePacket):
    cpl_header: CxlIoCompletionHeader
    id: int
    data: int

    # TODO: Support dynamic data size. Fixed to 8 for now.
    _fields = CxlIoBasePacket._fields + [
        StructureField(
            "cpl_header",
            CXL_IO_CPL_HEADER_START,
            CXL_IO_CPL_HEADER_END,
            CxlIoCompletionHeader,
        ),
        DynamicByteField("data", CXL_IO_CPL_FIELD_START, 0x0),
    ]

    @staticmethod
    def create(
        req_id: int,
        tag: int,
        data: int,
        cpl_id: int = 0,
        status: CXL_IO_CPL_STATUS = CXL_IO_CPL_STATUS.SC,
        pload_len=0x04,
        ld_id: int = 0,
    ) -> "CxlIoCompletionWithDataPacket":
        # for config reads, always 1 DWORD (4 bytes)

        packet = CxlIoCompletionWithDataPacket()
        packet.system_header.payload_type = PAYLOAD_TYPE.CXL_IO
        packet.cxl_io_header.fmt_type = CXL_IO_FMT_TYPE.CPL_D

        # convert to DWORDs
        packet.cxl_io_header.length_upper = extract_upper(pload_len // 4, 2, 10)
        packet.cxl_io_header.length_lower = extract_lower(pload_len // 4, 8, 10)

        packet.cpl_header.cpl_id = htotlp16(cpl_id)
        packet.cpl_header.status = status
        packet.cpl_header.req_id = htotlp16(req_id)
        packet.cpl_header.tag = tag

        packet.cpl_header.byte_count_upper = extract_upper(pload_len, 4, 12)
        packet.cpl_header.byte_count_lower = extract_lower(pload_len, 8, 12)

        packet.set_dynamic_field_length(pload_len)
        packet.data = data

        packet.tlp_prefix.ld_id = ld_id

        packet.system_header.payload_length = len(packet)

        return packet

    def get_transaction_id(self) -> int:
        return self.cpl_header.get_transaction_id()


def is_cxl_io_completion_status_sc(packet: BasePacket) -> bool:
    if not packet.is_cxl_io():
        return False
    cxl_io_packet = cast(CxlIoBasePacket, packet)
    if cxl_io_packet.is_cpld():
        return True
    if not cxl_io_packet.is_cpl():
        return False
    cpl_packet = cast(CxlIoCompletionPacket, packet)
    return cpl_packet.cpl_header.status == CXL_IO_CPL_STATUS.SC


def is_cxl_io_completion_status_ur(packet: BasePacket) -> bool:
    if not packet.is_cxl_io():
        return False
    cxl_io_packet = cast(CxlIoBasePacket, packet)
    if not cxl_io_packet.is_cpl():
        return False
    cpl_packet = cast(CxlIoCompletionPacket, packet)
    return cpl_packet.cpl_header.status == CXL_IO_CPL_STATUS.UR


#
# Packet Definitions for PAYLOAD_TYPE.CXL_CACHE
#


class CXL_CACHE_MSG_CLASS(IntEnum):
    D2H_REQ = 1
    D2H_RSP = 2
    D2H_DATA = 3
    H2D_REQ = 4
    H2D_RSP = 5
    H2D_DATA = 6


class CxlCacheHeaderPacket(UnalignedBitStructure):
    port_index: int
    msg_class: CXL_CACHE_MSG_CLASS
    _fields = [ByteField("port_index", 0, 0), ByteField("msg_class", 1, 1)]


CXL_CACHE_HEADER_START = SYSTEM_HEADER_END + 1
CXL_CACHE_HEADER_END = CXL_CACHE_HEADER_START + CxlCacheHeaderPacket.get_size() - 1
CXL_CACHE_FIELD_START = CXL_CACHE_HEADER_END + 1


class CxlCacheBasePacket(BasePacket):
    cxl_cache_header: CxlCacheHeaderPacket
    _fields = BasePacket._fields + [
        StructureField(
            "cxl_cache_header",
            CXL_CACHE_HEADER_START,
            CXL_CACHE_HEADER_END,
            CxlCacheHeaderPacket,
        ),
    ]

    def is_d2hreq(self) -> bool:
        return self.cxl_cache_header.msg_class == CXL_CACHE_MSG_CLASS.D2H_REQ

    def is_d2hrsp(self) -> bool:
        return self.cxl_cache_header.msg_class == CXL_CACHE_MSG_CLASS.D2H_RSP

    def is_d2hdata(self) -> bool:
        return self.cxl_cache_header.msg_class == CXL_CACHE_MSG_CLASS.D2H_DATA

    def is_h2dreq(self) -> bool:
        return self.cxl_cache_header.msg_class == CXL_CACHE_MSG_CLASS.H2D_REQ

    def is_h2drsp(self) -> bool:
        return self.cxl_cache_header.msg_class == CXL_CACHE_MSG_CLASS.H2D_RSP

    def is_h2ddata(self) -> bool:
        return self.cxl_cache_header.msg_class == CXL_CACHE_MSG_CLASS.H2D_DATA


# Table 3-22
class CXL_CACHE_D2HREQ_OPCODE(IntEnum):
    CACHE_RD_CURR = 0b00001
    CACHE_RD_OWN = 0b00010
    CACHE_RD_SHARED = 0b00011
    CACHE_RD_ANY = 0b00100
    CACHE_RD_OWN_NO_DATA = 0b00101
    CACHE_I_TO_M_WR = 0b00110
    CACHE_WR_CUR = 0b00111
    CACHE_CL_FLUSH = 0b01000
    CACHE_CLEAN_EVICT = 0b01001
    CACHE_DIRTY_EVICT = 0b01010
    CACHE_CLEAN_EVICT_NO_DATA = 0b01011
    CACHE_WEAKLY_ORDERED_WR_INV = 0b01100
    CACHE_WEAKLY_ORDERED_WR_INV_F = 0b01101
    CACHE_WR_INV = 0b01110
    CACHE_CACHE_FLUSHED = 0b10000


# Table 3-14
class CXL_CACHE_NON_TEMPORAL_ENCODINGS(IntEnum):
    DEFAULT = 0
    LRU = 1


# Table 3-13
class CxlCacheD2HReqHeader(UnalignedBitStructure):
    valid: int
    cache_opcode: CXL_CACHE_D2HREQ_OPCODE
    cqid: int
    nt: CXL_CACHE_NON_TEMPORAL_ENCODINGS
    cache_id: int
    addr: int
    rsvd: int
    _fields = [
        BitField("valid", 0, 0),
        BitField("cache_opcode", 1, 5),
        BitField("cqid", 6, 17),
        BitField("nt", 18, 18),
        BitField("cache_id", 19, 22),
        BitField("addr", 23, 68),
        BitField("rsvd", 69, 71),
    ]


# Table 3-25
class CXL_CACHE_D2HRSP_OPCODE(IntEnum):
    RSP_I_HIT_I = 0b00100
    RSP_V_HIT_V = 0b00110
    RSP_I_HIT_SE = 0b00101
    RSP_S_HIT_SE = 0b00001
    RSP_S_FWD_M = 0b00111
    RSP_I_FWD_M = 0b01111
    RSP_V_FWD_V = 0b10110


# Table 3-15
class CxlCacheD2HRspHeader(UnalignedBitStructure):
    valid: int
    cache_opcode: CXL_CACHE_D2HRSP_OPCODE
    uqid: int
    rsvd: int
    _fields = [
        BitField("valid", 0, 0),
        BitField("cache_opcode", 1, 5),
        BitField("uqid", 6, 17),
        BitField("rsvd", 18, 23),
    ]


# Table 3-16
class CxlCacheD2HDataHeader(UnalignedBitStructure):
    valid: int
    uqid: int
    bogus: int
    poison: int
    bep: int
    rsvd: int
    _fields = [
        BitField("valid", 0, 0),
        BitField("uqid", 1, 12),
        BitField("bogus", 13, 13),
        BitField("poison", 14, 14),
        BitField("bep", 15, 15),
        BitField("rsvd", 16, 23),
    ]


# Table 3-26
class CXL_CACHE_H2DREQ_OPCODE(IntEnum):
    SNP_DATA = 0b001
    SNP_INV = 0b010
    SNP_CUR = 0b011


# Table 3-17
class CxlCacheH2DReqHeader(UnalignedBitStructure):
    valid: int
    cache_opcode: CXL_CACHE_H2DREQ_OPCODE
    addr: int
    uqid: int
    cache_id: int
    rsvd: int
    _fields = [
        BitField("valid", 0, 0),
        BitField("cache_opcode", 1, 3),
        BitField("addr", 4, 49),
        BitField("uqid", 50, 61),
        BitField("cache_id", 62, 65),
        BitField("rsvd", 66, 71),
    ]


# Table 3-27
class CXL_CACHE_H2DRSP_OPCODE(IntEnum):
    WRITE_PULL = 0b0001
    GO = 0b0100
    GO_WRITE_PULL = 0b0101
    EXT_CMP = 0b0110
    GO_WRITE_PULL_DROP = 0b1000
    RSVD = 0b1100
    FAST_GO_WRITE_PULL = 0b1101
    GO_ERR_WRITE_PUL = 0b1111


# Table 3-19
class CXL_CACHE_H2DRSP_PRE(IntEnum):
    HOST_CACHE_MISS_LOCAL_CPU_SOCKET = 0b00
    HOST_CACHE_HIT = 0b01
    HOST_CACHE_MISS_REMOTE_CPU_SOCKET = 0b10
    RSVD = 0b11


# Table 3-20
class CXL_CACHE_H2DRSP_CACHE_STATE(IntEnum):
    INVALID = 0b0011
    SHARED = 0b0001
    EXCLUSIVE = 0b0010
    MODIFIED = 0b0110
    ERROR = 0b0100


# Table 3-18
class CxlCacheH2DRspHeader(UnalignedBitStructure):
    valid: int
    cache_opcode: CXL_CACHE_H2DRSP_OPCODE
    rsp_data: int  # Could be CXL_CACHE_H2DRSP_CACHE_STATE
    rsp_pre: CXL_CACHE_H2DRSP_PRE
    cqid: int
    cache_id: int
    rsvd: int
    _fields = [
        BitField("valid", 0, 0),
        BitField("cache_opcode", 1, 4),
        BitField("rsp_data", 5, 16),
        BitField("rsp_pre", 17, 18),
        BitField("cqid", 19, 30),
        BitField("cache_id", 31, 34),
        BitField("rsvd", 35, 39),
    ]


# Table 3-21
class CxlCacheH2DDataHeader(UnalignedBitStructure):
    valid: int
    cqid: int
    poison: int
    go_err: int
    cache_id: int
    rsvd: int
    _fields = [
        BitField("valid", 0, 0),
        BitField("cqid", 1, 12),
        BitField("poison", 13, 13),
        BitField("go_err", 14, 14),
        BitField("cache_id", 15, 18),
        BitField("rsvd", 19, 23),
    ]


D2HREQ_HEADER_START = CXL_CACHE_HEADER_END + 1
D2HREQ_HEADER_END = D2HREQ_HEADER_START + CxlCacheD2HReqHeader.get_size() - 1
D2HREQ_FIELD_START = D2HREQ_HEADER_END + 1


class CxlCacheD2HReqPacket(CxlCacheBasePacket):
    d2hreq_header: CxlCacheD2HReqHeader
    _fields = CxlCacheBasePacket._fields + [
        StructureField(
            "d2hreq_header",
            D2HREQ_HEADER_START,
            D2HREQ_HEADER_END,
            CxlCacheD2HReqHeader,
        ),
    ]

    def get_address(self) -> int:
        return self.d2hreq_header.addr << 6

    def set_cache_id(self, cache_id: int):
        self.d2hreq_header.cache_id = cache_id


D2HRSP_HEADER_START = CXL_CACHE_HEADER_END + 1
D2HRSP_HEADER_END = D2HRSP_HEADER_START + CxlCacheD2HRspHeader.get_size() - 1
D2HRSP_FIELD_START = D2HRSP_HEADER_END + 1


class CxlCacheD2HRspPacket(CxlCacheBasePacket):
    d2hrsp_header: CxlCacheD2HRspHeader
    _fields = CxlCacheBasePacket._fields + [
        StructureField(
            "d2hrsp_header",
            D2HRSP_HEADER_START,
            D2HRSP_HEADER_END,
            CxlCacheD2HRspHeader,
        ),
    ]


D2HDATA_HEADER_START = CXL_CACHE_HEADER_END + 1
D2HDATA_HEADER_END = D2HDATA_HEADER_START + CxlCacheD2HDataHeader.get_size() - 1
D2HDATA_FIELD_START = D2HDATA_HEADER_END + 1


class CxlCacheD2HDataPacket(CxlCacheBasePacket):
    d2hdata_header: CxlCacheD2HDataHeader
    data: int
    _fields = CxlCacheBasePacket._fields + [
        StructureField(
            "d2hdata_header",
            D2HRSP_HEADER_START,
            D2HRSP_HEADER_END,
            CxlCacheD2HDataHeader,
        ),
        ByteField("data", D2HDATA_FIELD_START, D2HDATA_FIELD_START + 63),
    ]


H2DREQ_HEADER_START = CXL_CACHE_HEADER_END + 1
H2DREQ_HEADER_END = H2DREQ_HEADER_START + CxlCacheH2DReqHeader.get_size() - 1
H2DREQ_FIELD_START = H2DREQ_HEADER_END + 1


class CxlCacheH2DReqPacket(CxlCacheBasePacket):
    h2dreq_header: CxlCacheH2DReqHeader
    _fields = CxlCacheBasePacket._fields + [
        StructureField(
            "h2dreq_header",
            H2DREQ_HEADER_START,
            H2DREQ_HEADER_END,
            CxlCacheH2DReqHeader,
        ),
    ]

    def get_address(self) -> int:
        return self.h2dreq_header.addr << 6

    def get_opcode(self) -> CXL_CACHE_H2DREQ_OPCODE:
        return self.h2dreq_header.cache_opcode


H2DRSP_HEADER_START = CXL_CACHE_HEADER_END + 1
H2DRSP_HEADER_END = H2DRSP_HEADER_START + CxlCacheH2DRspHeader.get_size() - 1
H2DRSP_FIELD_START = H2DRSP_HEADER_END + 1


class CxlCacheH2DRspPacket(CxlCacheBasePacket):
    h2drsp_header: CxlCacheH2DRspHeader
    _fields = CxlCacheBasePacket._fields + [
        StructureField(
            "h2drsp_header",
            H2DRSP_HEADER_START,
            H2DRSP_HEADER_END,
            CxlCacheH2DRspHeader,
        ),
    ]

    def get_opcode(self) -> CXL_CACHE_H2DRSP_OPCODE:
        return self.h2drsp_header.cache_opcode


H2DDATA_HEADER_START = CXL_CACHE_HEADER_END + 1
H2DDATA_HEADER_END = H2DDATA_HEADER_START + CxlCacheH2DDataHeader.get_size() - 1
H2DDATA_FIELD_START = H2DDATA_HEADER_END + 1


class CxlCacheH2DDataPacket(CxlCacheBasePacket):
    h2ddata_header: CxlCacheH2DDataHeader
    data: int
    _fields = CxlCacheBasePacket._fields + [
        StructureField(
            "h2ddata_header",
            H2DDATA_HEADER_START,
            H2DDATA_HEADER_END,
            CxlCacheH2DDataHeader,
        ),
        ByteField("data", H2DDATA_FIELD_START, H2DDATA_FIELD_START + 63),
    ]

    def get_cqid(self) -> int:
        return self.h2ddata_header.cqid

    def get_cache_id(self) -> int:
        return self.h2ddata_header.cache_id


# Helper classes
class CxlCacheCacheD2HReqPacket(CxlCacheD2HReqPacket):
    @staticmethod
    # read length is assumed to be 64 for now
    def create(
        addr: int,
        cache_id: int,
        opcode: CXL_CACHE_D2HREQ_OPCODE,
        cqid: int = 0,
    ) -> "CxlCacheCacheD2HReqPacket":
        packet = CxlCacheCacheD2HReqPacket()
        packet.system_header.payload_type = PAYLOAD_TYPE.CXL_CACHE
        packet.system_header.payload_length = len(packet)
        packet.cxl_cache_header.msg_class = CXL_CACHE_MSG_CLASS.D2H_REQ
        packet.d2hreq_header.valid = 0b1
        packet.d2hreq_header.cache_opcode = opcode
        packet.d2hreq_header.cqid = cqid
        packet.d2hreq_header.cache_id = cache_id
        if addr % 0x40:
            raise Exception("Address must be a multiple of 0x40")
        packet.d2hreq_header.addr = addr >> 6
        return packet


class CxlCacheCacheD2HRspPacket(CxlCacheD2HRspPacket):
    @staticmethod
    # read length is assumed to be 64 for now
    def create(uqid: int, opcode: CXL_CACHE_D2HRSP_OPCODE) -> "CxlCacheCacheD2HRspPacket":
        packet = CxlCacheCacheD2HRspPacket()
        packet.system_header.payload_type = PAYLOAD_TYPE.CXL_CACHE
        packet.system_header.payload_length = len(packet)
        packet.cxl_cache_header.msg_class = CXL_CACHE_MSG_CLASS.D2H_RSP
        packet.d2hrsp_header.valid = 0b1
        packet.d2hrsp_header.uqid = uqid
        packet.d2hrsp_header.cache_opcode = opcode
        return packet


class CxlCacheCacheD2HDataPacket(CxlCacheD2HDataPacket):
    @staticmethod
    def create(uqid: int, data: int) -> "CxlCacheCacheD2HDataPacket":
        packet = CxlCacheCacheD2HDataPacket()
        packet.system_header.payload_type = PAYLOAD_TYPE.CXL_CACHE
        packet.system_header.payload_length = len(packet)
        packet.cxl_cache_header.msg_class = CXL_CACHE_MSG_CLASS.D2H_DATA
        packet.d2hdata_header.valid = 0b1
        packet.d2hdata_header.uqid = uqid
        packet.d2hdata_header.poison = 0b0
        packet.data = data
        return packet


class CxlCacheCacheH2DReqPacket(CxlCacheH2DReqPacket):
    @staticmethod
    # read length is assumed to be 64 for now
    def create(
        addr: int, cache_id: int, opcode: CXL_CACHE_H2DREQ_OPCODE
    ) -> "CxlCacheCacheH2DReqPacket":
        packet = CxlCacheCacheH2DReqPacket()
        packet.system_header.payload_type = PAYLOAD_TYPE.CXL_CACHE
        packet.system_header.payload_length = len(packet)
        packet.cxl_cache_header.msg_class = CXL_CACHE_MSG_CLASS.H2D_REQ
        packet.h2dreq_header.valid = 0b1
        packet.h2dreq_header.cache_opcode = opcode
        packet.h2dreq_header.cache_id = cache_id
        if addr % 0x40:
            raise Exception("Address must be a multiple of 0x40")
        packet.h2dreq_header.addr = addr >> 6
        return packet


class CxlCacheCacheH2DRspPacket(CxlCacheH2DRspPacket):
    @staticmethod
    # read length is assumed to be 64 for now
    def create(
        cache_id: int,
        opcode: CXL_CACHE_H2DRSP_OPCODE,
        rsp_data: CXL_CACHE_H2DRSP_CACHE_STATE,
        cqid: int = 0,
    ) -> "CxlCacheCacheH2DRspPacket":
        packet = CxlCacheCacheH2DRspPacket()
        packet.system_header.payload_type = PAYLOAD_TYPE.CXL_CACHE
        packet.system_header.payload_length = len(packet)
        packet.cxl_cache_header.msg_class = CXL_CACHE_MSG_CLASS.H2D_RSP
        packet.h2drsp_header.valid = 0b1
        packet.h2drsp_header.cache_opcode = opcode
        packet.h2drsp_header.cache_id = cache_id
        packet.h2drsp_header.rsp_data = rsp_data
        packet.h2drsp_header.cqid = cqid
        return packet


class CxlCacheCacheH2DDataPacket(CxlCacheH2DDataPacket):
    @staticmethod
    def create(cache_id: int, data: int, cqid: int = 0) -> "CxlCacheCacheH2DDataPacket":
        packet = CxlCacheCacheH2DDataPacket()
        packet.system_header.payload_type = PAYLOAD_TYPE.CXL_CACHE
        packet.system_header.payload_length = len(packet)
        packet.cxl_cache_header.msg_class = CXL_CACHE_MSG_CLASS.H2D_DATA
        packet.h2ddata_header.valid = 0b1
        packet.h2ddata_header.cache_id = cache_id
        packet.h2ddata_header.cqid = cqid
        packet.data = data
        return packet


def is_cxl_cache_h2d_data(packet: BasePacket) -> bool:
    if not packet.is_cxl_cache():
        return False
    cxl_cache_packet = cast(CxlCacheH2DDataPacket, packet)
    return cxl_cache_packet.is_h2ddata() and cxl_cache_packet.h2ddata_header.valid == 1


def is_cxl_cache_d2h_data(packet: BasePacket) -> bool:
    if not packet.is_cxl_cache():
        return False
    cxl_cache_packet = cast(CxlCacheD2HDataPacket, packet)
    return cxl_cache_packet.is_d2hdata() and cxl_cache_packet.d2hdata_header.valid == 1


#
# Packet Definitions for PAYLOAD_TYPE.CXL_MEM
#

# TODO: Support tag


class CXL_MEM_MSG_CLASS(IntEnum):
    M2S_REQ = 1
    M2S_RWD = 2
    M2S_BIRSP = 3
    S2M_BISNP = 4
    S2M_NDR = 5
    S2M_DRS = 6


class CxlMemHeaderPacket(UnalignedBitStructure):
    port_index: int
    msg_class: CXL_MEM_MSG_CLASS
    _fields = [ByteField("port_index", 0, 0), ByteField("msg_class", 1, 1)]


CXL_MEM_HEADER_START = SYSTEM_HEADER_END + 1
CXL_MEM_HEADER_END = CXL_MEM_HEADER_START + CxlMemHeaderPacket.get_size() - 1
CXL_MEM_FIELD_START = CXL_MEM_HEADER_END + 1


class CxlMemBasePacket(BasePacket):
    cxl_mem_header: CxlMemHeaderPacket
    _fields = BasePacket._fields + [
        StructureField(
            "cxl_mem_header",
            CXL_MEM_HEADER_START,
            CXL_MEM_HEADER_END,
            CxlMemHeaderPacket,
        ),
    ]

    def is_m2sreq(self) -> bool:
        return self.cxl_mem_header.msg_class == CXL_MEM_MSG_CLASS.M2S_REQ

    def is_m2srwd(self) -> bool:
        return self.cxl_mem_header.msg_class == CXL_MEM_MSG_CLASS.M2S_RWD

    def is_m2sbirsp(self) -> bool:
        return self.cxl_mem_header.msg_class == CXL_MEM_MSG_CLASS.M2S_BIRSP

    def is_s2mbisnp(self) -> bool:
        return self.cxl_mem_header.msg_class == CXL_MEM_MSG_CLASS.S2M_BISNP

    def is_s2mndr(self) -> bool:
        return self.cxl_mem_header.msg_class == CXL_MEM_MSG_CLASS.S2M_NDR

    def is_s2mdrs(self) -> bool:
        return self.cxl_mem_header.msg_class == CXL_MEM_MSG_CLASS.S2M_DRS


# CXL.mem M2S common definition
class CXL_MEM_META_FIELD(IntEnum):
    META0_STATE = 0b00
    NO_OP = 0b11


class CXL_MEM_META_VALUE(IntEnum):
    INVALID = 0b00
    ANY = 0b10
    SHARED = 0b11


class CXL_MEM_M2S_SNP_TYPE(IntEnum):
    NO_OP = 0b000
    SNP_DATA = 0b001
    SNP_CUR = 0b010
    SNP_INV = 0b011


# CXL.mem M2S Request (Req)
class CXL_MEM_M2SREQ_OPCODE(IntEnum):
    MEM_INV = 0b0000
    MEM_RD = 0b0001
    MEM_RD_DATA = 0b0010
    MEM_RD_FWD = 0b0011
    MEM_WR_FWD = 0b0100
    MEM_SPEC_RD = 0b1000
    MEM_INV_NT = 0b1001
    MEM_CLN_EVCT = 0b1010


class CxlMemM2SReqHeader(UnalignedBitStructure):
    valid: int
    mem_opcode: CXL_MEM_M2SREQ_OPCODE
    snp_type: CXL_MEM_M2S_SNP_TYPE
    meta_field: CXL_MEM_META_FIELD
    meta_value: CXL_MEM_META_VALUE
    tag: int
    addr: int
    ld_id: int
    rsvd: int
    tc: int
    padding: int
    _fields = [
        BitField("valid", 0, 0),
        BitField("mem_opcode", 1, 4),
        BitField("snp_type", 5, 7),
        BitField("meta_field", 8, 9),
        BitField("meta_value", 10, 11),
        BitField("tag", 12, 27),
        BitField("addr", 28, 73),
        BitField("ld_id", 74, 77),
        BitField("rsvd", 78, 97),
        BitField("tc", 98, 99),
        # padding to align to the byte boundary. Not part of the CXL spec
        BitField("padding", 100, 103),
    ]


M2SREQ_HEADER_START = CXL_MEM_HEADER_END + 1
M2SREQ_HEADER_END = M2SREQ_HEADER_START + CxlMemM2SReqHeader.get_size() - 1
M2SREQ_FIELD_START = M2SREQ_HEADER_END + 1


class CxlMemM2SReqPacket(CxlMemBasePacket):
    m2sreq_header: CxlMemM2SReqHeader
    _fields = CxlMemBasePacket._fields + [
        StructureField(
            "m2sreq_header",
            M2SREQ_HEADER_START,
            M2SREQ_HEADER_END,
            CxlMemM2SReqHeader,
        ),
    ]

    def is_mem_rd(self) -> bool:
        return self.m2sreq_header.mem_opcode == CXL_MEM_M2SREQ_OPCODE.MEM_RD

    def is_mem_inv(self) -> bool:
        return self.m2sreq_header.mem_opcode == CXL_MEM_M2SREQ_OPCODE.MEM_INV

    def get_address(self) -> int:
        return self.m2sreq_header.addr << 6


# CXL.mem M2S Request with Data (RwD)
class CXL_MEM_M2SRWD_OPCODE(IntEnum):
    MEM_WR = 0b0001
    MEM_WR_PTL = 0b0010
    BI_CONFLICT = 0b0100


class CxlMemM2SRwDHeader(UnalignedBitStructure):
    valid: int
    mem_opcode: CXL_MEM_M2SRWD_OPCODE
    snp_type: CXL_MEM_M2S_SNP_TYPE
    meta_field: CXL_MEM_META_FIELD
    meta_value: CXL_MEM_META_VALUE
    tag: int
    addr: int
    poison: int
    bep: int
    ld_id: int
    rsvd: int
    tc: int
    _fields = [
        BitField("valid", 0, 0),
        BitField("mem_opcode", 1, 4),
        BitField("snp_type", 5, 7),
        BitField("meta_field", 8, 9),
        BitField("meta_value", 10, 11),
        BitField("tag", 12, 27),
        BitField("addr", 28, 73),
        BitField("poison", 74, 74),
        BitField("bep", 75, 75),
        BitField("ld_id", 76, 79),
        BitField("rsvd", 80, 101),
        BitField("tc", 102, 103),
    ]


M2SRWD_HEADER_START = CXL_MEM_HEADER_END + 1
M2SRWD_HEADER_END = M2SRWD_HEADER_START + CxlMemM2SRwDHeader.get_size() - 1
M2SRWD_FIELD_START = M2SRWD_HEADER_END + 1


class CxlMemM2SRwDPacket(CxlMemBasePacket):
    m2srwd_header: CxlMemM2SRwDHeader
    data: int
    _fields = CxlMemBasePacket._fields + [
        StructureField(
            "m2srwd_header",
            M2SRWD_HEADER_START,
            M2SRWD_HEADER_END,
            CxlMemM2SRwDHeader,
        ),
        ByteField("data", M2SRWD_FIELD_START, M2SRWD_FIELD_START + 63),
    ]

    def is_mem_wr(self) -> bool:
        return self.m2srwd_header.mem_opcode == CXL_MEM_M2SRWD_OPCODE.MEM_WR

    def get_address(self) -> int:
        return self.m2srwd_header.addr << 6


# CXL.mem M2S Back-Invalidate Response (BIRsp)
class CXL_MEM_M2SBIRSP_OPCODE(IntEnum):
    BIRSP_I = 0b0000
    BIRSP_S = 0b0001
    BIRSP_E = 0b0010
    BIRSP_IBLK = 0b0100
    BIRSP_SBLK = 0b0101
    BIRSP_EBLK = 0b0110


class CxlMemM2SBIRspHeader(UnalignedBitStructure):
    valid: int
    opcode: CXL_MEM_M2SBIRSP_OPCODE
    bi_id: int
    bi_tag: int
    low_addr: int
    rsvd: int
    _fields = [
        BitField("valid", 0, 0),
        BitField("opcode", 1, 4),
        BitField("bi_id", 5, 16),
        BitField("bi_tag", 17, 28),
        BitField("low_addr", 29, 30),
        BitField("rsvd", 31, 39),
    ]


M2SBIRSP_HEADER_START = CXL_MEM_HEADER_END + 1
M2SBIRSP_HEADER_END = M2SBIRSP_HEADER_START + CxlMemM2SBIRspHeader.get_size() - 1
M2SBIRSP_FIELD_START = M2SBIRSP_HEADER_END + 1


class CxlMemM2SBIRspPacket(CxlMemBasePacket):
    m2sbirsp_header: CxlMemM2SBIRspHeader
    _fields = CxlMemBasePacket._fields + [
        StructureField(
            "m2sbirsp_header",
            M2SBIRSP_HEADER_START,
            M2SBIRSP_HEADER_END,
            CxlMemM2SBIRspHeader,
        ),
    ]


# CXL.mem S2M common definition
class CXL_MEM_S2M_DEV_LOAD(IntEnum):
    LIGHT_LOAD = 0b00
    OPTIMAL_LOAD = 0b01
    MODERATE_OVERLOAD = 0b10
    SEVERE_OVERLOAD = 0b11


# CXL.mem S2M Back-Invalidate Snoop (BISnp)
class CXL_MEM_S2MBISNP_OPCODE(IntEnum):
    BISNP_CUR = 0b0000
    BISNP_DATA = 0b0001
    BISNP_INV = 0b0010
    BISNP_CUR_BLK = 0b0100
    BISNP_DATA_BLK = 0b0101
    BISNP_INV_BLK = 0b0110


class CxlMemS2MBISnpHeader(UnalignedBitStructure):
    valid: int
    opcode: CXL_MEM_S2MBISNP_OPCODE
    bi_id: int
    bi_tag: int
    addr: int
    rsvd: int
    _fields = [
        BitField("valid", 0, 0),
        BitField("opcode", 1, 4),
        BitField("bi_id", 5, 16),
        BitField("bi_tag", 17, 28),
        BitField("addr", 29, 74),
        BitField("rsvd", 75, 79),
    ]


S2MBISNP_HEADER_START = CXL_MEM_HEADER_END + 1
S2MBISNP_HEADER_END = S2MBISNP_HEADER_START + CxlMemS2MBISnpHeader.get_size() - 1
S2MBISNP_FIELD_START = S2MBISNP_HEADER_END + 1


class CxlMemS2MBISnpPacket(CxlMemBasePacket):
    s2mbisnp_header: CxlMemS2MBISnpHeader
    _fields = CxlMemBasePacket._fields + [
        StructureField(
            "s2mbisnp_header",
            S2MBISNP_HEADER_START,
            S2MBISNP_HEADER_END,
            CxlMemS2MBISnpHeader,
        ),
    ]

    def get_address(self) -> int:
        return self.s2mbisnp_header.addr << 6


# CXL.mem S2M No Data Response (NDR)
class CXL_MEM_S2MNDR_OPCODE(IntEnum):
    CMP = 0b000
    CMP_S = 0b001
    CMP_E = 0b010
    CMP_M = 0b011
    BI_CONFLICT_ACK = 0b100


class CxlMemS2MNDRHeader(UnalignedBitStructure):
    valid: int
    opcode: CXL_MEM_S2MNDR_OPCODE
    meta_field: CXL_MEM_META_FIELD
    meta_value: CXL_MEM_META_VALUE
    tag: int
    ld_id: int
    dev_load: CXL_MEM_S2M_DEV_LOAD
    rsvd: int
    _fields = [
        BitField("valid", 0, 0),
        BitField("opcode", 1, 3),
        BitField("meta_field", 4, 5),
        BitField("meta_value", 6, 7),
        BitField("tag", 8, 23),
        BitField("ld_id", 24, 27),
        BitField("dev_load", 28, 29),
        BitField("rsvd", 30, 39),
    ]


S2MNDR_HEADER_START = CXL_MEM_HEADER_END + 1
S2MNDR_HEADER_END = S2MNDR_HEADER_START + CxlMemS2MNDRHeader.get_size() - 1
S2MNDR_FIELD_START = S2MNDR_HEADER_END + 1


class CxlMemS2MNDRPacket(CxlMemBasePacket):
    s2mndr_header: CxlMemS2MNDRHeader
    _fields = CxlMemBasePacket._fields + [
        StructureField(
            "s2mndr_header",
            S2MNDR_HEADER_START,
            S2MNDR_HEADER_END,
            CxlMemS2MNDRHeader,
        ),
    ]


# CXL.mem S2M Data Response (DRS)
class CXL_MEM_S2MDRS_OPCODE(IntEnum):
    MEM_DATA = 0b000
    MEM_DATA_NXM = 0b001


class CxlMemS2MDRSHeader(UnalignedBitStructure):
    valid: int
    opcode: CXL_MEM_S2MDRS_OPCODE
    meta_field: int
    meta_value: int
    tag: int
    poison: int
    ld_id: int
    dev_load: CXL_MEM_S2M_DEV_LOAD
    rsvd: int
    _fields = [
        BitField("valid", 0, 0),
        BitField("opcode", 1, 3),
        BitField("meta_field", 4, 5),
        BitField("meta_value", 6, 7),
        BitField("tag", 8, 23),
        BitField("poison", 24, 24),
        BitField("ld_id", 25, 28),
        BitField("dev_load", 29, 30),
        BitField("rsvd", 31, 39),
    ]


S2MDRS_HEADER_START = CXL_MEM_HEADER_END + 1
S2MDRS_HEADER_END = S2MDRS_HEADER_START + CxlMemS2MDRSHeader.get_size() - 1
S2MDRS_FIELD_START = S2MDRS_HEADER_END + 1


class CxlMemS2MDRSPacket(CxlMemBasePacket):
    s2mdrs_header: CxlMemS2MDRSHeader
    data: int
    _fields = CxlMemBasePacket._fields + [
        StructureField(
            "s2mdrs_header",
            S2MDRS_HEADER_START,
            S2MDRS_HEADER_END,
            CxlMemS2MDRSHeader,
        ),
        ByteField("data", S2MDRS_FIELD_START, S2MDRS_FIELD_START + 63),
    ]


# Helper classes
class CxlMemMemRdPacket(CxlMemM2SReqPacket):
    @staticmethod
    # read length is assumed to be 64 for now
    def create(
        addr: int,
        opcode: Optional[CXL_MEM_M2SREQ_OPCODE] = CXL_MEM_M2SREQ_OPCODE.MEM_RD,
        meta_field: Optional[CXL_MEM_META_FIELD] = CXL_MEM_META_FIELD.NO_OP,
        meta_value: Optional[CXL_MEM_META_VALUE] = CXL_MEM_META_VALUE.ANY,
        snp_type: Optional[CXL_MEM_M2S_SNP_TYPE] = CXL_MEM_M2S_SNP_TYPE.NO_OP,
        ld_id: int = 0,
    ) -> "CxlMemMemRdPacket":
        packet = CxlMemMemRdPacket()
        packet.system_header.payload_type = PAYLOAD_TYPE.CXL_MEM
        packet.system_header.payload_length = len(packet)
        packet.cxl_mem_header.msg_class = CXL_MEM_MSG_CLASS.M2S_REQ
        packet.m2sreq_header.valid = 0b1
        packet.m2sreq_header.mem_opcode = opcode
        packet.m2sreq_header.meta_field = meta_field
        packet.m2sreq_header.meta_value = meta_value
        packet.m2sreq_header.snp_type = snp_type
        packet.m2sreq_header.ld_id = ld_id
        if addr % 0x40:
            raise Exception("Address must be a multiple of 0x40")
        packet.m2sreq_header.addr = addr >> 6
        return packet


class CxlMemMemWrPacket(CxlMemM2SRwDPacket):
    @staticmethod
    def create(
        addr: int,
        data: int,
        opcode: Optional[CXL_MEM_M2SRWD_OPCODE] = CXL_MEM_M2SRWD_OPCODE.MEM_WR,
        meta_field: Optional[CXL_MEM_META_FIELD] = CXL_MEM_META_FIELD.NO_OP,
        meta_value: Optional[CXL_MEM_META_VALUE] = CXL_MEM_META_VALUE.ANY,
        snp_type: Optional[CXL_MEM_M2S_SNP_TYPE] = CXL_MEM_M2S_SNP_TYPE.NO_OP,
        ld_id: int = 0,
    ) -> "CxlMemMemWrPacket":
        packet = CxlMemMemWrPacket()
        packet.system_header.payload_type = PAYLOAD_TYPE.CXL_MEM
        packet.system_header.payload_length = len(packet)
        packet.cxl_mem_header.msg_class = CXL_MEM_MSG_CLASS.M2S_RWD
        packet.m2srwd_header.valid = 0b1
        packet.m2srwd_header.mem_opcode = opcode
        packet.m2srwd_header.meta_field = meta_field
        packet.m2srwd_header.meta_value = meta_value
        packet.m2srwd_header.snp_type = snp_type
        packet.m2srwd_header.ld_id = ld_id
        if addr % 0x40:
            raise Exception("Address must be a multiple of 0x40")
        packet.m2srwd_header.addr = addr >> 6
        packet.data = data
        return packet


class CxlMemBIRspPacket(CxlMemM2SBIRspPacket):
    @staticmethod
    def create(
        opcode: CXL_MEM_M2SBIRSP_OPCODE, bi_id: int = 0, bi_tag: int = 0
    ) -> "CxlMemBIRspPacket":
        packet = CxlMemBIRspPacket()
        packet.system_header.payload_type = PAYLOAD_TYPE.CXL_MEM
        packet.system_header.payload_length = len(packet)
        packet.cxl_mem_header.msg_class = CXL_MEM_MSG_CLASS.M2S_BIRSP
        packet.m2sbirsp_header.valid = 0b1
        packet.m2sbirsp_header.opcode = opcode
        packet.m2sbirsp_header.low_addr = 0b0
        packet.m2sbirsp_header.bi_tag = bi_tag
        packet.m2sbirsp_header.bi_id = bi_id
        return packet


class CxlMemBISnpPacket(CxlMemS2MBISnpPacket):
    tag: int = 0

    @staticmethod
    def get_tag():
        old_tag = CxlMemBISnpPacket.tag
        CxlMemBISnpPacket.tag += 1
        CxlMemBISnpPacket.tag %= 4096
        return old_tag

    @staticmethod
    def create(
        addr: int, opcode: CXL_MEM_S2MBISNP_OPCODE, bi_id: int = 0, bi_tag: int = 0
    ) -> "CxlMemBISnpPacket":
        packet = CxlMemBISnpPacket()
        packet.system_header.payload_type = PAYLOAD_TYPE.CXL_MEM
        packet.system_header.payload_length = len(packet)
        packet.cxl_mem_header.msg_class = CXL_MEM_MSG_CLASS.S2M_BISNP
        packet.s2mbisnp_header.valid = 0b1
        packet.s2mbisnp_header.opcode = opcode
        packet.s2mbisnp_header.bi_tag = bi_tag
        packet.s2mbisnp_header.bi_id = bi_id
        if addr % 0x40:
            raise Exception("Address must be a multiple of 0x40")
        packet.s2mbisnp_header.addr = addr >> 6
        packet.s2mbisnp_header.bi_tag = CxlMemBISnpPacket.get_tag()
        return packet


class CxlMemMemDataPacket(CxlMemS2MDRSPacket):
    @staticmethod
    def create(
        data: int,
        drs_opcode: Optional[CXL_MEM_S2MDRS_OPCODE] = CXL_MEM_S2MDRS_OPCODE.MEM_DATA,
        meta_field: Optional[CXL_MEM_META_FIELD] = CXL_MEM_META_FIELD.NO_OP,
        meta_value: Optional[CXL_MEM_META_VALUE] = CXL_MEM_META_VALUE.ANY,
        ld_id: int = 0,
    ) -> "CxlMemMemDataPacket":
        packet = CxlMemMemDataPacket()
        packet.system_header.payload_type = PAYLOAD_TYPE.CXL_MEM
        packet.system_header.payload_length = len(packet)
        packet.cxl_mem_header.msg_class = CXL_MEM_MSG_CLASS.S2M_DRS
        packet.s2mdrs_header.opcode = drs_opcode
        packet.s2mdrs_header.meta_field = meta_field
        packet.s2mdrs_header.meta_value = meta_value
        packet.s2mdrs_header.ld_id = ld_id
        packet.data = data
        return packet


class CxlMemCmpPacket(CxlMemS2MNDRPacket):
    @staticmethod
    def create(
        ndr_opcode: Optional[CXL_MEM_S2MNDR_OPCODE] = CXL_MEM_S2MNDR_OPCODE.CMP,
        meta_field: Optional[CXL_MEM_META_FIELD] = CXL_MEM_META_FIELD.NO_OP,
        meta_value: Optional[CXL_MEM_META_VALUE] = CXL_MEM_META_VALUE.ANY,
        ld_id: int = 0,
    ) -> "CxlMemCmpPacket":
        packet = CxlMemCmpPacket()
        packet.system_header.payload_type = PAYLOAD_TYPE.CXL_MEM
        packet.system_header.payload_length = len(packet)
        packet.cxl_mem_header.msg_class = CXL_MEM_MSG_CLASS.S2M_NDR
        packet.s2mndr_header.valid = 0b1
        packet.s2mndr_header.opcode = ndr_opcode
        packet.s2mndr_header.meta_field = meta_field
        packet.s2mndr_header.meta_value = meta_value
        packet.s2mndr_header.ld_id = ld_id
        return packet


def is_cxl_mem_data(packet: BasePacket) -> bool:
    if not packet.is_cxl_mem():
        return False
    cxl_mem_packet = cast(CxlMemMemDataPacket, packet)
    return (
        cxl_mem_packet.is_s2mdrs()
        and cxl_mem_packet.s2mdrs_header.opcode == CXL_MEM_S2MDRS_OPCODE.MEM_DATA
    )


def is_cxl_mem_completion(packet: BasePacket) -> bool:
    if not packet.is_cxl_mem():
        return False
    cxl_mem_packet = cast(CxlMemCmpPacket, packet)
    return (
        cxl_mem_packet.is_s2mndr()
        and cxl_mem_packet.s2mndr_header.opcode == CXL_MEM_S2MNDR_OPCODE.CMP
    )


def is_cxl_mem_birsp(packet: BasePacket) -> bool:
    if not packet.is_cxl_mem():
        return False
    cxl_mem_packet = cast(CxlMemBIRspPacket, packet)
    return cxl_mem_packet.is_m2sbirsp()


class CCI_MCTP_MESSAGE_CATEGORY(IntEnum):
    REQUEST = 0
    RESPONSE = 1


class CXL_M2S_RWD_OPCODES(IntEnum):
    MEM_WR = 0b0001
    MEM_WR_PTL = 0b0010
    BI_CONFLICT = 0b1000


class CXL_S2M_DRS_OPCODES(IntEnum):
    MEM_DATA = 0b000
    MEM_DATA_NXM = 0b001


class CXL_S2M_NDR_OPCODES(IntEnum):
    CMP = 0b000
    CMP_S = 0b001
    CMP_E = 0b010
    BI_CONFLICT_ACK = 0b100


class CXL_MEM_DEV_LOAD(IntEnum):
    LIGHT_LOAD = 0b00
    OPTIMAL_LOAD = 0b01
    MODERATE_OVERLOAD = 0b10
    SEVERE_OVERLOAD = 0b11


class CXL_MEM_SNP_TYPE(IntEnum):
    NO_OP = 0b000
    SNP_DATA = 0b001
    SNP_CUR = 0b010
    SNP_INV = 0b011


# CCI Base Packets wrappers for Switch <-> MLD


class CCI_MSG_CLASS(IntEnum):
    REQ = 1
    RSP = 2


class CciHeaderPacket(UnalignedBitStructure):
    port_index: int
    msg_class: CCI_MSG_CLASS
    _fields = [ByteField("port_index", 0, 0), ByteField("msg_class", 1, 1)]


CCI_HEADER_START = SYSTEM_HEADER_END + 1
CCI_HEADER_END = CCI_HEADER_START + CciHeaderPacket.get_size() - 1


class CciMessageHeaderPacket(UnalignedBitStructure):
    message_category: int
    message_tag: int
    command_opcode: int
    message_payload_length_low: int
    message_payload_length_high: int
    background_operation: int
    return_code: int
    vendor_specific_extended_status: int

    _fields = [
        BitField("message_category", 0, 3),
        BitField("reserved0", 4, 7),
        BitField("message_tag", 8, 15),
        BitField("reserved1", 16, 23),
        BitField("command_opcode", 24, 39),
        BitField("message_payload_length_low", 40, 55),
        BitField("message_payload_length_high", 56, 60),
        BitField("reserved2", 61, 62),
        BitField("background_operation", 63, 63),
        BitField("return_code", 64, 79),
        BitField("vendor_specific_extended_status", 80, 95),
    ]

    def get_message_payload_length(self) -> int:
        return self.message_payload_length_high << 16 | self.message_payload_length_low

    def set_message_payload_length(self, length):
        payload_length_low = length & 0xFFFF
        payload_length_high = (length >> 16) & 0x1F
        self.message_payload_length_high = payload_length_high
        self.message_payload_length_low = payload_length_low


class CciMessageBasePacket(UnalignedBitStructure):
    header: CciMessageHeaderPacket
    _payload_data: int  # Every caller should use get_payload()

    _fields = [
        StructureField(
            "header",
            0,
            CciMessageHeaderPacket.get_size() - 1,
            CciMessageHeaderPacket,
        ),
        DynamicByteField("_payload_data", CciMessageHeaderPacket.get_size(), 0x0),
    ]

    def get_total_size(self) -> int:
        return self.header.get_message_payload_length() + len(self.header)

    def get_payload_size(self) -> int:
        return self.header.get_message_payload_length()

    def get_payload(self) -> bytes:
        return int.to_bytes(self._payload_data, self.get_payload_size(), "little")


class CciMessagePacket(CciMessageBasePacket):
    @staticmethod
    def create(header: CciMessageHeaderPacket, data: bytes) -> "CciMessagePacket":
        packet = CciMessagePacket()
        packet.set_dynamic_field_length(len(data))
        packet.header = header
        # pylint: disable=protected-access
        packet._payload_data = int.from_bytes(data, "little")
        return packet


CCI_FIELD_START = CCI_HEADER_END + 1


class CciBasePacket(BasePacket):
    cci_header: CciHeaderPacket
    _fields = BasePacket._fields + [
        StructureField(
            "cci_header",
            CCI_HEADER_START,
            CCI_HEADER_END,
            CciHeaderPacket,
        ),
    ]

    def is_req(self) -> bool:
        return self.cci_header.msg_class == CCI_MSG_CLASS.REQ

    def is_rsp(self) -> bool:
        return self.cci_header.msg_class == CCI_MSG_CLASS.RSP

    def get_payload_size(self) -> int:
        return self.system_header.payload_length - CCI_FIELD_START

    def update_len(self, cci_msg_length: int):
        self.set_dynamic_field_length(cci_msg_length)
        self.system_header.payload_length = len(self)

    def get_total_size(self) -> int:
        return self.system_header.payload_length


class CciPayloadBasePacket(CciBasePacket):
    cci_msg: int

    _fields = CciBasePacket._fields + [
        DynamicByteField("cci_msg", CCI_FIELD_START, 0x0),
    ]


class CciPayloadPacket(CciPayloadBasePacket):
    def get_packet(self) -> CciMessagePacket:
        # Go through setter, don't inline self.cci_msg
        cci_msg = self.cci_msg
        cci_len = self.get_payload_size()
        packet = CciMessagePacket()
        packet.reset(int.to_bytes(cci_msg, cci_len, "little"))
        packet.set_dynamic_field_length(packet.get_payload_size())
        # We don't need this as it's not read directly from PacketReader
        # packet.system_header.payload_length = len(packet)
        return packet

    def update_len(self, cci_msg_length: int):
        self.set_dynamic_field_length(cci_msg_length)
        self.system_header.payload_length = len(self)

    @staticmethod
    def create(data, length: int, index: int = 0) -> "CciPayloadPacket":
        packet = CciPayloadPacket()
        packet.set_dynamic_field_length(length)
        packet.cci_header.port_index = index
        packet.system_header.payload_type = PAYLOAD_TYPE.CCI_MCTP
        packet.system_header.payload_length = len(packet)

        if isinstance(data, CciMessagePacket):
            packet.cci_msg = int.from_bytes(bytes(data.header) + data.get_payload(), "little")
        else:
            packet.cci_msg = int.from_bytes(
                bytes(data.system_header)
                + bytes(data.cci_header)
                + data.cci_msg.to_bytes(data.get_payload_size(), "little"),
                "little",
            )
        return packet


CCI_HEADER_DATA_REQUEST_START = CCI_HEADER_END + 1
CCI_HEADER_DATA_REQUEST_END = CCI_HEADER_DATA_REQUEST_START + CciMessageHeaderPacket.get_size() - 1


class CciRequestPacket(CciBasePacket):
    header_data: CciMessageHeaderPacket  # For CCI
    _fields = CciBasePacket._fields + [
        StructureField(
            "header_data",
            CCI_HEADER_DATA_REQUEST_START,
            CCI_HEADER_DATA_REQUEST_END,
            CciMessageHeaderPacket,
        ),
    ]

    def get_command_opcode(self) -> int:
        return self.header_data.command_opcode

    def is_req(self) -> bool:
        return self.cci_header.msg_class == CCI_MSG_CLASS.REQ


class GetLdInfoRequestPacket(CciRequestPacket):
    def is_req(self) -> bool:
        return self.cci_header.msg_class == CCI_MSG_CLASS.REQ

    def is_get_ld_info(self) -> bool:
        return self.header_data.command_opcode == CCI_FM_API_COMMAND_OPCODE.GET_LD_INFO

    @staticmethod
    def create() -> "GetLdInfoRequestPacket":
        packet = GetLdInfoRequestPacket()
        packet.cci_header.msg_class = CCI_MSG_CLASS.REQ
        packet.system_header.payload_type = PAYLOAD_TYPE.CCI_MCTP
        packet.system_header.payload_length = len(packet)

        packet.header_data.message_category = 0
        packet.header_data.message_tag = 0
        packet.header_data.command_opcode = CCI_FM_API_COMMAND_OPCODE.GET_LD_INFO
        packet.header_data.message_payload_length_high = 0
        packet.header_data.message_payload_length_low = 0
        packet.header_data.return_code = 0
        packet.header_data.vendor_specific_extended_status = 0
        packet.header_data.background_operation = 0

        return packet

    @staticmethod
    def create_from_ccimessage(ccimessage: CciMessagePacket) -> "GetLdInfoRequestPacket":
        packet = GetLdInfoRequestPacket()
        packet.cci_header.msg_class = CCI_MSG_CLASS.REQ
        packet.system_header.payload_type = PAYLOAD_TYPE.CCI_MCTP
        packet.system_header.payload_length = len(packet)

        packet.header_data.message_category = ccimessage.header.message_category
        packet.header_data.message_tag = ccimessage.header.message_tag
        packet.header_data.command_opcode = ccimessage.header.command_opcode
        packet.header_data.message_payload_length_high = (
            ccimessage.header.message_payload_length_high
        )
        packet.header_data.message_payload_length_low = ccimessage.header.message_payload_length_low
        packet.header_data.return_code = ccimessage.header.return_code
        packet.header_data.vendor_specific_extended_status = (
            ccimessage.header.vendor_specific_extended_status
        )
        packet.header_data.background_operation = ccimessage.header.background_operation

        return packet


class GetLdAllocationsRequestPayload(UnalignedBitStructure):
    start_ld_id: int  # 1 bytes
    ld_allocation_list_limit: int  # 1bytes

    _fields = [
        BitField("start_ld_id", 0, 7),
        BitField("ld_allocation_list_limit", 8, 15),
    ]


GET_LD_ALLOCATIONS_REQUEST_PAYLOAD_START = CCI_HEADER_DATA_REQUEST_END + 1
GET_LD_ALLOCATIONS_REQUEST_PAYLOAD_END = (
    GET_LD_ALLOCATIONS_REQUEST_PAYLOAD_START + GetLdAllocationsRequestPayload.get_size() - 1
)


class GetLdAllocationsRequestBasePacket(CciRequestPacket):
    get_ld_allocations_request: GetLdAllocationsRequestPayload

    _fields = CciRequestPacket._fields + [
        StructureField(
            "get_ld_allocations_request",
            GET_LD_ALLOCATIONS_REQUEST_PAYLOAD_START,
            GET_LD_ALLOCATIONS_REQUEST_PAYLOAD_END,
            GetLdAllocationsRequestPayload,
        ),
    ]

    def is_req(self) -> bool:
        return self.cci_header.msg_class == CCI_MSG_CLASS.REQ

    def get_start_ld_id(self) -> int:
        return self.get_ld_allocations_request.start_ld_id

    def get_ld_allocation_list_limit(self) -> int:
        return self.get_ld_allocations_request.ld_allocation_list_limit


class GetLdAllocationsRequestPacket(GetLdAllocationsRequestBasePacket):
    @staticmethod
    def create(start_ld_id: int, ld_allocation_list_limit: int) -> "GetLdAllocationsRequestPacket":
        packet = GetLdAllocationsRequestPacket()
        packet.cci_header.msg_class = CCI_MSG_CLASS.REQ
        packet.system_header.payload_type = PAYLOAD_TYPE.CCI_MCTP
        packet.system_header.payload_length = len(packet)

        packet.header_data.message_category = 0
        packet.header_data.message_tag = 0
        packet.header_data.command_opcode = CCI_FM_API_COMMAND_OPCODE.GET_LD_ALLOCATIONS
        packet.header_data.message_payload_length_high = 0
        packet.header_data.message_payload_length_low = 0
        packet.header_data.return_code = 0
        packet.header_data.vendor_specific_extended_status = 0
        packet.header_data.background_operation = 0

        packet.get_ld_allocations_request.start_ld_id = start_ld_id
        packet.get_ld_allocations_request.ld_allocation_list_limit = ld_allocation_list_limit

        return packet

    @staticmethod
    def create_from_ccimessage(ccimessage: CciMessagePacket) -> "GetLdAllocationsRequestPacket":
        packet = GetLdAllocationsRequestPacket()
        packet.cci_header.msg_class = CCI_MSG_CLASS.REQ
        packet.system_header.payload_type = PAYLOAD_TYPE.CCI_MCTP
        packet.system_header.payload_length = len(packet)

        packet.header_data.message_category = ccimessage.header.message_category
        packet.header_data.message_tag = ccimessage.header.message_tag
        packet.header_data.command_opcode = ccimessage.header.command_opcode
        packet.header_data.message_payload_length_high = (
            ccimessage.header.message_payload_length_high
        )
        packet.header_data.message_payload_length_low = ccimessage.header.message_payload_length_low
        packet.header_data.return_code = ccimessage.header.return_code
        packet.header_data.vendor_specific_extended_status = (
            ccimessage.header.vendor_specific_extended_status
        )
        packet.header_data.background_operation = ccimessage.header.background_operation

        # pylint: disable=protected-access
        packet.get_ld_allocations_request.start_ld_id = ccimessage._payload_data & 0xFF
        packet.get_ld_allocations_request.ld_allocation_list_limit = (
            ccimessage._payload_data >> 8
        ) & 0xFF

        return packet


class SetLdAllocationsRequestPayload(UnalignedBitStructure):
    number_of_lds: int  # 1 bytes
    start_ld_id: int  # 1 bytes
    reserved: int  # 2 bytes

    _fields = [
        BitField("number_of_lds", 0, 7),
        BitField("start_ld_id", 8, 15),
        BitField("reserved", 16, 31),
    ]


SET_LD_ALLOCATIONS_REQUEST_PAYLOAD_START = CCI_HEADER_DATA_REQUEST_END + 1
SET_LD_ALLOCATIONS_REQUEST_PAYLOAD_END = (
    SET_LD_ALLOCATIONS_REQUEST_PAYLOAD_START + SetLdAllocationsRequestPayload.get_size() - 1
)


class SetLdAllocationsRequestBasePacket(CciRequestPacket):
    set_ld_allocations_request_payload: SetLdAllocationsRequestPayload
    ld_allocation_list: int

    _fields = CciRequestPacket._fields + [
        StructureField(
            "set_ld_allocations_request_payload",
            SET_LD_ALLOCATIONS_REQUEST_PAYLOAD_START,
            SET_LD_ALLOCATIONS_REQUEST_PAYLOAD_END,
            SetLdAllocationsRequestPayload,
        ),
        DynamicByteField("ld_allocation_list", SET_LD_ALLOCATIONS_REQUEST_PAYLOAD_END + 1, 0x0),
    ]

    def is_req(self) -> bool:
        return self.cci_header.msg_class == CCI_MSG_CLASS.REQ

    def get_number_of_lds(self) -> int:
        return self.set_ld_allocations_request_payload.number_of_lds

    def get_start_ld_id(self) -> int:
        return self.set_ld_allocations_request_payload.start_ld_id

    def get_ld_allocation_list(self) -> bytes:
        return int.to_bytes(
            self.ld_allocation_list,
            self.set_ld_allocations_request_payload.number_of_lds * 2 * 8,
            "little",
        )


class SetLdAllocationsRequestPacket(SetLdAllocationsRequestBasePacket):
    @staticmethod
    def create_from_ccimessage(ccimessage: CciMessagePacket) -> "SetLdAllocationsRequestPacket":
        packet = SetLdAllocationsRequestPacket()
        packet.cci_header.msg_class = CCI_MSG_CLASS.REQ
        packet.system_header.payload_type = PAYLOAD_TYPE.CCI_MCTP
        packet.system_header.payload_length = len(packet)

        packet.header_data.message_category = ccimessage.header.message_category
        packet.header_data.message_tag = ccimessage.header.message_tag
        packet.header_data.command_opcode = ccimessage.header.command_opcode
        packet.header_data.message_payload_length_high = (
            ccimessage.header.message_payload_length_high
        )
        packet.header_data.message_payload_length_low = ccimessage.header.message_payload_length_low
        packet.header_data.return_code = ccimessage.header.return_code
        packet.header_data.vendor_specific_extended_status = (
            ccimessage.header.vendor_specific_extended_status
        )
        packet.header_data.background_operation = ccimessage.header.background_operation

        cci_payload = ccimessage.get_payload()
        packet.set_ld_allocations_request_payload.reset(
            cci_payload[: SetLdAllocationsRequestPayload.get_size()]
        )

        ld_allocation_list = cci_payload[SetLdAllocationsRequestPayload.get_size() :]
        ld_allocation_list = [
            int.from_bytes(ld_allocation_list[i : i + 8], "little")
            for i in range(0, len(ld_allocation_list), 8)
        ]

        packet.set_dynamic_field_length(
            packet.set_ld_allocations_request_payload.number_of_lds * 2 * 8
        )
        packet.ld_allocation_list = ld_allocation_list
        packet.system_header.payload_length = len(packet)

        return packet

    @staticmethod
    def create(
        number_of_lds: int, start_ld_id: int, ld_allocation_list: int
    ) -> "SetLdAllocationsRequestPacket":
        packet = SetLdAllocationsRequestPacket()

        packet.cci_header.msg_class = CCI_MSG_CLASS.REQ
        packet.system_header.payload_type = PAYLOAD_TYPE.CCI_MCTP

        packet.header_data.message_category = 0
        packet.header_data.message_tag = 0
        packet.header_data.command_opcode = CCI_FM_API_COMMAND_OPCODE.SET_LD_ALLOCATIONS
        payload_length = 4 + 16 * number_of_lds
        packet.header_data.message_payload_length_low = payload_length & 0xFFFF
        packet.header_data.message_payload_length_high = (payload_length >> 16) & 0x1F
        packet.header_data.return_code = 0
        packet.header_data.vendor_specific_extended_status = 0
        packet.header_data.background_operation = 0

        if number_of_lds < 1:
            raise Exception("Number of LDs must be greater than 0")
        packet.set_ld_allocations_request_payload.number_of_lds = number_of_lds
        packet.set_ld_allocations_request_payload.start_ld_id = start_ld_id
        packet.set_ld_allocations_request_payload.reserved = 0
        packet.set_dynamic_field_length(number_of_lds * 2 * 8)

        packet.ld_allocation_list = ld_allocation_list
        packet.system_header.payload_length = len(packet)

        return packet


class CciResponseHeader(UnalignedBitStructure):
    response_length: int  # 2bytes
    reserved: int  # 2bytes

    _fields = [
        BitField("response_length", 0, 15),
        BitField("reserved", 16, 31),
    ]


CCI_HEADER_DATA_RESPONSE_START = CCI_HEADER_END + 1
CCI_HEADER_DATA_RESPONSE_END = (
    CCI_HEADER_DATA_RESPONSE_START + CciMessageHeaderPacket.get_size() - 1
)


class CciResponsePacket(CciBasePacket):
    header_data: CciMessageHeaderPacket  # CCI
    _fields = CciBasePacket._fields + [
        StructureField(
            "header_data",
            CCI_HEADER_DATA_RESPONSE_START,
            CCI_HEADER_DATA_RESPONSE_END,
            CciMessageHeaderPacket,
        ),
    ]

    def get_command_opcode(self) -> int:
        return self.header_data.command_opcode

    def is_rsp(self) -> bool:
        return self.cci_header.msg_class == CCI_MSG_CLASS.RSP


class GetLdInfoResponsePayload(UnalignedBitStructure):
    memory_size: int  # 8 bytes
    ld_count: int  # 2 bytes
    QoS_Telemetry_capability: int  # 1 byte

    _fields = [
        BitField("memory_size", 0, 63),
        BitField("ld_count", 64, 79),
        BitField("QoS_Telemetry_capability", 80, 87),
    ]


GET_LD_INFO_RESPONSE_START = CCI_HEADER_DATA_RESPONSE_END + 1
GET_LD_INFO_RESPONSE_END = GET_LD_INFO_RESPONSE_START + GetLdInfoResponsePayload.get_size() - 1


class GetLdInfoResponseBasePacket(CciResponsePacket):
    payload: GetLdInfoResponsePayload

    _fields = CciResponsePacket._fields + [
        StructureField(
            "payload",
            GET_LD_INFO_RESPONSE_START,
            GET_LD_INFO_RESPONSE_END,
            GetLdInfoResponsePayload,
        ),
    ]

    def get_memory_size(self) -> int:
        return self.payload.memory_size

    def get_ld_count(self) -> int:
        return self.payload.ld_count

    def get_QoS_Telemetry_capability(self) -> int:
        return self.payload.QoS_Telemetry_capability

    def get_payload_size(self) -> int:
        return self.payload.get_size()


class GetLdInfoResponsePacket(GetLdInfoResponseBasePacket):
    def payload_to_bytes(self, byteorder: str) -> bytes:
        memory_size_bytes = self.payload.memory_size.to_bytes(8, byteorder)
        ld_count_bytes = self.payload.ld_count.to_bytes(2, byteorder)
        qos_telemetry_bytes = self.payload.QoS_Telemetry_capability.to_bytes(1, byteorder)

        return memory_size_bytes + ld_count_bytes + qos_telemetry_bytes

    def create_ccimessage(self) -> "CciMessagePacket":
        cci_message__header = CciMessageHeaderPacket()
        cci_message__header.message_category = self.header_data.message_category
        cci_message__header.message_tag = self.header_data.message_tag
        cci_message__header.command_opcode = self.header_data.command_opcode
        cci_message__header.message_payload_length_high = (
            self.header_data.message_payload_length_high
        )
        cci_message__header.message_payload_length_low = self.header_data.message_payload_length_low
        cci_message__header.return_code = self.header_data.return_code
        cci_message__header.vendor_specific_extended_status = (
            self.header_data.vendor_specific_extended_status
        )
        cci_message__header.background_operation = self.header_data.background_operation
        # payload size is 11bytes, and this

        cci_message_packet = CciMessagePacket.create(
            cci_message__header, self.payload_to_bytes("little")
        )

        return cci_message_packet

    @staticmethod
    def create(memory_size: int, ld_count: int, message_tag: int) -> "GetLdInfoResponsePacket":
        packet = GetLdInfoResponsePacket()
        packet.cci_header.msg_class = CCI_MSG_CLASS.RSP
        packet.system_header.payload_type = PAYLOAD_TYPE.CCI_MCTP
        packet.system_header.payload_length = len(packet)

        packet.header_data.message_category = 1
        packet.header_data.message_tag = message_tag
        packet.header_data.command_opcode = CCI_FM_API_COMMAND_OPCODE.GET_LD_INFO
        # get ld info payload size is 11 bytes
        packet.header_data.message_payload_length_high = 0
        packet.header_data.message_payload_length_low = 11
        packet.header_data.return_code = 0
        packet.header_data.vendor_specific_extended_status = 0
        packet.header_data.background_operation = 0

        packet.payload.memory_size = memory_size
        packet.payload.ld_count = ld_count
        packet.payload.QoS_Telemetry_capability = 0

        return packet


class GetLdAllocationsResponsePayload(UnalignedBitStructure):
    number_of_lds: int  # 1 byte
    memory_granularity: int  # 1 byte
    start_ld_id: int  # 1 byte
    ld_allocation_list_length: int  # 1 byte

    _fields = [
        BitField("number_of_lds", 0, 7),
        BitField("memory_granularity", 8, 15),
        BitField("start_ld_id", 16, 23),
        BitField("ld_allocation_list_length", 24, 31),
    ]


GET_LD_ALLOCATIONS_RESPONSE_PAYLOAD_START = CCI_HEADER_DATA_RESPONSE_END + 1
GET_LD_ALLOCATIONS_RESPONSE_PAYLOAD_END = (
    GET_LD_ALLOCATIONS_RESPONSE_PAYLOAD_START + GetLdAllocationsResponsePayload.get_size() - 1
)


class GetLdAllocationsResponseBasePacket(CciResponsePacket):
    get_ld_allocations_response_payload: GetLdAllocationsResponsePayload
    ld_allocation_list: int

    _fields = CciResponsePacket._fields + [
        StructureField(
            "get_ld_allocations_response_payload",
            GET_LD_ALLOCATIONS_RESPONSE_PAYLOAD_START,
            GET_LD_ALLOCATIONS_RESPONSE_PAYLOAD_END,
            GetLdAllocationsResponsePayload,
        ),
        DynamicByteField("ld_allocation_list", GET_LD_ALLOCATIONS_RESPONSE_PAYLOAD_END + 1, 0x0),
    ]

    def get_number_of_lds(self) -> int:
        return self.get_ld_allocations_response_payload.number_of_lds

    def get_memory_granularity(self) -> int:
        return self.get_ld_allocations_response_payload.memory_granularity

    def get_ld_allocation_list(self) -> bytes:
        return int.to_bytes(
            self.ld_allocation_list,
            self.get_ld_allocations_response_payload.ld_allocation_list_length * 2 * 8,
            "little",
        )

    def get_start_ld_id(self) -> int:
        return self.get_ld_allocations_response_payload.start_ld_id

    def get_ld_allocation_list_length(self) -> int:
        return self.get_ld_allocations_response_payload.ld_allocation_list_length


class GetLdAllocationsResponsePacket(GetLdAllocationsResponseBasePacket):
    def payload_to_bytes(self, byteorder: str) -> bytes:
        number_of_lds_bytes = self.get_ld_allocations_response_payload.number_of_lds.to_bytes(
            1, byteorder
        )
        memory_granularity_bytes = (
            self.get_ld_allocations_response_payload.memory_granularity.to_bytes(1, byteorder)
        )
        start_ld_id_bytes = self.get_ld_allocations_response_payload.start_ld_id.to_bytes(
            1, byteorder
        )
        ld_allocation_list_length_bytes = (
            self.get_ld_allocations_response_payload.ld_allocation_list_length.to_bytes(
                1, byteorder
            )
        )
        ld_allocations_bytes = self.get_ld_allocation_list()

        return (
            number_of_lds_bytes
            + memory_granularity_bytes
            + start_ld_id_bytes
            + ld_allocation_list_length_bytes
            + ld_allocations_bytes
        )

    def create_ccimessage(self) -> "CciMessagePacket":
        cci_message__header = CciMessageHeaderPacket()
        cci_message__header.message_category = self.header_data.message_category
        cci_message__header.message_tag = self.header_data.message_tag
        cci_message__header.command_opcode = self.header_data.command_opcode
        cci_message__header.message_payload_length_high = (
            self.header_data.message_payload_length_high
        )
        cci_message__header.message_payload_length_low = self.header_data.message_payload_length_low
        cci_message__header.return_code = self.header_data.return_code
        cci_message__header.vendor_specific_extended_status = (
            self.header_data.vendor_specific_extended_status
        )
        cci_message__header.background_operation = self.header_data.background_operation

        cci_message_packet = CciMessagePacket.create(
            cci_message__header, self.payload_to_bytes("little")
        )

        return cci_message_packet

    @staticmethod
    def create(
        number_of_lds: int,
        memory_granularity: int,
        start_ld_id: int,
        ld_allocation_list_length: int,
        ld_allocation_list: int,
        message_tag: int,
    ) -> "GetLdAllocationsResponsePacket":
        packet = GetLdAllocationsResponsePacket()
        packet.cci_header.msg_class = CCI_MSG_CLASS.RSP
        packet.system_header.payload_type = PAYLOAD_TYPE.CCI_MCTP

        packet.header_data.message_category = 1
        packet.header_data.message_tag = message_tag
        packet.header_data.command_opcode = CCI_FM_API_COMMAND_OPCODE.GET_LD_ALLOCATIONS
        payload_length = 4 + ld_allocation_list_length * 16
        packet.header_data.message_payload_length_low = payload_length & 0xFFFF
        packet.header_data.message_payload_length_high = (payload_length >> 16) & 0x1F
        packet.header_data.return_code = 0
        packet.header_data.vendor_specific_extended_status = 0
        packet.header_data.background_operation = 0

        # Set payload_packet
        packet.get_ld_allocations_response_payload.number_of_lds = number_of_lds
        packet.get_ld_allocations_response_payload.memory_granularity = memory_granularity
        packet.get_ld_allocations_response_payload.start_ld_id = start_ld_id
        packet.get_ld_allocations_response_payload.ld_allocation_list_length = (
            ld_allocation_list_length
        )
        packet.set_dynamic_field_length(ld_allocation_list_length * 2 * 8)
        packet.ld_allocation_list = ld_allocation_list
        packet.system_header.payload_length = len(packet)

        return packet


class SetLdAllocationsResponsePayload(UnalignedBitStructure):
    number_of_lds: int  # 1 byte
    start_ld_id: int  # 1 byte
    reserved: int  # 2 bytes

    _fields = [
        BitField("number_of_lds", 0, 7),
        BitField("start_ld_id", 8, 15),
        BitField("reserved", 16, 31),
    ]


SET_LD_ALLOCATIONS_RESPONSE_PAYLOAD_START = CCI_HEADER_DATA_RESPONSE_END + 1
SET_LD_ALLOCATIONS_RESPONSE_PAYLOAD_END = (
    SET_LD_ALLOCATIONS_RESPONSE_PAYLOAD_START + SetLdAllocationsResponsePayload.get_size() - 1
)


class SetLdAllocationsResponseBasePacket(CciResponsePacket):
    set_ld_allocations_response_payload: SetLdAllocationsResponsePayload
    ld_allocation_list: int

    _fields = CciResponsePacket._fields + [
        StructureField(
            "set_ld_allocations_response_payload",
            SET_LD_ALLOCATIONS_RESPONSE_PAYLOAD_START,
            SET_LD_ALLOCATIONS_RESPONSE_PAYLOAD_END,
            SetLdAllocationsResponsePayload,
        ),
        DynamicByteField("ld_allocation_list", SET_LD_ALLOCATIONS_RESPONSE_PAYLOAD_END + 1, 0x0),
    ]

    def get_number_of_lds(self) -> int:
        return self.set_ld_allocations_response_payload.number_of_lds

    def get_start_ld_id(self) -> int:
        return self.set_ld_allocations_response_payload.start_ld_id

    def get_ld_allocation_list_length(self) -> int:
        return self.ld_allocation_list

    def get_ld_allocation_list(self) -> bytes:
        return int.to_bytes(
            self.ld_allocation_list,
            self.set_ld_allocations_response_payload.number_of_lds * 2 * 8,
            "little",
        )


class SetLdAllocationsResponsePacket(SetLdAllocationsResponseBasePacket):
    def payload_to_bytes(self) -> bytes:
        number_of_lds_bytes = self.set_ld_allocations_response_payload.number_of_lds.to_bytes(
            1, "little"
        )
        start_ld_id_bytes = self.set_ld_allocations_response_payload.start_ld_id.to_bytes(
            1, "little"
        )
        reserved_bytes = self.set_ld_allocations_response_payload.reserved.to_bytes(2, "little")

        return number_of_lds_bytes + start_ld_id_bytes + reserved_bytes + self.ld_allocation_list

    def create_ccimessage(self) -> "CciMessagePacket":
        cci_message_header = CciMessageHeaderPacket()
        cci_message_header.message_category = self.header_data.message_category
        cci_message_header.message_tag = self.header_data.message_tag
        cci_message_header.command_opcode = self.header_data.command_opcode
        cci_message_header.message_payload_length_high = (
            self.header_data.message_payload_length_high
        )
        cci_message_header.message_payload_length_low = self.header_data.message_payload_length_low
        cci_message_header.return_code = self.header_data.return_code
        cci_message_header.vendor_specific_extended_status = (
            self.header_data.vendor_specific_extended_status
        )
        cci_message_header.background_operation = self.header_data.background_operation

        cci_message_packet = CciMessagePacket.create(cci_message_header, self.payload_to_bytes())

        return cci_message_packet

    @staticmethod
    def create(
        number_of_lds: int, start_ld_id: int, ld_allocation_list: int, message_tag: int
    ) -> "SetLdAllocationsResponsePacket":
        packet = SetLdAllocationsResponsePacket()
        packet.cci_header.msg_class = CCI_MSG_CLASS.RSP
        packet.system_header.payload_type = PAYLOAD_TYPE.CCI_MCTP

        packet.header_data.message_category = 1
        packet.header_data.message_tag = message_tag
        packet.header_data.command_opcode = CCI_FM_API_COMMAND_OPCODE.SET_LD_ALLOCATIONS
        payload_length = 4 + 16 * number_of_lds
        packet.header_data.message_payload_length_low = payload_length & 0xFFFF
        packet.header_data.message_payload_length_high = (payload_length >> 16) & 0x1F
        packet.header_data.return_code = 0
        packet.header_data.vendor_specific_extended_status = 0
        packet.header_data.background_operation = 0

        packet.set_ld_allocations_response_payload.number_of_lds = number_of_lds
        packet.set_ld_allocations_response_payload.start_ld_id = start_ld_id
        packet.set_ld_allocations_response_payload.reserved = 0

        packet.set_dynamic_field_length(number_of_lds * 2 * 8)
        packet.ld_allocation_list = ld_allocation_list
        packet.system_header.payload_length = len(packet)

        return packet
