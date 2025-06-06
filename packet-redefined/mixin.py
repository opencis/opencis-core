from enum import IntEnum


class PAYLOAD_TYPE(IntEnum):
    CXL = 0  # packet based on CPI
    CXL_IO = 1  # Custom packet for CXL.io
    CXL_MEM = 2  # Custom packet for CXL.mem
    CXL_CACHE = 3  # Custom packet for CXL.cache
    CCI_MCTP = 4  # Custom packet for CCI MCTP
    SIDEBAND = 15


class BasePacketMixin:
    def is_cxl_io(self) -> bool:
        return self.system_header.payload_type == PAYLOAD_TYPE.CXL_IO

    def is_cxl_mem(self) -> bool:
        return self.system_header.payload_type == PAYLOAD_TYPE.CXL_MEM

    def is_cxl_cache(self) -> bool:
        return self.system_header.payload_type == PAYLOAD_TYPE.CXL_CACHE

    def is_cci(self) -> bool:
        return self.system_header.payload_type == PAYLOAD_TYPE.CCI_MCTP

    def is_sideband(self) -> bool:
        return self.system_header.payload_type == PAYLOAD_TYPE.SIDEBAND

    def get_type(self) -> str:
        return self.__class__.__name__


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
    CAS_64B = 0b011011


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

    # @staticmethod
    # def get_tag() -> int:
    #     old_tag = CxlIoBasePacket.tag
    #     CxlIoBasePacket.tag += 1
    #     CxlIoBasePacket.tag %= 256
    #     return old_tag

    @staticmethod
    def build_transaction_id(req_id: int, tag: int) -> int:
        tid = (req_id << 8) | tag
        return tid

    def get_transaction_id(self) -> int:
        raise Exception("get_transaction_id must be implemented by a child class")


class CXL_IO_CPL_STATUS(IntEnum):
    SC = 0b000
    UR = 0b001
    RRS = 0b010
    CA = 0b100


######### CACHE
class CXL_CACHE_MSG_CLASS(IntEnum):
    D2H_REQ = 1
    D2H_RSP = 2
    D2H_DATA = 3
    H2D_REQ = 4
    H2D_RSP = 5
    H2D_DATA = 6


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


# Table 3-25
class CXL_CACHE_D2HRSP_OPCODE(IntEnum):
    RSP_I_HIT_I = 0b00100
    RSP_V_HIT_V = 0b00110
    RSP_I_HIT_SE = 0b00101
    RSP_S_HIT_SE = 0b00001
    RSP_S_FWD_M = 0b00111
    RSP_I_FWD_M = 0b01111
    RSP_V_FWD_V = 0b10110


# Table 3-26
class CXL_CACHE_H2DREQ_OPCODE(IntEnum):
    SNP_DATA = 0b001
    SNP_INV = 0b010
    SNP_CUR = 0b011


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
