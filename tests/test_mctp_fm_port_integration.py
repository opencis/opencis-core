"""
test_mctp_fm_port_integration.py
=================================
Integration tests for FmMctpCciServer (port 8300) — pure MCTP adapter.

These tests verify the adapter end-to-end using a mocked MctpCciApiClient
(specifically, send_raw_cci is mocked with AsyncMock). This lets us test
the complete MCTP framing pipeline without requiring a full switch stack.

Full switch-stack integration (with MctpConnectionManager + MctpCciExecutor)
is covered by the higher-level system tests.

Architecture under test:
  MctpCciTestClient  ──► TCP port 8300 (FmMctpCciServer)
                          │  MctpPacketProcessor depacketizes
                          │  _process_client extracts (opcode, payload)
                          │  _forward_to_cli calls send_raw_cci() [MOCKED]
                          │  response built from (rc, resp_bytes, is_bg)
                          │  MctpPacketProcessor repacketizes
                         ◄── CciPayloadPacket RESPONSE

What is tested
--------------
  1. All 6 PBR opcodes forwarded to send_raw_cci() with correct opcode
  2. Payload bytes from MCTP request passed verbatim to send_raw_cci()
  3. Return code from send_raw_cci() forwarded in MCTP response
  4. Background flag from send_raw_cci() forwarded in MCTP response
  5. Response bytes from send_raw_cci() forwarded in MCTP response body
  6. No mctp_client → UNSUPPORTED for all opcodes
  7. Switch error codes forwarded back
  8. Tag echo: response.message_tag = request.message_tag (always)
  9. Opcode echo: response.command_opcode = request.command_opcode (always)
 10. Persistent connection: multiple commands on one TCP connection
 11. Concurrent connections: two clients get independent correct responses
 12. Configurable response bytes returned to MCTP client
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock
from typing import Dict, List

import pytest
import pytest_asyncio

from opencis.cxl.component.mctp.fm_mctp_cci_server import FmMctpCciServer
from opencis.cxl.cci.common import CCI_RETURN_CODE, CCI_FM_API_COMMAND_OPCODE
from opencis.cxl.cci.fabric_manager.pbr_switch import (
    IdentifyPbrSwitchCommand,
    ConfigurePidAssignmentCommand,
    ConfigurePidAssignmentRequestPayload,
    GetPidBindingCommand,
    GetPidBindingRequestPayload,
    ConfigurePidBindingCommand,
    ConfigurePidBindingRequestPayload,
    GetDrtCommand,
    GetDrtRequestPayload,
    SetDrtCommand,
    SetDrtRequestPayload,
)
from opencis.cxl.cci.fabric_manager.pbr_switch.configure_pid_assignment import (
    PidAssignmentEntry,
    PidAssignmentOperation,
)
from opencis.cxl.cci.fabric_manager.pbr_switch.configure_pid_binding import (
    PidBindingOperation,
)
from opencis.cxl.component.pbr_switch_manager import (
    DrtEntry,
    DrtEntryType,
)
from opencis.cxl.component.cci_executor import CciRequest
from opencis.cxl.transport.cci_packets import CciMessagePacket, CciPayloadPacket
from opencis.cxl.transport.packet_constants import CCI_MCTP_MESSAGE_CATEGORY


# ---------------------------------------------------------------------------
# Raw MCTP test client
# ---------------------------------------------------------------------------

class MctpCciTestClient:
    """Thin raw-TCP client for CCI command round-trips on port 8300."""

    def __init__(self, host: str, port: int):
        self._host = host
        self._port = port
        self._reader = None
        self._writer = None
        self._tag = 0

    async def connect(self):
        self._reader, self._writer = await asyncio.open_connection(
            self._host, self._port
        )

    async def close(self):
        if self._writer:
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except Exception:
                pass

    def _next_tag(self) -> int:
        t = self._tag
        self._tag = (self._tag + 1) & 0xFF
        return t

    async def send(self, opcode: int, payload: bytes = b"", tag: int = None) -> CciMessagePacket:
        if tag is None:
            tag = self._next_tag()
        msg = CciMessagePacket.create(
            message_category=CCI_MCTP_MESSAGE_CATEGORY.REQUEST,
            opcode=opcode,
            data=payload,
            message_tag=tag,
        )
        self._writer.write(bytes(CciPayloadPacket.create(msg)))
        await self._writer.drain()
        return (await self._recv()).get_cci_message()

    async def send_request(self, request: CciRequest) -> CciMessagePacket:
        return await self.send(opcode=request.opcode, payload=request.payload or b"")

    async def _recv(self) -> CciPayloadPacket:
        from opencis.cxl.transport.packet_structs import SystemHeader
        from opencis.cxl.transport.common import BasePacket
        hdr = await self._reader.readexactly(SystemHeader.get_size())
        base = BasePacket(bytearray(hdr))
        body = await self._reader.readexactly(
            max(0, base.system_header.payload_length - len(base))
        )
        return CciPayloadPacket(bytearray(hdr + body))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_client(
    rc: CCI_RETURN_CODE = CCI_RETURN_CODE.SUCCESS,
    response_bytes: bytes = b"",
    is_background: bool = False,
):
    """Return a mock whose send_raw_cci() resolves with the given values."""
    mock = MagicMock()
    mock.send_raw_cci = AsyncMock(return_value=(rc, response_bytes, is_background))
    return mock


async def _round_trip(
    server: FmMctpCciServer,
    opcode: int,
    payload: bytes = b"",
    tag: int = 1,
) -> CciMessagePacket:
    client = MctpCciTestClient("127.0.0.1", server.get_port())
    await client.connect()
    try:
        return await asyncio.wait_for(
            client.send(opcode, payload, tag=tag), timeout=10.0
        )
    finally:
        await client.close()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture(loop_scope="function")
async def fm_no_switch():
    """FmMctpCciServer with no mctp_client — returns UNSUPPORTED."""
    server = FmMctpCciServer(host="127.0.0.1", port=0, mctp_client=None)
    task = asyncio.create_task(server.run())
    await server.wait_for_ready()
    yield server
    await server.stop()
    try:
        await asyncio.wait_for(task, timeout=3.0)
    except Exception:
        task.cancel()


@pytest_asyncio.fixture(loop_scope="function")
async def full_stack():
    """
    FmMctpCciServer with a mocked MctpCciApiClient.

    The mock's send_raw_cci() returns (SUCCESS, b"", False) by default.
    Tests can override mock.send_raw_cci.return_value for specific cases.
    """
    mock_client = _make_mock_client(CCI_RETURN_CODE.SUCCESS, b"", False)
    server = FmMctpCciServer(
        host="127.0.0.1", port=0, mctp_client=mock_client
    )
    task = asyncio.create_task(server.run())
    await server.wait_for_ready()
    yield server, mock_client
    await server.stop()
    try:
        await asyncio.wait_for(task, timeout=3.0)
    except Exception:
        task.cancel()


# ===========================================================================
# Tests — all 6 PBR opcodes forwarded correctly
# ===========================================================================

@pytest.mark.asyncio
async def test_identify_pbr_switch_forwarded(full_stack):
    """IDENTIFY_PBR_SWITCH (0x5700) calls send_raw_cci with correct opcode."""
    server, mock = full_stack
    resp = await _round_trip(server, CCI_FM_API_COMMAND_OPCODE.IDENTIFY_PBR_SWITCH)
    assert resp.cci_msg_header.return_code == CCI_RETURN_CODE.SUCCESS
    call_opcode = mock.send_raw_cci.call_args[0][0]
    assert call_opcode == CCI_FM_API_COMMAND_OPCODE.IDENTIFY_PBR_SWITCH


@pytest.mark.asyncio
async def test_configure_pid_assignment_forwarded(full_stack):
    """CONFIGURE_PID_ASSIGNMENT (0x5704) calls send_raw_cci with payload."""
    server, mock = full_stack
    payload = ConfigurePidAssignmentRequestPayload(
        operation=PidAssignmentOperation.ASSIGN,
        entries=[PidAssignmentEntry(pid=0x010, target_id=0, instance_id=0)],
    )
    req = ConfigurePidAssignmentCommand.create_cci_request(payload)
    resp = await _round_trip(server, req.opcode, req.payload or b"")
    assert resp.cci_msg_header.return_code == CCI_RETURN_CODE.SUCCESS
    assert mock.send_raw_cci.call_args[0][0] == CCI_FM_API_COMMAND_OPCODE.CONFIGURE_PID_ASSIGNMENT


@pytest.mark.asyncio
async def test_get_pid_binding_forwarded(full_stack):
    """GET_PID_BINDING (0x5705) forwarded to switch."""
    server, mock = full_stack
    req = GetPidBindingCommand.create_cci_request(
        GetPidBindingRequestPayload(target_vcs=0, target_vppb=0)
    )
    resp = await _round_trip(server, req.opcode, req.payload or b"")
    assert resp.cci_msg_header.return_code == CCI_RETURN_CODE.SUCCESS
    assert mock.send_raw_cci.call_args[0][0] == CCI_FM_API_COMMAND_OPCODE.GET_PID_BINDING


@pytest.mark.asyncio
async def test_configure_pid_binding_forwarded(full_stack):
    """CONFIGURE_PID_BINDING (0x5706) forwarded to switch."""
    server, mock = full_stack
    mock.send_raw_cci.return_value = (CCI_RETURN_CODE.BACKGROUND_COMMAND_STARTED, b"", True)
    payload = ConfigurePidBindingRequestPayload(
        operation=PidBindingOperation.BIND, target_vcs=0, target_vppb=0, pid=0x010,
    )
    req = ConfigurePidBindingCommand.create_cci_request(payload)
    resp = await _round_trip(server, req.opcode, req.payload or b"")
    assert resp.cci_msg_header.return_code == CCI_RETURN_CODE.BACKGROUND_COMMAND_STARTED
    assert resp.cci_msg_header.background_operation == 1
    assert mock.send_raw_cci.call_args[0][0] == CCI_FM_API_COMMAND_OPCODE.CONFIGURE_PID_BINDING


@pytest.mark.asyncio
async def test_get_drt_forwarded(full_stack):
    """GET_DRT (0x5708) forwarded to switch."""
    server, mock = full_stack
    req = GetDrtCommand.create_cci_request(
        GetDrtRequestPayload(drt_index=0, start_entry=0, num_entries=1)
    )
    resp = await _round_trip(server, req.opcode, req.payload or b"")
    assert resp.cci_msg_header.return_code == CCI_RETURN_CODE.SUCCESS
    assert mock.send_raw_cci.call_args[0][0] == CCI_FM_API_COMMAND_OPCODE.GET_DRT


@pytest.mark.asyncio
async def test_set_drt_forwarded(full_stack):
    """SET_DRT (0x5709) forwarded to switch with payload bytes unchanged."""
    server, mock = full_stack
    entries = [DrtEntry(DrtEntryType.PHYSICAL_PORT, routing_target=1)]
    req = SetDrtCommand.create_cci_request(
        SetDrtRequestPayload(drt_index=0, start_entry=0x042, entries=entries)
    )
    resp = await _round_trip(server, req.opcode, req.payload or b"")
    assert resp.cci_msg_header.return_code == CCI_RETURN_CODE.SUCCESS
    call_opcode, call_payload = mock.send_raw_cci.call_args[0][:2]
    assert call_opcode == CCI_FM_API_COMMAND_OPCODE.SET_DRT
    assert call_payload == (req.payload or b"")


# ===========================================================================
# Tests — adapter behaviour
# ===========================================================================

@pytest.mark.asyncio
async def test_no_switch_returns_unsupported(fm_no_switch):
    """No mctp_client -> UNSUPPORTED for all PBR opcodes."""
    server = fm_no_switch
    for opcode in [
        CCI_FM_API_COMMAND_OPCODE.IDENTIFY_PBR_SWITCH,
        CCI_FM_API_COMMAND_OPCODE.SET_DRT,
        CCI_FM_API_COMMAND_OPCODE.CONFIGURE_PID_ASSIGNMENT,
        CCI_FM_API_COMMAND_OPCODE.GET_DRT,
        CCI_FM_API_COMMAND_OPCODE.GET_PID_BINDING,
        CCI_FM_API_COMMAND_OPCODE.CONFIGURE_PID_BINDING,
    ]:
        resp = await _round_trip(server, opcode)
        assert resp.cci_msg_header.return_code == CCI_RETURN_CODE.UNSUPPORTED


@pytest.mark.asyncio
async def test_switch_error_forwarded(full_stack):
    """Error rc from send_raw_cci() is forwarded verbatim in MCTP response."""
    server, mock = full_stack
    mock.send_raw_cci.return_value = (CCI_RETURN_CODE.INVALID_INPUT, b"", False)
    resp = await _round_trip(server, CCI_FM_API_COMMAND_OPCODE.SET_DRT)
    assert resp.cci_msg_header.return_code == CCI_RETURN_CODE.INVALID_INPUT


@pytest.mark.asyncio
async def test_response_bytes_forwarded(full_stack):
    """Response bytes from send_raw_cci() appear in the MCTP response payload."""
    server, mock = full_stack
    resp_data = b"\xAA\xBB\xCC\xDD"
    mock.send_raw_cci.return_value = (CCI_RETURN_CODE.SUCCESS, resp_data, False)
    resp = await _round_trip(server, CCI_FM_API_COMMAND_OPCODE.IDENTIFY_PBR_SWITCH)
    assert resp.cci_msg_header.return_code == CCI_RETURN_CODE.SUCCESS
    assert resp.get_payload() == resp_data


@pytest.mark.asyncio
async def test_tag_echoed_in_response(full_stack):
    """response.message_tag always equals request.message_tag."""
    server, mock = full_stack
    client = MctpCciTestClient("127.0.0.1", server.get_port())
    await client.connect()
    for tag in [0, 3, 15, 127, 255]:
        resp = await client.send(CCI_FM_API_COMMAND_OPCODE.IDENTIFY_PBR_SWITCH, tag=tag)
        assert resp.cci_msg_header.message_tag == tag
    await client.close()


@pytest.mark.asyncio
async def test_opcode_echoed_in_response(full_stack):
    """response.command_opcode always equals request.command_opcode."""
    server, mock = full_stack
    client = MctpCciTestClient("127.0.0.1", server.get_port())
    await client.connect()
    for opcode in [
        CCI_FM_API_COMMAND_OPCODE.IDENTIFY_PBR_SWITCH,
        CCI_FM_API_COMMAND_OPCODE.SET_DRT,
        CCI_FM_API_COMMAND_OPCODE.GET_DRT,
        CCI_FM_API_COMMAND_OPCODE.CONFIGURE_PID_ASSIGNMENT,
    ]:
        resp = await client.send(opcode)
        assert resp.cci_msg_header.command_opcode == opcode
    await client.close()


@pytest.mark.asyncio
async def test_payload_bytes_forwarded_verbatim(full_stack):
    """Payload bytes in the MCTP request are passed unchanged to send_raw_cci."""
    server, mock = full_stack
    dummy = bytes(range(16))
    await _round_trip(server, CCI_FM_API_COMMAND_OPCODE.SET_DRT, dummy)
    call_payload = mock.send_raw_cci.call_args[0][1]
    assert call_payload == dummy


@pytest.mark.asyncio
async def test_persistent_connection_multiple_commands(full_stack):
    """Persistent TCP connection handles many sequential CCI commands."""
    server, mock = full_stack
    client = MctpCciTestClient("127.0.0.1", server.get_port())
    await client.connect()
    opcodes = [
        CCI_FM_API_COMMAND_OPCODE.IDENTIFY_PBR_SWITCH,
        CCI_FM_API_COMMAND_OPCODE.SET_DRT,
        CCI_FM_API_COMMAND_OPCODE.CONFIGURE_PID_ASSIGNMENT,
        CCI_FM_API_COMMAND_OPCODE.GET_DRT,
        CCI_FM_API_COMMAND_OPCODE.GET_PID_BINDING,
        CCI_FM_API_COMMAND_OPCODE.CONFIGURE_PID_BINDING,
    ]
    for tag, opcode in enumerate(opcodes, start=1):
        resp = await client.send(opcode, tag=tag)
        assert resp.cci_msg_header.return_code == CCI_RETURN_CODE.SUCCESS
        assert resp.cci_msg_header.message_tag == tag
    assert mock.send_raw_cci.await_count == len(opcodes)
    await client.close()


@pytest.mark.asyncio
async def test_concurrent_connections(full_stack):
    """Two simultaneous clients both get correct independent responses."""
    server, mock = full_stack

    async def one_client(tag: int):
        c = MctpCciTestClient("127.0.0.1", server.get_port())
        await c.connect()
        resp = await c.send(CCI_FM_API_COMMAND_OPCODE.IDENTIFY_PBR_SWITCH, tag=tag)
        await c.close()
        return resp

    r1, r2 = await asyncio.gather(one_client(1), one_client(2))
    assert r1.cci_msg_header.return_code == CCI_RETURN_CODE.SUCCESS
    assert r2.cci_msg_header.return_code == CCI_RETURN_CODE.SUCCESS


@pytest.mark.asyncio
async def test_send_raw_cci_called_once_per_command(full_stack):
    """send_raw_cci() is invoked exactly once per incoming MCTP command."""
    server, mock = full_stack
    N = 5
    client = MctpCciTestClient("127.0.0.1", server.get_port())
    await client.connect()
    for i in range(N):
        await client.send(CCI_FM_API_COMMAND_OPCODE.IDENTIFY_PBR_SWITCH, tag=i)
    await client.close()
    assert mock.send_raw_cci.await_count == N
