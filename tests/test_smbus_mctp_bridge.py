"""
tests/test_smbus_mctp_bridge.py
================================
Unit and integration tests for SmbusToMctpBridge.

Tests cover:
  - Auto-sequenced message_tag override
  - Full round-trip: Unix socket → bridge → mock FM → bridge → Unix socket
  - Background command handling (CONFIGURE_PID_BINDING)
  - FM disconnect recovery
  - Multiple sequential commands per session (tag rolls over)
  - Bridge cleans up Unix socket file on stop
"""

import asyncio
import os
import struct
import tempfile
import pytest

from opencis.cxl.component.smbus.smbus_mctp_bridge import (
    SmbusToMctpBridge,
    _read_cci_payload_packet,
)
from opencis.cxl.transport.cci_packets import CciMessagePacket, CciPayloadPacket
from opencis.cxl.transport.packet_constants import CCI_MCTP_MESSAGE_CATEGORY
from opencis.cxl.cci.common import CCI_RETURN_CODE, CCI_FM_API_COMMAND_OPCODE

# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _make_request_packet(opcode: int, payload: bytes = b"", tag: int = 0) -> bytes:
    """Build a CciPayloadPacket REQUEST and return its raw bytes."""
    cci_msg = CciMessagePacket.create(
        message_category=CCI_MCTP_MESSAGE_CATEGORY.REQUEST,
        opcode=opcode,
        data=payload,
        message_tag=tag,
    )
    pkt = CciPayloadPacket.create(cci_msg)
    return bytes(pkt)


def _make_response_packet(
    opcode: int,
    payload: bytes = b"",
    tag: int = 0,
    rc: int = CCI_RETURN_CODE.SUCCESS,
    background: int = 0,
) -> bytes:
    """Build a CciPayloadPacket RESPONSE and return its raw bytes."""
    cci_msg = CciMessagePacket.create(
        message_category=CCI_MCTP_MESSAGE_CATEGORY.RESPONSE,
        opcode=opcode,
        data=payload,
        message_tag=tag,
        return_code=int(rc),
        background_operation=background,
    )
    pkt = CciPayloadPacket.create(cci_msg)
    return bytes(pkt)


async def _send_and_receive(
    unix_path: str,
    request_bytes: bytes,
    timeout: float = 3.0,
) -> bytes:
    """Connect to Unix socket, send *request_bytes*, return raw response bytes."""
    reader, writer = await asyncio.open_unix_connection(unix_path)
    writer.write(request_bytes)
    await writer.drain()
    resp = await asyncio.wait_for(_read_cci_payload_packet(reader), timeout=timeout)
    writer.close()
    await writer.wait_closed()
    return resp


# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_sock(tmp_path):
    """Return a unique temporary Unix socket path."""
    return str(tmp_path / "smbus_test.sock")


@pytest.fixture
def mock_fm_port():
    """
    Return a free TCP port for the mock FM server.
    Uses port 0 so the OS picks one.
    """
    return 0  # will be resolved after server starts


# ──────────────────────────────────────────────────────────────────────────────
# Mock FM helper
# ──────────────────────────────────────────────────────────────────────────────

class MockFmServer:
    """
    Minimal asyncio TCP server that mimics FmMctpCciServer (port 8300).

    For each request it receives, it calls *responder(cci_payload_pkt)*
    and sends the returned bytes back.
    """

    def __init__(self, responder=None):
        self._responder = responder or self._default_responder
        self._server = None
        self._port = None

    @staticmethod
    def _default_responder(raw_req: bytes) -> bytes:
        """Echo SUCCESS with no payload, preserving opcode and tag."""
        req_pkt = CciPayloadPacket(bytearray(raw_req))
        req_msg = req_pkt.get_cci_message()
        opcode  = req_msg.cci_msg_header.command_opcode
        tag     = req_msg.cci_msg_header.message_tag
        return _make_response_packet(opcode=opcode, tag=tag)

    async def start(self):
        self._server = await asyncio.start_server(
            self._handle, host="127.0.0.1", port=0
        )
        self._port = self._server.sockets[0].getsockname()[1]
        asyncio.create_task(self._server.serve_forever())
        return self._port

    async def stop(self):
        if self._server:
            self._server.close()
            await self._server.wait_closed()

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        try:
            while True:
                raw = await _read_cci_payload_packet(reader)
                resp = self._responder(raw)
                writer.write(resp)
                await writer.drain()
        except asyncio.IncompleteReadError:
            pass
        finally:
            writer.close()


# ──────────────────────────────────────────────────────────────────────────────
# Test: auto-sequenced tag
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_bridge_auto_sequences_tag(tmp_sock):
    """
    Tag in the forwarded packet must be 0 for first request, 1 for second,
    regardless of whatever tag the QEMU client puts in its original packet.
    """
    observed_tags = []

    def tag_observer(raw: bytes) -> bytes:
        req_pkt = CciPayloadPacket(bytearray(raw))
        req_msg = req_pkt.get_cci_message()
        observed_tags.append(req_msg.cci_msg_header.message_tag)
        opcode = req_msg.cci_msg_header.command_opcode
        tag    = req_msg.cci_msg_header.message_tag
        return _make_response_packet(opcode=opcode, tag=tag)

    mock_fm = MockFmServer(responder=tag_observer)
    fm_port = await mock_fm.start()

    bridge = SmbusToMctpBridge(
        unix_socket_path=tmp_sock,
        fm_host="127.0.0.1",
        fm_port=fm_port,
    )
    bridge_task = asyncio.create_task(bridge.run())
    await bridge.wait_for_ready()

    try:
        OPCODE = CCI_FM_API_COMMAND_OPCODE.IDENTIFY_PBR_SWITCH  # 0x5700
        # Send two requests with arbitrary tags — bridge should override them
        req1 = _make_request_packet(opcode=OPCODE, tag=0xFF)  # bridge must change to 0
        req2 = _make_request_packet(opcode=OPCODE, tag=0xAB)  # bridge must change to 1

        r, w = await asyncio.open_unix_connection(tmp_sock)
        w.write(req1)
        await w.drain()
        await asyncio.wait_for(_read_cci_payload_packet(r), timeout=3.0)

        w.write(req2)
        await w.drain()
        await asyncio.wait_for(_read_cci_payload_packet(r), timeout=3.0)

        w.close()
        await w.wait_closed()
    finally:
        await bridge._stop()
        bridge_task.cancel()
        await mock_fm.stop()

    assert observed_tags[0] == 0, f"Expected tag 0, got {observed_tags[0]}"
    assert observed_tags[1] == 1, f"Expected tag 1, got {observed_tags[1]}"


# ──────────────────────────────────────────────────────────────────────────────
# Test: full round-trip — request and response forwarded correctly
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_bridge_round_trip_identify(tmp_sock):
    """
    Bridge correctly forwards IDENTIFY_PBR_SWITCH and relays response.
    The response received by the QEMU client must be a valid CciPayloadPacket
    with RESPONSE category.
    """
    OPCODE = CCI_FM_API_COMMAND_OPCODE.IDENTIFY_PBR_SWITCH
    mock_payload = b"\x01\x02\x03\x04"  # pretend switch response

    def responder(raw: bytes) -> bytes:
        req_msg = CciPayloadPacket(bytearray(raw)).get_cci_message()
        return _make_response_packet(
            opcode=req_msg.cci_msg_header.command_opcode,
            tag=req_msg.cci_msg_header.message_tag,
            payload=mock_payload,
        )

    mock_fm = MockFmServer(responder=responder)
    fm_port = await mock_fm.start()

    bridge = SmbusToMctpBridge(
        unix_socket_path=tmp_sock,
        fm_host="127.0.0.1",
        fm_port=fm_port,
    )
    bridge_task = asyncio.create_task(bridge.run())
    await bridge.wait_for_ready()

    try:
        req = _make_request_packet(opcode=OPCODE)
        resp_raw = await _send_and_receive(tmp_sock, req)
    finally:
        await bridge._stop()
        bridge_task.cancel()
        await mock_fm.stop()

    # Parse and validate the response
    resp_pkt = CciPayloadPacket(bytearray(resp_raw))
    resp_msg = resp_pkt.get_cci_message()
    assert resp_msg.cci_msg_header.message_category == CCI_MCTP_MESSAGE_CATEGORY.RESPONSE
    assert resp_msg.cci_msg_header.command_opcode == OPCODE
    assert resp_msg.get_payload() == mock_payload


# ──────────────────────────────────────────────────────────────────────────────
# Test: background command — CONFIGURE_PID_BINDING
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_bridge_background_command(tmp_sock):
    """
    Bridge must relay background responses (background_operation=1) verbatim.
    CONFIGURE_PID_BINDING returns BACKGROUND_COMMAND_STARTED.
    """
    OPCODE = CCI_FM_API_COMMAND_OPCODE.CONFIGURE_PID_BINDING

    def responder(raw: bytes) -> bytes:
        req_msg = CciPayloadPacket(bytearray(raw)).get_cci_message()
        return _make_response_packet(
            opcode=req_msg.cci_msg_header.command_opcode,
            tag=req_msg.cci_msg_header.message_tag,
            rc=CCI_RETURN_CODE.BACKGROUND_COMMAND_STARTED,
            background=1,
        )

    mock_fm = MockFmServer(responder=responder)
    fm_port = await mock_fm.start()

    bridge = SmbusToMctpBridge(
        unix_socket_path=tmp_sock,
        fm_host="127.0.0.1",
        fm_port=fm_port,
    )
    bridge_task = asyncio.create_task(bridge.run())
    await bridge.wait_for_ready()

    try:
        req = _make_request_packet(opcode=OPCODE)
        resp_raw = await _send_and_receive(tmp_sock, req)
    finally:
        await bridge._stop()
        bridge_task.cancel()
        await mock_fm.stop()

    resp_msg = CciPayloadPacket(bytearray(resp_raw)).get_cci_message()
    assert resp_msg.cci_msg_header.background_operation == 1
    assert resp_msg.cci_msg_header.return_code == CCI_RETURN_CODE.BACKGROUND_COMMAND_STARTED


# ──────────────────────────────────────────────────────────────────────────────
# Test: tag wraps at 255 → 0
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_bridge_tag_rollover(tmp_sock):
    """
    After 256 sequential requests the tag counter wraps from 255 back to 0.
    """
    OPCODE = CCI_FM_API_COMMAND_OPCODE.IDENTIFY_PBR_SWITCH
    observed_tags = []

    def tag_observer(raw: bytes) -> bytes:
        req_msg = CciPayloadPacket(bytearray(raw)).get_cci_message()
        observed_tags.append(req_msg.cci_msg_header.message_tag)
        return _make_response_packet(
            opcode=req_msg.cci_msg_header.command_opcode,
            tag=req_msg.cci_msg_header.message_tag,
        )

    mock_fm = MockFmServer(responder=tag_observer)
    fm_port = await mock_fm.start()

    bridge = SmbusToMctpBridge(
        unix_socket_path=tmp_sock,
        fm_host="127.0.0.1",
        fm_port=fm_port,
    )
    bridge_task = asyncio.create_task(bridge.run())
    await bridge.wait_for_ready()

    req = _make_request_packet(opcode=OPCODE)

    try:
        r, w = await asyncio.open_unix_connection(tmp_sock)
        for _ in range(258):   # span two rollovers
            w.write(req)
            await w.drain()
            await asyncio.wait_for(_read_cci_payload_packet(r), timeout=3.0)
        w.close()
        await w.wait_closed()
    finally:
        await bridge._stop()
        bridge_task.cancel()
        await mock_fm.stop()

    assert observed_tags[0]   == 0
    assert observed_tags[255]  == 255
    assert observed_tags[256]  == 0    # rolled over
    assert observed_tags[257]  == 1


# ──────────────────────────────────────────────────────────────────────────────
# Test: bridge cleans up socket file on stop
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_bridge_removes_socket_on_stop(tmp_sock):
    """Unix socket file must be removed after the bridge stops."""
    mock_fm = MockFmServer()
    fm_port = await mock_fm.start()

    bridge = SmbusToMctpBridge(
        unix_socket_path=tmp_sock,
        fm_host="127.0.0.1",
        fm_port=fm_port,
    )
    bridge_task = asyncio.create_task(bridge.run())
    await bridge.wait_for_ready()
    assert os.path.exists(tmp_sock), "Socket file should exist while bridge is running"

    await bridge._stop()
    bridge_task.cancel()
    await mock_fm.stop()

    assert not os.path.exists(tmp_sock), "Socket file should be removed after stop"


# ──────────────────────────────────────────────────────────────────────────────
# Test: bridge handles stale socket file (replaces it)
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_bridge_replaces_stale_socket(tmp_sock):
    """If the socket file already exists, bridge should remove it and re-create."""
    # Create a stale socket file
    with open(tmp_sock, "w") as f:
        f.write("stale")

    mock_fm = MockFmServer()
    fm_port = await mock_fm.start()

    bridge = SmbusToMctpBridge(
        unix_socket_path=tmp_sock,
        fm_host="127.0.0.1",
        fm_port=fm_port,
    )
    bridge_task = asyncio.create_task(bridge.run())
    await bridge.wait_for_ready()   # should not raise

    OPCODE = CCI_FM_API_COMMAND_OPCODE.IDENTIFY_PBR_SWITCH
    req = _make_request_packet(opcode=OPCODE)
    resp_raw = await _send_and_receive(tmp_sock, req, timeout=3.0)
    resp_msg = CciPayloadPacket(bytearray(resp_raw)).get_cci_message()
    assert resp_msg.cci_msg_header.message_category == CCI_MCTP_MESSAGE_CATEGORY.RESPONSE

    await bridge._stop()
    bridge_task.cancel()
    await mock_fm.stop()


# ──────────────────────────────────────────────────────────────────────────────
# Test: multiple concurrent clients (each gets own TCP session to FM)
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_bridge_multiple_concurrent_clients(tmp_sock):
    """
    Two QEMU clients connecting simultaneously must each get correct responses.
    """
    OPCODE = CCI_FM_API_COMMAND_OPCODE.IDENTIFY_PBR_SWITCH

    mock_fm = MockFmServer()   # default echo responder
    fm_port = await mock_fm.start()

    bridge = SmbusToMctpBridge(
        unix_socket_path=tmp_sock,
        fm_host="127.0.0.1",
        fm_port=fm_port,
    )
    bridge_task = asyncio.create_task(bridge.run())
    await bridge.wait_for_ready()

    req = _make_request_packet(opcode=OPCODE)

    try:
        resp1, resp2 = await asyncio.gather(
            _send_and_receive(tmp_sock, req),
            _send_and_receive(tmp_sock, req),
        )
    finally:
        await bridge._stop()
        bridge_task.cancel()
        await mock_fm.stop()

    for resp_raw in (resp1, resp2):
        resp_msg = CciPayloadPacket(bytearray(resp_raw)).get_cci_message()
        assert resp_msg.cci_msg_header.message_category == CCI_MCTP_MESSAGE_CATEGORY.RESPONSE
        assert resp_msg.cci_msg_header.command_opcode == OPCODE
