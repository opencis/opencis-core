"""
tests/test_smbus_dual_port.py
==============================
pytest tests for FmSmbusDualPortServer — VDI-independent timing.

Architecture under test:
  ┌──────────────────────────────────────────────────────────────┐
  │                FmSmbusDualPortServer                          │
  │                                                              │
  │  TCP req_port ←── SMBus Slave (test) ─── asyncio connect    │
  │       │                                                       │
  │       ▼  SmbusMctpRequest.parse()                            │
  │       │  _forward_to_cli(opcode, payload)                    │
  │       ▼  MockMctpCciApiClient.send_raw_cci()                 │
  │       │  build_smbus_mctp_response()                         │
  │       ▼  asyncio.Queue.put()                                 │
  │       │  asyncio.sleep(0)  ← YIELD (fixes slow-VDI race)     │
  │       ▼                                                       │
  │  asyncio.Queue.get()                                          │
  │       │                                                       │
  │  TCP resp_port ──► SMBus Master (test) reads response        │
  └──────────────────────────────────────────────────────────────┘

Why these tests are VDI-independent
------------------------------------
1. Port 0 — OS picks free ports → no 8301/8302 collisions in parallel.
2. asyncio instead of blocking sockets → no fixed recv() timeout.
3. MASTER connects BEFORE SLAVE sends → queue always has a consumer.
4. asyncio.wait_for(timeout=30) → generous but bounded.
5. All asyncio primitives created inside _run() → correct event loop.

Tests
------
  1. test_dual_port_identify_basic
       Slave sends IDENTIFY_PBR_SWITCH; Master receives SUCCESS response.

  2. test_dual_port_response_fields
       Validate every field in the response frame (EIDs, PEC, opcode, rc).

  3. test_dual_port_multiple_sequential
       5 requests in sequence; each response arrives on the master port.

  4. test_dual_port_no_client_returns_unsupported
       No MctpCciApiClient bound → UNSUPPORTED delivered to Master.

  5. test_dual_port_bad_pec_returns_invalid_input
       Slave sends frame with corrupted PEC; Master receives INVALID_INPUT.

  6. test_dual_port_background_command
       CONFIGURE_PID_BINDING returns BACKGROUND (rc=1, background=1).

  7. test_dual_port_master_connects_after_slave
       Master connects AFTER the response is already in the queue;
       must still receive the frame (queue buffers it).

  8. test_dual_port_two_slaves_sequential
       Slave 1 and Slave 2 each send one command; Master sees both responses.
"""

import asyncio
import struct
import pytest

from opencis.cxl.component.mctp.fm_smbus_dual_port_server import FmSmbusDualPortServer
from opencis.cxl.component.mctp.smbus_mctp_framing import (
    SMBUS_MCTP_COMMAND_CODE,
)
from opencis.cxl.cci.common import CCI_RETURN_CODE, CCI_FM_API_COMMAND_OPCODE


# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

OPCODE_IDENTIFY = int(CCI_FM_API_COMMAND_OPCODE.IDENTIFY_PBR_SWITCH)   # 0x5700
OPCODE_BIND     = int(CCI_FM_API_COMMAND_OPCODE.CONFIGURE_PID_BINDING) # 0x5706

FM_I2C_ADDR  = 0x10
DEV_I2C_ADDR = 0x20
FM_EID       = 0x08
DEV_EID      = 0x09
MCTP_HDR_VER = 0x01
MCTP_MSG_TYPE = 0x7E


# ─────────────────────────────────────────────────────────────────────────────
# Mock MctpCciApiClient
# ─────────────────────────────────────────────────────────────────────────────

class MockMctpCciApiClient:
    """Configurable mock for send_raw_cci()."""

    def __init__(
        self,
        return_code: int = CCI_RETURN_CODE.SUCCESS,
        response_payload: bytes = b"",
        is_background: bool = False,
    ):
        self.return_code      = return_code
        self.response_payload = response_payload
        self.is_background    = is_background
        self.calls: list      = []

    async def send_raw_cci(self, opcode: int, payload: bytes, port_index: int = 0):
        self.calls.append((opcode, payload))
        return (self.return_code, self.response_payload, self.is_background)


# ─────────────────────────────────────────────────────────────────────────────
# Frame builder / parser helpers
# ─────────────────────────────────────────────────────────────────────────────

def _crc8(data: bytes) -> int:
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
) -> bytes:
    """Build a raw DSP0237 SMBus+MCTP request frame."""
    plen = len(cci_payload)
    cci_hdr = bytearray(12)
    cci_hdr[0] = 0x00               # REQUEST
    cci_hdr[1] = cci_tag & 0xFF
    cci_hdr[3] = opcode & 0xFF
    cci_hdr[4] = (opcode >> 8) & 0xFF
    cci_hdr[5] = plen & 0xFF
    cci_hdr[6] = (plen >> 8) & 0xFF
    cci_hdr[7] = (plen >> 16) & 0x1F
    cci_msg = bytes(cci_hdr) + cci_payload

    flags = 0xC0 | 0x08 | (msg_tag & 0x7)   # SOM|EOM|TO
    body = bytes([
        (DEV_I2C_ADDR << 1) | 0x01,
        MCTP_HDR_VER, FM_EID, DEV_EID, flags, MCTP_MSG_TYPE,
    ]) + cci_msg

    dest_addr  = (FM_I2C_ADDR << 1) & 0xFE
    byte_count = len(body)
    frame      = bytes([dest_addr, SMBUS_MCTP_COMMAND_CODE, byte_count]) + body
    pec        = _crc8(frame)
    if corrupt_pec:
        pec = (pec ^ 0xFF) & 0xFF
    return frame + bytes([pec])


def parse_response(raw: bytes) -> dict:
    """Parse a raw SMBus+MCTP response frame."""
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

    cci_hdr     = raw[7:19]
    category    = cci_hdr[0] & 0x0F
    cci_tag     = cci_hdr[1]
    opcode      = int.from_bytes(cci_hdr[3:5], "little")
    plen        = int.from_bytes(cci_hdr[5:7], "little") | ((cci_hdr[7] & 0x1F) << 16)
    background  = (cci_hdr[7] >> 7) & 1
    return_code = int.from_bytes(cci_hdr[8:10], "little")
    cci_payload = raw[19: 19 + plen]

    return {
        "byte_count":   byte_count,
        "fm_src_addr":  fm_src_addr,
        "hdr_ver":      hdr_ver,
        "dest_eid":     dest_eid,
        "src_eid":      src_eid,
        "msg_tag":      flags & 0x7,
        "msg_type":     msg_type,
        "pec":          pec,
        "pec_ok":       pec == pec_expected,
        "category":     category,
        "cci_tag":      cci_tag,
        "opcode":       opcode,
        "return_code":  return_code,
        "background":   background,
        "cci_payload":  cci_payload,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Async helpers
# ─────────────────────────────────────────────────────────────────────────────

RESPONSE_TIMEOUT = 30.0   # generous: covers even heavily loaded VDIs


async def _recv_smbus_resp(reader: asyncio.StreamReader) -> bytes:
    """Read one complete SMBus+MCTP response frame."""
    bc_byte    = await reader.readexactly(1)
    byte_count = bc_byte[0]
    rest       = await reader.readexactly(byte_count + 1)
    return bc_byte + rest


async def _start_server(mock_client=None, verify_pec: bool = False):
    """Start FmSmbusDualPortServer on OS-assigned free ports (port=0)."""
    server = FmSmbusDualPortServer(
        host="127.0.0.1",
        req_port=0,            # OS picks — no collision between parallel tests
        resp_port=0,
        mctp_client=mock_client,
        fm_i2c_addr=FM_I2C_ADDR,
        verify_pec=verify_pec,
    )
    task = asyncio.create_task(server.run())
    await server.wait_for_ready()
    req_port  = server.get_req_port()
    resp_port = server.get_resp_port()
    assert req_port  > 0, "req_port must be > 0 after start"
    assert resp_port > 0, "resp_port must be > 0 after start"
    return server, req_port, resp_port, task


async def _stop_server(server, task):
    await server._stop()
    task.cancel()
    try:
        await task
    except (asyncio.CancelledError, Exception):
        pass


async def _connect_master(resp_port: int):
    """Connect the Master (reads responses) to resp_port."""
    reader, writer = await asyncio.open_connection("127.0.0.1", resp_port)
    return reader, writer


async def _connect_slave(req_port: int):
    """Connect the Slave (sends requests) to req_port."""
    reader, writer = await asyncio.open_connection("127.0.0.1", req_port)
    return reader, writer


async def _send_and_receive(
    req_port: int,
    resp_port: int,
    frame: bytes,
) -> bytes:
    """
    Full round-trip:
      1. Connect Master to resp_port FIRST (so it's waiting before request arrives)
      2. Connect Slave to req_port
      3. Slave sends frame
      4. Master reads response
    """
    # Step 1: Master connects first — ensures consumer is ready before producer puts
    m_reader, m_writer = await asyncio.open_connection("127.0.0.1", resp_port)

    # Step 2 & 3: Slave connects and sends
    s_reader, s_writer = await asyncio.open_connection("127.0.0.1", req_port)
    s_writer.write(frame)
    await s_writer.drain()

    # Step 4: Master reads (generous timeout for slow VDIs)
    raw = await asyncio.wait_for(_recv_smbus_resp(m_reader), timeout=RESPONSE_TIMEOUT)

    # Cleanup
    s_writer.close()
    m_writer.close()
    try:
        await s_writer.wait_closed()
        await m_writer.wait_closed()
    except Exception:
        pass

    return raw


def make_identify_payload(num_drts: int = 1) -> bytes:
    """Build a realistic Identify PBR Switch response payload (12 bytes)."""
    data = bytearray(12)
    data[0] = 0x01          # gae_support_map bit 0 = VCS 0
    data[8] = num_drts
    return bytes(data)


# ─────────────────────────────────────────────────────────────────────────────
# ① Basic: Slave sends Identify, Master receives SUCCESS
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_dual_port_identify_basic():
    """
    Slave sends IDENTIFY_PBR_SWITCH on req_port.
    Master on resp_port must receive a SUCCESS (rc=0) response.
    """
    mock = MockMctpCciApiClient(
        return_code=CCI_RETURN_CODE.SUCCESS,
        response_payload=make_identify_payload(),
    )
    server, req_port, resp_port, task = await _start_server(mock)
    try:
        frame = build_slave_request(opcode=OPCODE_IDENTIFY)
        raw   = await _send_and_receive(req_port, resp_port, frame)
        resp  = parse_response(raw)

        assert resp["return_code"] == 0, f"Expected SUCCESS, got rc={resp['return_code']}"
        assert resp["opcode"] == OPCODE_IDENTIFY
        assert len(resp["cci_payload"]) == 12
    finally:
        await _stop_server(server, task)


# ─────────────────────────────────────────────────────────────────────────────
# ② All response header fields correct
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_dual_port_response_fields():
    """
    Verify every header field in the response:
      fm_src_addr, hdr_ver, dest_eid, src_eid, msg_type,
      CCI category, opcode, return_code, background=0, PEC.
    """
    identify_payload = make_identify_payload(num_drts=3)
    mock = MockMctpCciApiClient(
        return_code=CCI_RETURN_CODE.SUCCESS,
        response_payload=identify_payload,
    )
    server, req_port, resp_port, task = await _start_server(mock)
    try:
        frame = build_slave_request(opcode=OPCODE_IDENTIFY, cci_tag=7, msg_tag=5)
        raw   = await _send_and_receive(req_port, resp_port, frame)
        resp  = parse_response(raw)

        assert resp["fm_src_addr"] == (FM_I2C_ADDR << 1) | 1, "fm_src_addr wrong"
        assert resp["hdr_ver"]  == MCTP_HDR_VER, "hdr_ver wrong"
        assert resp["msg_type"] == 0x7E, "msg_type must be 0x7E (CXL FM API)"
        assert resp["category"] == 1, "category must be 1 (RESPONSE)"
        assert resp["return_code"] == 0
        assert resp["opcode"] == OPCODE_IDENTIFY
        assert resp["background"] == 0, "Identify is foreground — background must be 0"
        assert resp["dest_eid"] == DEV_EID, "dest_eid = device that sent request"
        assert resp["src_eid"]  == FM_EID,  "src_eid  = FM"
        assert resp["cci_tag"]  == 7, "cci_tag must be echoed"
        assert resp["msg_tag"]  == 5, "msg_tag must be echoed"
        assert resp["pec_ok"], f"PEC invalid: got 0x{resp['pec']:02X}"
        assert resp["cci_payload"] == identify_payload
    finally:
        await _stop_server(server, task)


# ─────────────────────────────────────────────────────────────────────────────
# ③ Multiple sequential requests
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_dual_port_multiple_sequential():
    """
    Send 5 Identify requests on one persistent Slave connection.
    All 5 responses must arrive on the persistent Master connection, in order.
    """
    mock = MockMctpCciApiClient(
        return_code=CCI_RETURN_CODE.SUCCESS,
        response_payload=make_identify_payload(),
    )
    server, req_port, resp_port, task = await _start_server(mock)
    try:
        # Master connects first
        m_reader, m_writer = await asyncio.open_connection("127.0.0.1", resp_port)
        # Slave connects
        s_reader, s_writer = await asyncio.open_connection("127.0.0.1", req_port)

        N = 5
        for i in range(N):
            frame = build_slave_request(opcode=OPCODE_IDENTIFY, cci_tag=i, msg_tag=i % 8)
            s_writer.write(frame)
            await s_writer.drain()

            raw  = await asyncio.wait_for(
                _recv_smbus_resp(m_reader), timeout=RESPONSE_TIMEOUT
            )
            resp = parse_response(raw)

            assert resp["return_code"] == 0,   f"[{i}] Expected SUCCESS"
            assert resp["cci_tag"]     == i,    f"[{i}] cci_tag mismatch"
            assert resp["msg_tag"]     == i % 8, f"[{i}] msg_tag mismatch"

        s_writer.close()
        m_writer.close()
        await s_writer.wait_closed()
        await m_writer.wait_closed()

        assert len(mock.calls) == N
    finally:
        await _stop_server(server, task)


# ─────────────────────────────────────────────────────────────────────────────
# ④ No client → UNSUPPORTED on Master
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_dual_port_no_client_returns_unsupported():
    """
    Without a bound MctpCciApiClient, Master must receive UNSUPPORTED (rc=3).
    """
    server, req_port, resp_port, task = await _start_server(mock_client=None)
    try:
        frame = build_slave_request(opcode=OPCODE_IDENTIFY)
        raw   = await _send_and_receive(req_port, resp_port, frame)
        resp  = parse_response(raw)

        assert resp["return_code"] == int(CCI_RETURN_CODE.UNSUPPORTED), \
            f"Expected UNSUPPORTED, got {resp['return_code']}"
        assert resp["cci_payload"] == b""
    finally:
        await _stop_server(server, task)


# ─────────────────────────────────────────────────────────────────────────────
# ⑤ Bad PEC → INVALID_INPUT on Master
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_dual_port_bad_pec_returns_invalid_input():
    """
    With verify_pec=True and a corrupted PEC frame, Master must receive
    INVALID_INPUT (rc=2), and send_raw_cci must NOT be called.
    """
    mock = MockMctpCciApiClient(
        return_code=CCI_RETURN_CODE.SUCCESS,
        response_payload=make_identify_payload(),
    )
    server, req_port, resp_port, task = await _start_server(mock, verify_pec=True)
    try:
        bad_frame = build_slave_request(opcode=OPCODE_IDENTIFY, corrupt_pec=True)
        raw  = await _send_and_receive(req_port, resp_port, bad_frame)
        resp = parse_response(raw)

        assert resp["return_code"] == int(CCI_RETURN_CODE.INVALID_INPUT), \
            f"Expected INVALID_INPUT, got {resp['return_code']}"
        assert len(mock.calls) == 0, "send_raw_cci must not be called for bad PEC"
    finally:
        await _stop_server(server, task)


# ─────────────────────────────────────────────────────────────────────────────
# ⑥ Background command (CONFIGURE_PID_BINDING)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_dual_port_background_command():
    """
    CONFIGURE_PID_BINDING returns BACKGROUND_COMMAND_STARTED (rc=1, bg=1).
    Master must receive the response with those exact fields.
    """
    mock = MockMctpCciApiClient(
        return_code=CCI_RETURN_CODE.BACKGROUND_COMMAND_STARTED,
        response_payload=b"",
        is_background=True,
    )
    server, req_port, resp_port, task = await _start_server(mock)
    try:
        cci_payload = struct.pack("<BBBBH", 0, 0, 0, 0, 0x010)  # BIND, vcs=0, vppb=0, pid=0x010
        frame = build_slave_request(opcode=OPCODE_BIND, cci_payload=cci_payload)
        raw   = await _send_and_receive(req_port, resp_port, frame)
        resp  = parse_response(raw)

        assert resp["return_code"] == int(CCI_RETURN_CODE.BACKGROUND_COMMAND_STARTED), \
            f"Expected BACKGROUND (1), got {resp['return_code']}"
        assert resp["background"] == 1, "background bit must be 1"
        assert resp["opcode"] == OPCODE_BIND
    finally:
        await _stop_server(server, task)


# ─────────────────────────────────────────────────────────────────────────────
# ⑦ Master connects AFTER response is already in the queue (queue buffers it)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_dual_port_master_connects_after_slave():
    """
    The asyncio.Queue buffers the response frame.
    Master can connect AFTER the Slave's response is in the queue
    and still receive it correctly.

    This is the key test for the slow-VDI scenario: on a loaded machine,
    the Master may connect late.  The queue must hold the frame.
    """
    mock = MockMctpCciApiClient(
        return_code=CCI_RETURN_CODE.SUCCESS,
        response_payload=make_identify_payload(),
    )
    server, req_port, resp_port, task = await _start_server(mock)
    try:
        # Step 1: Slave sends — response goes into the queue (no Master yet)
        s_reader, s_writer = await asyncio.open_connection("127.0.0.1", req_port)
        frame = build_slave_request(opcode=OPCODE_IDENTIFY)
        s_writer.write(frame)
        await s_writer.drain()

        # Step 2: Give the server time to process (simulate slow Master connect)
        await asyncio.sleep(0.3)

        # Step 3: Master connects AFTER the response is already queued
        m_reader, m_writer = await asyncio.open_connection("127.0.0.1", resp_port)

        # Step 4: Master reads — queue delivers the buffered frame
        raw  = await asyncio.wait_for(_recv_smbus_resp(m_reader), timeout=RESPONSE_TIMEOUT)
        resp = parse_response(raw)

        assert resp["return_code"] == 0, f"Expected SUCCESS, got rc={resp['return_code']}"
        assert resp["opcode"] == OPCODE_IDENTIFY

        s_writer.close()
        m_writer.close()
        await s_writer.wait_closed()
        await m_writer.wait_closed()
    finally:
        await _stop_server(server, task)


# ─────────────────────────────────────────────────────────────────────────────
# ⑧ Two slave clients sequential — both responses reach master
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_dual_port_two_slaves_sequential():
    """
    Two Slave clients connect one after the other, each sending one Identify.
    The single Master must receive both responses in order.
    """
    mock = MockMctpCciApiClient(
        return_code=CCI_RETURN_CODE.SUCCESS,
        response_payload=make_identify_payload(),
    )
    server, req_port, resp_port, task = await _start_server(mock)
    try:
        # Master connects first
        m_reader, m_writer = await asyncio.open_connection("127.0.0.1", resp_port)

        for i in range(2):
            s_reader, s_writer = await asyncio.open_connection("127.0.0.1", req_port)
            frame = build_slave_request(opcode=OPCODE_IDENTIFY, cci_tag=i)
            s_writer.write(frame)
            await s_writer.drain()
            s_writer.close()
            await s_writer.wait_closed()

            # Small gap so requests are sequential
            await asyncio.sleep(0.05)

        # Master reads 2 responses
        for i in range(2):
            raw  = await asyncio.wait_for(
                _recv_smbus_resp(m_reader), timeout=RESPONSE_TIMEOUT
            )
            resp = parse_response(raw)
            assert resp["return_code"] == 0, f"Slave {i}: Expected SUCCESS"
            assert resp["opcode"] == OPCODE_IDENTIFY, f"Slave {i}: opcode mismatch"

        m_writer.close()
        await m_writer.wait_closed()

        assert len(mock.calls) == 2, "send_raw_cci must have been called exactly twice"
    finally:
        await _stop_server(server, task)
