"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.

smbus_mctp_framing.py — SMBus + MCTP packet framing (DMTF DSP0237)
===================================================================

Implements MCTP over SMBus/I2C framing per DMTF DSP0237 v1.2.0.
Used by FmSmbusMctpServer (port 8300) to accept packets from QEMU
SMBus Slave and send responses to QEMU SMBus Master.

REQUEST frame (QEMU SMBus Slave → FM TCP port):
  Byte 0: dest_slave_addr  = FM i2c_addr << 1         (write direction bit=0)
  Byte 1: command_code     = 0x0F                      (MCTP over SMBus)
  Byte 2: byte_count       = N  (bytes from byte[3] to PEC exclusive)
  Byte 3: src_slave_addr   = dev_i2c_addr << 1 | 0x01  (source, read bit=1)
  Byte 4: hdr_ver          = 0x01
  Byte 5: dest_eid         = FM EID (e.g. 0x08)
  Byte 6: src_eid          = Device EID (e.g. 0x09)
  Byte 7: SOM(1)|EOM(1)|PktSeq(2)|TO(1)|MsgTag(3)
  Byte 8: IC(1)|MsgType(7) = e.g. 0x7E for CXL FM API
  Bytes 9..9+11: CCI message header (12 bytes)
  Bytes 21..:    CCI payload
  Last:   PEC (CRC-8 over all preceding bytes)

RESPONSE frame (FM → QEMU SMBus Master):
  Byte 0: byte_count       = M  (bytes from byte[1] to PEC exclusive)
  Byte 1: src_slave_addr   = FM i2c_addr << 1 | 0x01   (FM responding)
  Byte 2: hdr_ver          = 0x01
  Byte 3: dest_eid         = Device EID (swapped from request)
  Byte 4: src_eid          = FM EID
  Byte 5: SOM(1)|EOM(1)|PktSeq(2)|TO=0|MsgTag(3)  (same tag as request)
  Byte 6: IC(1)|MsgType(7) (same msg_type as request)
  Bytes 7..18:   CCI response header (12 bytes)
  Bytes 19..:    CCI response payload
  Last:   PEC
"""

from __future__ import annotations
import struct
from dataclasses import dataclass

# ── Constants ──────────────────────────────────────────────────────────────────

SMBUS_MCTP_COMMAND_CODE = 0x0F       # Fixed: MCTP over SMBus command code
MCTP_HDR_VERSION        = 0x01       # MCTP header version
MCTP_MSG_TYPE_CXL_FM    = 0x7E       # CXL FM API message type (no IC bit)
MCTP_MSG_TYPE_VENDOR    = 0x7F       # Vendor-defined

# Sizes derived from fields.py bit layout
SMBUS_REQ_HDR_SIZE  = 9   # dest_addr(1)+cmd(1)+byte_count(1)+src_addr(1)+mctp_hdr(4)+msg_type(1)
SMBUS_RSP_HDR_SIZE  = 7   # byte_count(1)+src_addr(1)+mctp_hdr(4)+msg_type(1)
CCI_MSG_HDR_SIZE    = 12  # From CciMessageHeader in fields.py (96 bits = 12 bytes)
PEC_SIZE            = 1

# Minimum valid frame lengths
SMBUS_REQ_MIN_LEN = SMBUS_REQ_HDR_SIZE + CCI_MSG_HDR_SIZE + PEC_SIZE  # 22 bytes
SMBUS_RSP_MIN_LEN = SMBUS_RSP_HDR_SIZE + CCI_MSG_HDR_SIZE + PEC_SIZE  # 20 bytes


# ── CRC-8 (SMBus PEC, polynomial 0x07) ────────────────────────────────────────

def crc8_smbus(data: bytes | bytearray) -> int:
    """
    Compute CRC-8 for SMBus Packet Error Code (PEC).
    Polynomial: x^8 + x^2 + x + 1  (0x07)
    """
    crc = 0
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x80:
                crc = ((crc << 1) ^ 0x07) & 0xFF
            else:
                crc = (crc << 1) & 0xFF
    return crc


# ── CCI message field accessors (matches fields.py CciMessageHeader layout) ───

def _cci_get_opcode(cci_hdr: bytes) -> int:
    """Extract command_opcode from CCI message header (bits 24-39 = bytes[3:5] LE)."""
    return int.from_bytes(cci_hdr[3:5], "little")


def _cci_get_tag(cci_hdr: bytes) -> int:
    """Extract message_tag (bits 8-15 = byte[1])."""
    return cci_hdr[1]


def _cci_get_category(cci_hdr: bytes) -> int:
    """Extract message_category (bits 0-3 = byte[0] low nibble)."""
    return cci_hdr[0] & 0x0F


def _cci_get_payload_length(cci_hdr: bytes) -> int:
    """Extract payload length from CCI header (bits 40-60)."""
    low  = int.from_bytes(cci_hdr[5:7], "little")   # bits 40-55
    high = cci_hdr[7] & 0x1F                          # bits 56-60
    return low | (high << 16)


def _build_cci_response_header(
    tag: int,
    opcode: int,
    payload_len: int,
    return_code: int,
    is_background: bool,
) -> bytes:
    """Build a 12-byte CCI message header for a RESPONSE packet."""
    hdr = bytearray(12)
    hdr[0]  = 0x01              # message_category = RESPONSE (1)
    hdr[1]  = tag & 0xFF        # message_tag
    hdr[2]  = 0x00              # reserved1
    hdr[3]  = opcode & 0xFF     # opcode low
    hdr[4]  = (opcode >> 8) & 0xFF   # opcode high
    hdr[5]  = payload_len & 0xFF          # payload_length_low low
    hdr[6]  = (payload_len >> 8) & 0xFF   # payload_length_low high
    hdr[7]  = (payload_len >> 16) & 0x1F  # payload_length_high
    if is_background:
        hdr[7] |= 0x80          # background_operation bit
    hdr[8]  = return_code & 0xFF
    hdr[9]  = (return_code >> 8) & 0xFF
    hdr[10] = 0x00              # vendor_specific_extended_status low
    hdr[11] = 0x00              # vendor_specific_extended_status high
    return bytes(hdr)


# ── SmbusMctpRequest ───────────────────────────────────────────────────────────

@dataclass
class SmbusMctpRequest:
    """
    Parsed SMBus+MCTP request frame (DSP0237).

    After parsing:
      .cci_opcode        — CCI command opcode (e.g. 0x5700)
      .cci_tag           — CCI message tag (0-255)
      .cci_payload       — raw CCI payload bytes
      .msg_tag           — MCTP message tag (3-bit, for response)
      .msg_type_byte     — full MCTP message type byte (IC + msg_type)
      .src_eid / dest_eid — MCTP endpoint IDs
      .src_slave_addr    — I2C source address byte (for response routing)
    """

    # SMBus fields
    dest_slave_addr: int
    command_code: int
    byte_count: int
    src_slave_addr: int

    # MCTP transport header
    hdr_ver: int
    dest_eid: int
    src_eid: int
    som: int
    eom: int
    pkt_seq: int
    to: int                     # tag owner bit
    msg_tag: int                # 3-bit MCTP message tag

    # MCTP message body
    msg_type_byte: int          # IC(1) | msg_type(7)
    ic: int
    msg_type: int

    # CCI fields (extracted from CCI message header)
    cci_opcode: int
    cci_tag: int
    cci_payload: bytes

    # PEC
    pec: int
    pec_valid: bool

    @classmethod
    def parse(cls, raw: bytes, verify_pec: bool = True) -> "SmbusMctpRequest":
        """
        Parse a raw SMBus+MCTP request byte string.

        Raises ValueError on framing errors (too short, bad cmd code).
        Raises ValueError on PEC mismatch if verify_pec=True.
        """
        if len(raw) < SMBUS_REQ_MIN_LEN:
            raise ValueError(
                f"SMBus request too short: {len(raw)} bytes "
                f"(minimum {SMBUS_REQ_MIN_LEN})"
            )

        # ── SMBus header ──────────────────────────────────────────────
        dest_slave_addr = raw[0]
        command_code    = raw[1]
        byte_count      = raw[2]
        src_slave_addr  = raw[3]

        if command_code != SMBUS_MCTP_COMMAND_CODE:
            raise ValueError(
                f"Bad SMBus command code 0x{command_code:02X} "
                f"(expected 0x{SMBUS_MCTP_COMMAND_CODE:02X})"
            )

        # ── MCTP transport header ─────────────────────────────────────
        hdr_ver  = raw[4]
        dest_eid = raw[5]
        src_eid  = raw[6]
        flags    = raw[7]

        som     = (flags >> 7) & 0x1
        eom     = (flags >> 6) & 0x1
        pkt_seq = (flags >> 4) & 0x3
        to      = (flags >> 3) & 0x1
        msg_tag = flags & 0x7

        # ── MCTP message type ─────────────────────────────────────────
        msg_type_byte = raw[8]
        ic            = (msg_type_byte >> 7) & 0x1
        msg_type      = msg_type_byte & 0x7F

        # ── CCI message bytes (between msg_type and PEC) ──────────────
        cci_bytes = raw[SMBUS_REQ_HDR_SIZE : -PEC_SIZE]
        pec       = raw[-1]

        if len(cci_bytes) < CCI_MSG_HDR_SIZE:
            raise ValueError(
                f"CCI message too short: {len(cci_bytes)} bytes "
                f"(minimum {CCI_MSG_HDR_SIZE})"
            )

        cci_hdr      = cci_bytes[:CCI_MSG_HDR_SIZE]
        cci_opcode   = _cci_get_opcode(cci_hdr)
        cci_tag      = _cci_get_tag(cci_hdr)
        cci_plen     = _cci_get_payload_length(cci_hdr)
        cci_payload  = cci_bytes[CCI_MSG_HDR_SIZE : CCI_MSG_HDR_SIZE + cci_plen]

        # ── PEC verification ──────────────────────────────────────────
        expected_pec = crc8_smbus(raw[:-1])
        pec_valid    = (expected_pec == pec)
        if verify_pec and not pec_valid:
            raise ValueError(
                f"PEC mismatch: received 0x{pec:02X}, "
                f"computed 0x{expected_pec:02X}"
            )

        return cls(
            dest_slave_addr=dest_slave_addr,
            command_code=command_code,
            byte_count=byte_count,
            src_slave_addr=src_slave_addr,
            hdr_ver=hdr_ver,
            dest_eid=dest_eid,
            src_eid=src_eid,
            som=som,
            eom=eom,
            pkt_seq=pkt_seq,
            to=to,
            msg_tag=msg_tag,
            msg_type_byte=msg_type_byte,
            ic=ic,
            msg_type=msg_type,
            cci_opcode=cci_opcode,
            cci_tag=cci_tag,
            cci_payload=cci_payload,
            pec=pec,
            pec_valid=pec_valid,
        )


# ── SmbusMctpResponse builder ──────────────────────────────────────────────────

def build_smbus_mctp_response(
    request: SmbusMctpRequest,
    return_code: int,
    response_payload: bytes,
    is_background: bool,
    fm_i2c_addr: int = 0x10,
    compute_pec: bool = True,
) -> bytes:
    """
    Build a complete SMBus+MCTP response frame for the given request.

    Args:
        request:          the parsed incoming request
        return_code:      CCI return code (0=SUCCESS, 1=BACKGROUND, etc.)
        response_payload: raw CCI response payload bytes from switch
        is_background:    True if switch returned BACKGROUND_COMMAND_STARTED
        fm_i2c_addr:      FM's 7-bit I2C address (default 0x10)
        compute_pec:      compute and append CRC-8 PEC byte

    Response frame layout:
        [0]   byte_count
        [1]   fm_src_addr  = fm_i2c_addr << 1 | 0x01
        [2]   hdr_ver      = 0x01
        [3]   dest_eid     = request.src_eid   (device that sent the request)
        [4]   src_eid      = request.dest_eid  (FM's EID)
        [5]   flags        = SOM|EOM|PktSeq=0|TO=0|msg_tag
        [6]   msg_type     = same as request
        [7..18]  CCI response header (12 bytes)
        [19..N]  CCI response payload
        [N+1] PEC
    """
    # Build CCI response header + payload
    cci_hdr = _build_cci_response_header(
        tag=request.cci_tag,
        opcode=request.cci_opcode,
        payload_len=len(response_payload),
        return_code=return_code,
        is_background=is_background,
    )
    cci_msg = cci_hdr + response_payload

    # MCTP transport header flags for response
    # SOM=1, EOM=1, PktSeq=0, TO=0 (response), same msg_tag as request
    flags = 0xC0 | (request.msg_tag & 0x7)

    # FM source address (with read bit set)
    fm_src_addr = (fm_i2c_addr << 1) | 0x01

    # Build body (everything after byte_count)
    body = bytes([
        fm_src_addr,           # [1] FM responding
        MCTP_HDR_VERSION,      # [2]
        request.src_eid,       # [3] dest = device that sent the request
        request.dest_eid,      # [4] src  = FM EID
        flags,                 # [5]
        request.msg_type_byte, # [6] same message type as request
    ]) + cci_msg

    # Prepend byte_count (counts bytes in body, i.e. len(body))
    byte_count = len(body)
    frame = bytes([byte_count]) + body

    # Append PEC
    if compute_pec:
        frame += bytes([crc8_smbus(frame)])

    return frame


# ── Async frame reader ─────────────────────────────────────────────────────────

async def read_smbus_frame(reader) -> bytes:
    """
    Read one complete SMBus+MCTP frame from an asyncio StreamReader.

    SMBus length framing:
      Byte[0] = dest_slave_addr  (not byte_count)
      Byte[1] = command_code     = 0x0F
      Byte[2] = byte_count       = N  (number of remaining bytes before PEC)
      Bytes[3..3+N-1] = payload
      Byte[3+N] = PEC

    Total frame length = 3 + N + 1 = N + 4
    """
    # Read the first 3 bytes (dest_addr, cmd_code, byte_count)
    header = await reader.readexactly(3)
    dest_addr    = header[0]
    command_code = header[1]
    byte_count   = header[2]

    # Read remaining bytes: byte_count more bytes + 1 PEC byte
    # byte_count = bytes from src_addr onward, not including PEC
    # But per DSP0237: byte_count = number of data bytes from the 4th byte
    # onward up to (but not including) PEC
    # So: total remaining = byte_count + PEC_SIZE
    remaining = await reader.readexactly(byte_count + PEC_SIZE)

    return header + remaining
