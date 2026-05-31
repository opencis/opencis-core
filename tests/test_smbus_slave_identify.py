"""
tests/test_smbus_slave_identify.py
====================================
pytest test cases for the SMBus Slave → Identify PBR Switch scenario.

Tests the full pipeline:

  SMBus Slave  →  [DSP0237 SMBus frame]  →  FmSmbusMctpServer (port 8301)
  FmSmbusMctpServer  →  depacketize  →  mock MctpCciApiClient
  mock client  →  IDENTIFY_PBR_SWITCH response
  FmSmbusMctpServer  →  repacketize  →  SMBus response frame
  test  →  parse response  →  assert fields

Architecture under test:
  ┌──────────────────────────────────────────────────────────┐
  │                   FmSmbusMctpServer                       │
  │                                                           │
  │  TCP 8301 ←─ SMBus frame (DSP0237) ─── SMBus Slave sim   │
  │      │                                                     │
  │      ▼                                                     │
  │  SmbusMctpRequest.parse()   (depacketize)                  │
  │      │                                                     │
  │      ▼                                                     │
  │  _forward_to_cli(opcode, payload)                          │
  │      │                                                     │
  │      ▼                                                     │
  │  MockMctpCciApiClient.send_raw_cci()  ← mock switch       │
  │      │                                                     │
  │      ▼                                                     │
  │  build_smbus_mctp_response()   (repacketize)               │
  │      │                                                     │
  │  TCP 8301 ──→ SMBus response ───────► test asserts         │
  └──────────────────────────────────────────────────────────┘

Test cases:
  1. test_slave_identify_basic
       Slave sends IDENTIFY_PBR_SWITCH (0x5700) with no payload.
       Server returns SMBus response with SUCCESS and Identify payload.

  2. test_slave_identify_response_fields
       Verify every field in the SMBus response frame is correct:
       byte_count, fm_src_addr, hdr_ver, EIDs, flags, msg_type,
       CCI category, CCI opcode, return_code, cci_tag, payload.

  3. test_slave_identify_pec_correct
       PEC (CRC-8) in response must match recomputed value.

  4. test_slave_identify_echoes_eid
       Response dest_eid = request src_eid, src_eid = request dest_eid.

  5. test_slave_identify_echoes_msg_tag
       Response msg_tag must match request msg_tag (low 3 bits).

  6. test_slave_identify_no_client_returns_unsupported
       Without a bound MctpCciApiClient, server returns UNSUPPORTED (3).

  7. test_slave_identify_multiple_sequential
       Send 3 Identify requests sequentially; all succeed.

  8. test_slave_identify_with_real_pbr_payload
       Mock returns a realistic Identify PBR payload (num_drts=1, etc.)
       and the test parses + validates each field.

  9. test_slave_identify_pec_verify_rejected
       Server with verify_pec=True rejects a frame with a corrupted PEC
       and returns INVALID_INPUT.

 10. test_slave_identify_bad_command_code_rejected
       Frame with wrong SMBus command code (not 0x0F) is rejected.
"""

import asyncio
import struct
import pytest

from opencis.cxl.component.mctp.fm_smbus_mctp_server import FmSmbusMctpServer
from opencis.cxl.component.mctp.smbus_mctp_framing import (
    SmbusMctpRequest,
    build_smbus_mctp_response,
    crc8_smbus,
    SMBUS_MCTP_COMMAND_CODE,
)
from opencis.cxl.cci.common import CCI_RETURN_CODE, CCI_FM_API_COMMAND_OPCODE


# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

OPCODE_IDENTIFY   = int(CCI_FM_API_COMMAND_OPCODE.IDENTIFY_PBR_SWITCH)   # 0x5700

FM_I2C_ADDR   = 0x10   # 7-bit I2C address of the FM
DEV_I2C_ADDR  = 0x20   # 7-bit I2C address of the SMBus slave device
FM_EID        = 0x08   # MCTP EID of the FM
DEV_EID       = 0x09   # MCTP EID of the slave device
MCTP_HDR_VER  = 0x01
MCTP_MSG_TYPE = 0x7E   # CXL FM API

# ─────────────────────────────────────────────────────────────────────────────
# Mock MctpCciApiClient
# ─────────────────────────────────────────────────────────────────────────────

class MockMctpCciApiClient:
    """
    Drop-in replacement for MctpCciApiClient used in unit tests.

    By default returns SUCCESS with a configurable payload.
    Set .return_code, .response_payload, .is_background to control
    what send_raw_cci() returns.
    """

    def __init__(
        self,
        return_code: int = CCI_RETURN_CODE.SUCCESS,
        response_payload: bytes = b"",
        is_background: bool = False,
    ):
        self.return_code      = return_code
        self.response_payload = response_payload
        self.is_background    = is_background
        self.calls: list      = []   # log of (opcode, payload) tuples

    async def send_raw_cci(
        self,
        opcode: int,
        payload: bytes,
        port_index: int = 0,
    ):
        self.calls.append((opcode, payload))
        return (self.return_code, self.response_payload, self.is_background)


# ─────────────────────────────────────────────────────────────────────────────
# Frame builders / parsers (inline so tests have zero external deps)
# ─────────────────────────────────────────────────────────────────────────────

def _crc8(data: bytes) -> int:
    """CRC-8 with poly 0x07 (same as smbus_mctp_framing.crc8_smbus)."""
    crc = 0
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = ((crc << 1) ^ 0x07) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc


def build_slave_request(
    opcode: int,
    cci_payload: bytes = b"",
    cci_tag: int = 0,
    msg_tag: int = 0,
    corrupt_pec: bool = False,
    bad_cmd_code: bool = False,
) -> bytes:
    """
    Build a raw DSP0237 SMBus+MCTP request as a SMBus Slave would send it.

    Frame layout (matching SmbusMctpRequest.parse()):
      [0]  dest_slave_addr = FM_I2C_ADDR << 1 | 0    (WRITE direction)
      [1]  command_code    = 0x0F  (MCTP over SMBus)
      [2]  byte_count
      [3]  src_slave_addr  = DEV_I2C_ADDR << 1 | 1   (READ bit set)
      [4]  hdr_ver         = 0x01
      [5]  dest_eid        = FM_EID
      [6]  src_eid         = DEV_EID
      [7]  flags           = SOM|EOM|TO=1|msg_tag
      [8]  msg_type        = 0x7E  (CXL FM API, IC=0)
      [9..20]  CCI message header (12 bytes)
      [21+]    CCI payload
      [last]   PEC (CRC-8)
    """
    plen = len(cci_payload)
    cci_hdr = bytearray(12)
    cci_hdr[0]  = 0x00                      # message_category = REQUEST
    cci_hdr[1]  = cci_tag & 0xFF            # message_tag
    cci_hdr[2]  = 0x00                      # reserved
    cci_hdr[3]  = opcode & 0xFF             # opcode low byte
    cci_hdr[4]  = (opcode >> 8) & 0xFF      # opcode high byte
    cci_hdr[5]  = plen & 0xFF               # payload_length[7:0]
    cci_hdr[6]  = (plen >> 8) & 0xFF        # payload_length[15:8]
    cci_hdr[7]  = (plen >> 16) & 0x1F      # payload_length[20:16]
    # bytes 8-11: return_code = 0 in request

    cci_msg = bytes(cci_hdr) + cci_payload

    # MCTP flags: SOM=1, EOM=1, PktSeq=0, TO=1, msg_tag
    flags = 0xC0 | 0x08 | (msg_tag & 0x7)

    body = bytes([
        (DEV_I2C_ADDR << 1) | 0x01,  # src_slave_addr (READ bit)
        MCTP_HDR_VER,                 # hdr_ver
        FM_EID,                       # dest_eid
        DEV_EID,                      # src_eid
        flags,                        # MCTP flags
        MCTP_MSG_TYPE,                # msg_type = CXL FM API
    ]) + cci_msg

    cmd_code   = 0xFF if bad_cmd_code else SMBUS_MCTP_COMMAND_CODE
    dest_addr  = (FM_I2C_ADDR << 1) & 0xFE  # write direction
    byte_count = len(body)

    frame = bytes([dest_addr, cmd_code, byte_count]) + body
    pec   = _crc8(frame)
    if corrupt_pec:
        pec = (pec ^ 0xFF) & 0xFF   # flip all bits → guaranteed bad PEC
    return frame + bytes([pec])


def parse_response(raw: bytes) -> dict:
    """
    Parse a raw SMBus+MCTP response frame produced by build_smbus_mctp_response().

    Response layout:
      [0]   byte_count
      [1]   fm_src_addr  (FM_I2C_ADDR << 1 | 1)
      [2]   hdr_ver
      [3]   dest_eid     (device that sent the request)
      [4]   src_eid      (FM)
      [5]   flags
      [6]   msg_type_byte
      [7..18]  CCI response header (12 bytes)
      [19+]    CCI response payload
      [last]   PEC
    """
    assert len(raw) >= 20, f"Response too short: {len(raw)} bytes"

    byte_count   = raw[0]
    fm_src_addr  = raw[1]
    hdr_ver      = raw[2]
    dest_eid     = raw[3]
    src_eid      = raw[4]
    flags        = raw[5]
    msg_type     = raw[6] & 0x7F
    pec          = raw[-1]
    pec_expected = _crc8(raw[:-1])

    cci_hdr      = raw[7:19]   # 12-byte CCI header
    category     = cci_hdr[0] & 0x0F
    cci_tag      = cci_hdr[1]
    opcode       = int.from_bytes(cci_hdr[3:5], "little")
    plen         = int.from_bytes(cci_hdr[5:7], "little") | ((cci_hdr[7] & 0x1F) << 16)
    background   = (cci_hdr[7] >> 7) & 1
    return_code  = int.from_bytes(cci_hdr[8:10], "little")
    cci_payload  = raw[19: 19 + plen]

    return {
        "byte_count":   byte_count,
        "fm_src_addr":  fm_src_addr,
        "hdr_ver":      hdr_ver,
        "dest_eid":     dest_eid,
        "src_eid":      src_eid,
        "msg_tag":      flags & 0x7,
        "flags":        flags,
        "msg_type":     msg_type,
        "pec":          pec,
        "pec_expected": pec_expected,
        "pec_ok":       pec == pec_expected,
        "category":     category,
        "cci_tag":      cci_tag,
        "opcode":       opcode,
        "return_code":  return_code,
        "background":   background,
        "cci_payload":  cci_payload,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Helpers — start server + TCP client
# ─────────────────────────────────────────────────────────────────────────────

async def _recv_smbus_response(reader: asyncio.StreamReader) -> bytes:
    """
    Read one complete SMBus+MCTP response frame from an asyncio StreamReader.

    Response framing (from build_smbus_mctp_response):
      Byte[0]          = byte_count  (number of remaining bytes before PEC)
      Byte[1..N]       = body  (byte_count bytes)
      Byte[N+1]        = PEC
    Total = 1 + byte_count + 1
    """
    bc_byte    = await reader.readexactly(1)
    byte_count = bc_byte[0]
    rest       = await reader.readexactly(byte_count + 1)  # body + PEC
    return bc_byte + rest


async def _start_server(mock_client=None, verify_pec: bool = False):
    """
    Start an FmSmbusMctpServer on a random port and return (server, port, task).
    """
    server = FmSmbusMctpServer(
        host="127.0.0.1",
        port=0,                  # OS picks a free port
        mctp_client=mock_client,
        fm_i2c_addr=FM_I2C_ADDR,
        verify_pec=verify_pec,
    )
    task = asyncio.create_task(server.run())
    await server.wait_for_ready()
    port = server.get_port()
    return server, port, task


async def _stop_server(server, task):
    await server._stop()
    task.cancel()
    try:
        await task
    except (asyncio.CancelledError, Exception):
        pass


async def _do_transaction(port: int, frame: bytes) -> bytes:
    """Send one SMBus frame and receive the response."""
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(frame)
    await writer.drain()
    resp = await asyncio.wait_for(_recv_smbus_response(reader), timeout=5.0)
    writer.close()
    await writer.wait_closed()
    return resp


# ─────────────────────────────────────────────────────────────────────────────
# Realistic Identify PBR Switch payload builder
# ─────────────────────────────────────────────────────────────────────────────

def make_identify_pbr_payload(
    gae_support_map: int = 0x01,  # bit 0 = VCS 0 supports GAE
    num_drts: int = 1,
    num_rgts: int = 0,
    routing_caps: int = 0x00,     # no special routing modes
) -> bytes:
    """
    Build a realistic IDENTIFY_PBR_SWITCH response payload (12 bytes).
    Matches IdentifyPbrSwitchResponsePayload.dump() from the production code.

      Byte 0x00..0x07  GAE Support Map (8 bytes, little-endian)
      Byte 0x08        Num DRTs
      Byte 0x09        Num RGTs
      Byte 0x0A        Reserved
      Byte 0x0B        Routing Caps
    """
    data = bytearray(12)
    data[0x00:0x08] = gae_support_map.to_bytes(8, "little")
    data[0x08] = num_drts & 0xFF
    data[0x09] = num_rgts & 0xFF
    data[0x0A] = 0
    data[0x0B] = routing_caps & 0xFF
    return bytes(data)


# ─────────────────────────────────────────────────────────────────────────────
# ① Basic: slave sends Identify, gets SUCCESS response
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_slave_identify_basic():
    """
    SMBus Slave sends IDENTIFY_PBR_SWITCH (0x5700) with no payload.
    Server must return a SMBus response frame with return_code = SUCCESS (0).
    """
    mock_client = MockMctpCciApiClient(
        return_code=CCI_RETURN_CODE.SUCCESS,
        response_payload=make_identify_pbr_payload(),
    )
    server, port, task = await _start_server(mock_client)
    try:
        frame = build_slave_request(opcode=OPCODE_IDENTIFY)
        raw   = await _do_transaction(port, frame)
        resp  = parse_response(raw)

        assert resp["return_code"] == 0, \
            f"Expected SUCCESS (0), got {resp['return_code']}"
        assert resp["opcode"] == OPCODE_IDENTIFY, \
            f"Expected opcode 0x{OPCODE_IDENTIFY:04X}, got 0x{resp['opcode']:04X}"
        assert len(resp["cci_payload"]) == 12, \
            f"Identify response should be 12 bytes, got {len(resp['cci_payload'])}"
    finally:
        await _stop_server(server, task)


# ─────────────────────────────────────────────────────────────────────────────
# ② Every field in the response frame is correct
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_slave_identify_response_fields():
    """
    Validate every header field in the SMBus+MCTP response:
      - fm_src_addr = FM_I2C_ADDR << 1 | 1
      - hdr_ver     = 0x01
      - msg_type    = 0x7E  (CXL FM API)
      - category    = 1     (RESPONSE)
      - return_code = 0     (SUCCESS)
      - opcode      = 0x5700
      - background  = 0
    """
    identify_payload = make_identify_pbr_payload(num_drts=2, num_rgts=1)
    mock_client = MockMctpCciApiClient(
        return_code=CCI_RETURN_CODE.SUCCESS,
        response_payload=identify_payload,
    )
    server, port, task = await _start_server(mock_client)
    try:
        frame = build_slave_request(opcode=OPCODE_IDENTIFY, cci_tag=5, msg_tag=3)
        raw   = await _do_transaction(port, frame)
        resp  = parse_response(raw)

        assert resp["fm_src_addr"] == (FM_I2C_ADDR << 1) | 1, \
            "fm_src_addr must be FM I2C addr with READ bit"
        assert resp["hdr_ver"] == MCTP_HDR_VER, \
            f"hdr_ver should be 0x{MCTP_HDR_VER:02X}"
        assert resp["msg_type"] == 0x7E, \
            "msg_type must be 0x7E (CXL FM API)"
        assert resp["category"] == 1, \
            "category must be 1 (RESPONSE)"
        assert resp["return_code"] == 0, \
            "return_code must be SUCCESS (0)"
        assert resp["opcode"] == OPCODE_IDENTIFY, \
            f"opcode must be 0x{OPCODE_IDENTIFY:04X}"
        assert resp["background"] == 0, \
            "background must be 0 for Identify (foreground command)"
        assert resp["cci_payload"] == identify_payload, \
            "CCI payload must match what the mock switch returned"
    finally:
        await _stop_server(server, task)


# ─────────────────────────────────────────────────────────────────────────────
# ③ PEC in response is correct
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_slave_identify_pec_correct():
    """
    The PEC byte appended to the SMBus response must equal CRC-8 over
    all preceding bytes (computed locally and compared to recomputed value).
    """
    mock_client = MockMctpCciApiClient(
        return_code=CCI_RETURN_CODE.SUCCESS,
        response_payload=make_identify_pbr_payload(),
    )
    server, port, task = await _start_server(mock_client)
    try:
        frame = build_slave_request(opcode=OPCODE_IDENTIFY)
        raw   = await _do_transaction(port, frame)
        resp  = parse_response(raw)

        assert resp["pec_ok"], \
            (f"Response PEC bad: got 0x{resp['pec']:02X}, "
             f"expected 0x{resp['pec_expected']:02X}")
    finally:
        await _stop_server(server, task)


# ─────────────────────────────────────────────────────────────────────────────
# ④ Response EIDs are swapped correctly (dest↔src)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_slave_identify_echoes_eid():
    """
    In the response:
      dest_eid = request.src_eid   (= DEV_EID = 0x09)
      src_eid  = request.dest_eid  (= FM_EID  = 0x08)
    """
    mock_client = MockMctpCciApiClient(
        return_code=CCI_RETURN_CODE.SUCCESS,
        response_payload=make_identify_pbr_payload(),
    )
    server, port, task = await _start_server(mock_client)
    try:
        frame = build_slave_request(opcode=OPCODE_IDENTIFY)
        raw   = await _do_transaction(port, frame)
        resp  = parse_response(raw)

        assert resp["dest_eid"] == DEV_EID, \
            f"resp.dest_eid should be device EID 0x{DEV_EID:02X}, got 0x{resp['dest_eid']:02X}"
        assert resp["src_eid"] == FM_EID, \
            f"resp.src_eid should be FM EID 0x{FM_EID:02X}, got 0x{resp['src_eid']:02X}"
    finally:
        await _stop_server(server, task)


# ─────────────────────────────────────────────────────────────────────────────
# ⑤ Response msg_tag matches request msg_tag
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_slave_identify_echoes_msg_tag():
    """
    The 3-bit msg_tag in the response flags byte must match the one in the
    request so the slave can correlate request → response.
    """
    mock_client = MockMctpCciApiClient(
        return_code=CCI_RETURN_CODE.SUCCESS,
        response_payload=make_identify_pbr_payload(),
    )
    server, port, task = await _start_server(mock_client)
    try:
        for expected_tag in (0, 1, 3, 5, 7):
            frame = build_slave_request(
                opcode=OPCODE_IDENTIFY, msg_tag=expected_tag
            )
            raw  = await _do_transaction(port, frame)
            resp = parse_response(raw)

            assert resp["msg_tag"] == expected_tag, \
                (f"msg_tag mismatch: sent {expected_tag}, "
                 f"got {resp['msg_tag']}")
    finally:
        await _stop_server(server, task)


# ─────────────────────────────────────────────────────────────────────────────
# ⑥ No client bound → UNSUPPORTED
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_slave_identify_no_client_returns_unsupported():
    """
    When FmSmbusMctpServer has no MctpCciApiClient bound (offline mode),
    every CCI command must return UNSUPPORTED (return_code = 3).
    """
    server, port, task = await _start_server(mock_client=None)
    try:
        frame = build_slave_request(opcode=OPCODE_IDENTIFY)
        raw   = await _do_transaction(port, frame)
        resp  = parse_response(raw)

        assert resp["return_code"] == int(CCI_RETURN_CODE.UNSUPPORTED), \
            (f"Expected UNSUPPORTED ({int(CCI_RETURN_CODE.UNSUPPORTED)}), "
             f"got {resp['return_code']}")
        assert resp["cci_payload"] == b"", \
            "UNSUPPORTED response should have empty payload"
    finally:
        await _stop_server(server, task)


# ─────────────────────────────────────────────────────────────────────────────
# ⑦ Multiple sequential Identify requests all succeed
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_slave_identify_multiple_sequential():
    """
    Three Identify requests sent in sequence on the same TCP connection
    must all succeed with independent responses.
    """
    mock_client = MockMctpCciApiClient(
        return_code=CCI_RETURN_CODE.SUCCESS,
        response_payload=make_identify_pbr_payload(),
    )
    server, port, task = await _start_server(mock_client)
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)

        for i in range(3):
            frame = build_slave_request(
                opcode=OPCODE_IDENTIFY, cci_tag=i, msg_tag=i % 8
            )
            writer.write(frame)
            await writer.drain()
            raw  = await asyncio.wait_for(
                _recv_smbus_response(reader), timeout=5.0
            )
            resp = parse_response(raw)

            assert resp["return_code"] == 0, \
                f"Request {i}: expected SUCCESS, got {resp['return_code']}"
            assert resp["cci_tag"] == i, \
                f"Request {i}: expected cci_tag={i}, got {resp['cci_tag']}"

        writer.close()
        await writer.wait_closed()

        assert len(mock_client.calls) == 3, \
            f"Expected 3 calls to send_raw_cci, got {len(mock_client.calls)}"
        for opcode, payload in mock_client.calls:
            assert opcode == OPCODE_IDENTIFY
            assert payload == b""
    finally:
        await _stop_server(server, task)


# ─────────────────────────────────────────────────────────────────────────────
# ⑧ Parse and validate realistic Identify PBR payload fields
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_slave_identify_with_real_pbr_payload():
    """
    Mock returns a realistic IdentifyPbrSwitch payload:
      gae_support_map = 0x01  (VCS 0 supports GAE)
      num_drts        = 2
      num_rgts        = 1
      routing_caps    = 0x03  (Random + CongestionAvoidance)

    The test parses the CCI payload and verifies each field.
    """
    EXPECTED_GAE_MAP      = 0x01
    EXPECTED_NUM_DRTS     = 2
    EXPECTED_NUM_RGTS     = 1
    EXPECTED_ROUTING_CAPS = 0x03

    identify_payload = make_identify_pbr_payload(
        gae_support_map=EXPECTED_GAE_MAP,
        num_drts=EXPECTED_NUM_DRTS,
        num_rgts=EXPECTED_NUM_RGTS,
        routing_caps=EXPECTED_ROUTING_CAPS,
    )

    mock_client = MockMctpCciApiClient(
        return_code=CCI_RETURN_CODE.SUCCESS,
        response_payload=identify_payload,
    )
    server, port, task = await _start_server(mock_client)
    try:
        frame = build_slave_request(opcode=OPCODE_IDENTIFY)
        raw   = await _do_transaction(port, frame)
        resp  = parse_response(raw)

        assert resp["return_code"] == 0
        assert len(resp["cci_payload"]) == 12

        # Parse the Identify PBR payload manually
        payload        = resp["cci_payload"]
        gae_support_map = int.from_bytes(payload[0x00:0x08], "little")
        num_drts        = payload[0x08]
        num_rgts        = payload[0x09]
        routing_caps    = payload[0x0B]

        assert gae_support_map == EXPECTED_GAE_MAP, \
            f"gae_support_map: expected {EXPECTED_GAE_MAP:#x}, got {gae_support_map:#x}"
        assert num_drts == EXPECTED_NUM_DRTS, \
            f"num_drts: expected {EXPECTED_NUM_DRTS}, got {num_drts}"
        assert num_rgts == EXPECTED_NUM_RGTS, \
            f"num_rgts: expected {EXPECTED_NUM_RGTS}, got {num_rgts}"
        assert routing_caps == EXPECTED_ROUTING_CAPS, \
            f"routing_caps: expected {EXPECTED_ROUTING_CAPS:#x}, got {routing_caps:#x}"

        # Verify routing capabilities bits
        random_supported = bool(routing_caps & 0x01)
        cong_av_supported = bool(routing_caps & 0x02)
        assert random_supported,    "Bit 0 (Random) should be set"
        assert cong_av_supported,   "Bit 1 (CongestionAvoidance) should be set"
    finally:
        await _stop_server(server, task)


# ─────────────────────────────────────────────────────────────────────────────
# ⑨ Bad PEC → INVALID_INPUT when verify_pec=True
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_slave_identify_pec_verify_rejected():
    """
    When FmSmbusMctpServer is started with verify_pec=True and the slave
    sends a frame with a corrupted PEC byte, the server must:
      - Not crash
      - Return an INVALID_INPUT error response
    """
    mock_client = MockMctpCciApiClient(
        return_code=CCI_RETURN_CODE.SUCCESS,
        response_payload=make_identify_pbr_payload(),
    )
    # verify_pec=True → server rejects bad PEC
    server, port, task = await _start_server(mock_client, verify_pec=True)
    try:
        bad_frame = build_slave_request(
            opcode=OPCODE_IDENTIFY, corrupt_pec=True
        )
        raw  = await _do_transaction(port, bad_frame)
        resp = parse_response(raw)

        assert resp["return_code"] == int(CCI_RETURN_CODE.INVALID_INPUT), \
            (f"Expected INVALID_INPUT ({int(CCI_RETURN_CODE.INVALID_INPUT)}), "
             f"got {resp['return_code']}")

        # send_raw_cci must NOT have been called (bad frame rejected before forwarding)
        assert len(mock_client.calls) == 0, \
            "send_raw_cci should not be called for a bad-PEC frame"
    finally:
        await _stop_server(server, task)


# ─────────────────────────────────────────────────────────────────────────────
# ⑩ Wrong SMBus command code → INVALID_INPUT error frame
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_slave_identify_bad_command_code_rejected():
    """
    SMBus command code must be 0x0F (MCTP).
    A frame with any other command code must be rejected with INVALID_INPUT
    and must NOT reach the FM CLI path.
    """
    mock_client = MockMctpCciApiClient(
        return_code=CCI_RETURN_CODE.SUCCESS,
        response_payload=make_identify_pbr_payload(),
    )
    server, port, task = await _start_server(mock_client)
    try:
        bad_frame = build_slave_request(
            opcode=OPCODE_IDENTIFY, bad_cmd_code=True
        )
        raw  = await _do_transaction(port, bad_frame)
        resp = parse_response(raw)

        assert resp["return_code"] == int(CCI_RETURN_CODE.INVALID_INPUT), \
            (f"Expected INVALID_INPUT ({int(CCI_RETURN_CODE.INVALID_INPUT)}), "
             f"got {resp['return_code']}")
        assert len(mock_client.calls) == 0, \
            "send_raw_cci must not be called for a bad command code frame"
    finally:
        await _stop_server(server, task)
