"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from enum import IntEnum


class SYSTEM_PAYLOAD_TYPE(IntEnum):
    CXL = 0  # packet based on CPI
    CXL_IO = 1  # Custom packet for CXL.io
    CXL_MEM = 2  # Custom packet for CXL.mem
    CXL_CACHE = 3  # Custom packet for CXL.cache
    CCI_MCTP = 4  # Custom packet for CCI MCTP
    SIDEBAND = 15


class SIDEBAND_TYPES(IntEnum):
    CONNECTION_REQUEST = 0
    CONNECTION_ACCEPT = 1
    CONNECTION_REJECT = 2
    CONNECTION_DISCONNECTED = 3


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


class CXL_IO_CPL_STATUS(IntEnum):
    SC = 0b000
    UR = 0b001
    RRS = 0b010
    CA = 0b100


# cache


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


### mem


class CXL_MEM_MSG_CLASS(IntEnum):
    M2S_REQ = 1
    M2S_RWD = 2
    M2S_BIRSP = 3
    S2M_BISNP = 4
    S2M_NDR = 5
    S2M_DRS = 6


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


# CXL.mem M2S Request with Data (RwD)
class CXL_MEM_M2SRWD_OPCODE(IntEnum):
    MEM_WR = 0b0001
    MEM_WR_PTL = 0b0010
    BI_CONFLICT = 0b0100


# CXL.mem M2S Back-Invalidate Response (BIRsp)
class CXL_MEM_M2SBIRSP_OPCODE(IntEnum):
    BIRSP_I = 0b0000
    BIRSP_S = 0b0001
    BIRSP_E = 0b0010
    BIRSP_IBLK = 0b0100
    BIRSP_SBLK = 0b0101
    BIRSP_EBLK = 0b0110


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


# CXL.mem S2M No Data Response (NDR)
class CXL_MEM_S2MNDR_OPCODE(IntEnum):
    CMP = 0b000
    CMP_S = 0b001
    CMP_E = 0b010
    CMP_M = 0b011
    BI_CONFLICT_ACK = 0b100


# CXL.mem S2M Data Response (DRS)
class CXL_MEM_S2MDRS_OPCODE(IntEnum):
    MEM_DATA = 0b000
    MEM_DATA_NXM = 0b001


class CCI_MSG_CLASS(IntEnum):
    REQ = 1
    RSP = 2


class CCI_MCTP_MESSAGE_CATEGORY(IntEnum):
    REQUEST = 0
    RESPONSE = 1
