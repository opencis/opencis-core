from packet_constants import (
    SYSTEM_PAYLOAD_TYPE,
    CXL_IO_FMT_TYPE,
    CXL_MEM_MSG_CLASS,
    CXL_CACHE_MSG_CLASS,
    SIDEBAND_TYPES,
    CCI_MSG_CLASS,
)


class PacketDataMixin:
    def get_data(self) -> bytes:
        return bytes(super().get_data())

    def get_data_as_int(self) -> int:
        return int.from_bytes(self.get_data(), "little")

    def set_data(self, data: bytes):
        super().set_data(data)

    def set_data_as_int(self, data: int, length: int = None):
        # print(f"set_data_as_int i:{data:x}")
        if length is None:
            length = (data.bit_length() + 7) // 8 or 1
        data = data.to_bytes(length, byteorder="little")
        # print(f"set_data_as_int b:{data}")
        self.set_data(data)

    def get_pretty_string(self):
        return ""


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

    def get_type(self) -> str:
        return self.__class__.__name__


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

    def update_len(self, cci_msg_length: int):
        self.set_dynamic_field_length(cci_msg_length)
        self.system_header.payload_length = len(self)

    def get_total_size(self) -> int:
        return self.system_header.payload_length


def populate_header_from_ccimessage(cci_msg_header, ccimessage_header):
    cci_msg_header.message_category = ccimessage_header.message_category
    cci_msg_header.message_tag = ccimessage_header.message_tag
    cci_msg_header.command_opcode = ccimessage_header.command_opcode
    cci_msg_header.message_payload_length_high = ccimessage_header.message_payload_length_high
    cci_msg_header.message_payload_length_low = ccimessage_header.message_payload_length_low
    cci_msg_header.return_code = ccimessage_header.return_code
    cci_msg_header.vendor_specific_extended_status = (
        ccimessage_header.vendor_specific_extended_status
    )
    cci_msg_header.background_operation = ccimessage_header.background_operation
