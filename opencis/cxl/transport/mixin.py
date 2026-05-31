"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

# from opencis.util.logger import logger
from opencis.cxl.transport.packet_constants import (
    SYSTEM_PAYLOAD_TYPE,
    CXL_IO_FMT_TYPE,
    CXL_MEM_MSG_CLASS,
    CXL_CACHE_MSG_CLASS,
    SIDEBAND_TYPES,
    CCI_MSG_CLASS,
)
from opencis.util.pci import (
    extract_function_from_bdf,
    extract_device_from_bdf,
    extract_bus_from_bdf,
)
from opencis.util.number import (
    tlptoh16,
)


class PacketDataMixin:
    def get_data_as_int(self) -> int:
        return int.from_bytes(self.get_data(), "little")

    def set_data_as_int(self, data: int, length: int = None):
        if length is None:
            length = (data.bit_length() + 7) // 8 or 1

        data = data.to_bytes(length, byteorder="little")
        self.set_data(data)


class BasePacketMixin:
    def is_cxl_io(self) -> bool:
        return self.system_header.payload_type == SYSTEM_PAYLOAD_TYPE.CXL_IO

    def is_cxl_mem(self) -> bool:
        return self.system_header.payload_type == SYSTEM_PAYLOAD_TYPE.CXL_MEM

    def is_cxl_cache(self) -> bool:
        return self.system_header.payload_type == SYSTEM_PAYLOAD_TYPE.CXL_CACHE

    def is_cci(self) -> bool:
        return self.system_header.payload_type == SYSTEM_PAYLOAD_TYPE.CCI_MCTP

    def is_sideband(self) -> bool:
        return self.system_header.payload_type == SYSTEM_PAYLOAD_TYPE.SIDEBAND

    def is_pbr(self) -> bool:
        return self.system_header.payload_type == SYSTEM_PAYLOAD_TYPE.PBR

    def get_type(self) -> str:
        return self.__class__.__name__

    def get_pretty_string(self) -> str:
        out, hdrs = [], []
        out.append(f"\n{type(self).__name__}")
        for name in dir(self):
            if not name.startswith("_"):
                v = getattr(self, name, None)
                try:
                    off = int(self.get_byte_offset(v))
                except (TypeError, ValueError):
                    off = 0
                hdrs.append((off, name, v))

        # Print headers
        for _, name, hdr in sorted(hdrs, key=lambda x: x[0]):
            out.append(name)
            fld = getattr(type(hdr), "_fields", None)
            if fld:
                names = [f[0] for f in sorted(fld, key=lambda f: f[1])]
            else:
                names = [
                    a
                    for a in dir(hdr)
                    if not a.startswith("_")
                    and isinstance(getattr(hdr, a, None), (int, bytes, str, float))
                ]
            for fn in names:
                try:
                    val = getattr(hdr, fn)
                except (TypeError, ValueError):
                    val = "<err>"
                out.append(f"    {fn}: 0x{val:x}")

        # Print payload
        start = self.get_payload_offset()
        end = self.get_size()
        if end > start:
            data = bytes(self)[start:end]
            out.append("DataField")
            out.append(f"    offset: {start}")
            out.append(f"    length: {len(data)}")
            for i in range(0, len(data), 16):
                chunk = data[i : i + 16]
                hp = [f"{b:02x}" for b in chunk]
                left, right = hp[:8], hp[8:]
                hex_str = " ".join(left) + ("  " if right else "") + " ".join(right)
                pad = " " * (48 - len(hex_str))
                ascii_str = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
                out.append(f"        {i:08x}|  {hex_str}{pad} |{ascii_str}|")
        return "\n".join(out)


class SidebandPacketMixin:
    def get_packet_type(self) -> SIDEBAND_TYPES:
        return self.sideband_header.type

    def is_connection_request(self) -> bool:
        return self.get_packet_type() == SIDEBAND_TYPES.CONNECTION_REQUEST

    def is_connection_accept(self) -> bool:
        return self.get_packet_type() == SIDEBAND_TYPES.CONNECTION_ACCEPT

    def is_connection_reject(self) -> bool:
        return self.get_packet_type() == SIDEBAND_TYPES.CONNECTION_REJECT


class CxlIoBasePacketMixin:
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
    def build_transaction_id(req_id: int, tag: int) -> int:
        tid = (req_id << 8) | tag
        return tid


class CxlIoMemReqPacketMixin:
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


class CxlIoCfgReqPacketMixin:
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


class CxlCacheBasePacketMixin:
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


class CxlMemBasePacketMixin:
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


class CciBasePacketMixin:
    def is_req(self) -> bool:
        return self.cci_header.msg_class == CCI_MSG_CLASS.REQ

    def is_rsp(self) -> bool:
        return self.cci_header.msg_class == CCI_MSG_CLASS.RSP

    def get_cci_payload_length(self) -> int:
        max_bit = 0
        for _, offset, width in self._fields:
            if width == "dynamic" or callable(offset):
                continue
            max_bit = max(max_bit, offset + width)
        return (max_bit + 7) // 8
