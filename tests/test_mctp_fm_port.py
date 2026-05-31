"""
Tests for FmMctpCciServer — pure MCTP adapter (port 8300).

Unit tests mock the MctpCciApiClient.send_raw_cci() boundary.
Full TCP integration tests are in test_mctp_fm_port_integration.py.

Coverage:
  1. No mctp_client → every command returns UNSUPPORTED
  2. With mocked mctp_client → send_raw_cci() called with correct opcode+payload
  3. Switch error code forwarded back verbatim
  4. Background flag forwarded back
  5. Tag echo: response.message_tag mirrors request
  6. Opcode echo: response.command_opcode mirrors request
  7. Multiple sequential commands on one connection
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

from opencis.cxl.transport.cci_packets import CciMessagePacket, CciPayloadPacket
from opencis.cxl.transport.packet_constants import CCI_MCTP_MESSAGE_CATEGORY
from opencis.cxl.cci.common import CCI_RETURN_CODE, CCI_FM_API_COMMAND_OPCODE
from opencis.cxl.component.mctp.fm_mctp_cci_server import FmMctpCciServer


# ---------------------------------------------------------------------------
# Raw MCTP test client
# ---------------------------------------------------------------------------

class MctpCciTestClient:
    """Bare TCP client that speaks CciPayloadPacket over a raw socket."""

    def __init__(self, host: str, port: int):
        self._host = host
        self._port = port
        self._reader = None
        self._writer = None

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

    async def send(self, opcode: int, payload: bytes = b"", tag: int = 1) -> CciMessagePacket:
        req = CciMessagePacket.create(
            message_category=CCI_MCTP_MESSAGE_CATEGORY.REQUEST,
            opcode=opcode,
            data=payload,
            message_tag=tag,
        )
        self._writer.write(bytes(CciPayloadPacket.create(req)))
        await self._writer.drain()
        return (await self._recv()).get_cci_message()

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
# Helper: build a mock MctpCciApiClient
# ---------------------------------------------------------------------------

def _make_mock_client(
    rc: CCI_RETURN_CODE = CCI_RETURN_CODE.SUCCESS,
    response_bytes: bytes = b"",
    is_background: bool = False,
):
    """Return a mock whose send_raw_cci() resolves to (rc, response_bytes, is_background)."""
    mock = MagicMock()
    mock.send_raw_cci = AsyncMock(return_value=(rc, response_bytes, is_background))
    return mock


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture(loop_scope="function")
async def fm_no_client():
    """FmMctpCciServer with no mctp_client — every command → UNSUPPORTED."""
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
async def fm_with_mock_switch():
    """FmMctpCciServer with a mocked send_raw_cci() — no real TCP to switch."""
    mock_client = _make_mock_client(CCI_RETURN_CODE.SUCCESS, b"", False)
    server = FmMctpCciServer(host="127.0.0.1", port=0, mctp_client=mock_client)
    task = asyncio.create_task(server.run())
    await server.wait_for_ready()
    yield server, mock_client
    await server.stop()
    try:
        await asyncio.wait_for(task, timeout=3.0)
    except Exception:
        task.cancel()



# ---------------------------------------------------------------------------
# Tests — no client (UNSUPPORTED)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_no_client_returns_unsupported(fm_no_client):
    """With no mctp_client every opcode returns UNSUPPORTED."""
    server = fm_no_client
    client = MctpCciTestClient("127.0.0.1", server.get_port())
    await client.connect()
    resp = await client.send(opcode=CCI_FM_API_COMMAND_OPCODE.IDENTIFY_PBR_SWITCH)
    assert resp.cci_msg_header.return_code == CCI_RETURN_CODE.UNSUPPORTED
    await client.close()


@pytest.mark.asyncio
async def test_no_client_multiple_commands_all_unsupported(fm_no_client):
    """All 6 PBR opcodes return UNSUPPORTED when no switch is connected."""
    server = fm_no_client
    opcodes = [
        CCI_FM_API_COMMAND_OPCODE.IDENTIFY_PBR_SWITCH,
        CCI_FM_API_COMMAND_OPCODE.CONFIGURE_PID_ASSIGNMENT,
        CCI_FM_API_COMMAND_OPCODE.GET_PID_BINDING,
        CCI_FM_API_COMMAND_OPCODE.CONFIGURE_PID_BINDING,
        CCI_FM_API_COMMAND_OPCODE.GET_DRT,
        CCI_FM_API_COMMAND_OPCODE.SET_DRT,
    ]
    client = MctpCciTestClient("127.0.0.1", server.get_port())
    await client.connect()
    for tag, opcode in enumerate(opcodes, start=1):
        resp = await client.send(opcode=opcode, tag=tag)
        assert resp.cci_msg_header.return_code == CCI_RETURN_CODE.UNSUPPORTED
    await client.close()


# ---------------------------------------------------------------------------
# Tests — with mocked switch (adapter unit tests)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_adapter_calls_send_raw_cci(fm_with_mock_switch):
    """send_raw_cci() is called with the correct opcode from the MCTP request."""
    server, mock_client = fm_with_mock_switch
    client = MctpCciTestClient("127.0.0.1", server.get_port())
    await client.connect()
    await client.send(opcode=CCI_FM_API_COMMAND_OPCODE.IDENTIFY_PBR_SWITCH)
    mock_client.send_raw_cci.assert_awaited_once()
    call_opcode = mock_client.send_raw_cci.call_args[0][0]
    assert call_opcode == CCI_FM_API_COMMAND_OPCODE.IDENTIFY_PBR_SWITCH
    await client.close()


@pytest.mark.asyncio
async def test_adapter_forwards_payload_bytes(fm_with_mock_switch):
    """Payload bytes from the MCTP request are passed verbatim to send_raw_cci()."""
    server, mock_client = fm_with_mock_switch
    dummy = b"\xDE\xAD\xBE\xEF"
    client = MctpCciTestClient("127.0.0.1", server.get_port())
    await client.connect()
    await client.send(opcode=CCI_FM_API_COMMAND_OPCODE.SET_DRT, payload=dummy)
    call_payload = mock_client.send_raw_cci.call_args[0][1]
    assert call_payload == dummy
    await client.close()


@pytest.mark.asyncio
async def test_adapter_returns_success(fm_with_mock_switch):
    """SUCCESS from send_raw_cci() is forwarded back in the MCTP response."""
    server, mock_client = fm_with_mock_switch
    client = MctpCciTestClient("127.0.0.1", server.get_port())
    await client.connect()
    resp = await client.send(opcode=CCI_FM_API_COMMAND_OPCODE.IDENTIFY_PBR_SWITCH)
    assert resp.cci_msg_header.return_code == CCI_RETURN_CODE.SUCCESS
    await client.close()


@pytest.mark.asyncio
async def test_adapter_forwards_error_code(fm_no_client):
    """Error codes from send_raw_cci() (or UNSUPPORTED) reach the client."""
    server = fm_no_client   # no client → UNSUPPORTED
    client = MctpCciTestClient("127.0.0.1", server.get_port())
    await client.connect()
    resp = await client.send(opcode=CCI_FM_API_COMMAND_OPCODE.SET_DRT)
    assert resp.cci_msg_header.return_code == CCI_RETURN_CODE.UNSUPPORTED
    await client.close()


@pytest.mark.asyncio
async def test_adapter_error_rc_from_mock(fm_with_mock_switch):
    """INVALID_INPUT returned by send_raw_cci() is forwarded to MCTP client."""
    server, mock_client = fm_with_mock_switch
    mock_client.send_raw_cci.return_value = (CCI_RETURN_CODE.INVALID_INPUT, b"", False)
    client = MctpCciTestClient("127.0.0.1", server.get_port())
    await client.connect()
    resp = await client.send(opcode=CCI_FM_API_COMMAND_OPCODE.SET_DRT)
    assert resp.cci_msg_header.return_code == CCI_RETURN_CODE.INVALID_INPUT
    await client.close()


@pytest.mark.asyncio
async def test_adapter_background_flag_forwarded(fm_with_mock_switch):
    """BACKGROUND_COMMAND_STARTED + background_operation=1 forwarded to client."""
    server, mock_client = fm_with_mock_switch
    mock_client.send_raw_cci.return_value = (
        CCI_RETURN_CODE.BACKGROUND_COMMAND_STARTED, b"", True
    )
    client = MctpCciTestClient("127.0.0.1", server.get_port())
    await client.connect()
    resp = await client.send(opcode=CCI_FM_API_COMMAND_OPCODE.CONFIGURE_PID_BINDING)
    assert resp.cci_msg_header.return_code == CCI_RETURN_CODE.BACKGROUND_COMMAND_STARTED
    assert resp.cci_msg_header.background_operation == 1
    await client.close()


@pytest.mark.asyncio
async def test_adapter_tag_echoed(fm_with_mock_switch):
    """Response message_tag always mirrors the request tag."""
    server, mock_client = fm_with_mock_switch
    client = MctpCciTestClient("127.0.0.1", server.get_port())
    await client.connect()
    for tag in [1, 5, 42, 127]:
        resp = await client.send(
            opcode=CCI_FM_API_COMMAND_OPCODE.IDENTIFY_PBR_SWITCH, tag=tag
        )
        assert resp.cci_msg_header.message_tag == tag
    await client.close()


@pytest.mark.asyncio
async def test_adapter_opcode_echoed(fm_with_mock_switch):
    """Response command_opcode always mirrors the request opcode."""
    server, mock_client = fm_with_mock_switch
    client = MctpCciTestClient("127.0.0.1", server.get_port())
    await client.connect()
    for opcode in [
        CCI_FM_API_COMMAND_OPCODE.IDENTIFY_PBR_SWITCH,
        CCI_FM_API_COMMAND_OPCODE.SET_DRT,
        CCI_FM_API_COMMAND_OPCODE.GET_DRT,
    ]:
        resp = await client.send(opcode=opcode)
        assert resp.cci_msg_header.command_opcode == opcode
    await client.close()


@pytest.mark.asyncio
async def test_adapter_persistent_multiple_commands(fm_with_mock_switch):
    """One TCP connection handles multiple sequential CCI commands correctly."""
    server, mock_client = fm_with_mock_switch
    client = MctpCciTestClient("127.0.0.1", server.get_port())
    await client.connect()
    opcodes = [
        CCI_FM_API_COMMAND_OPCODE.IDENTIFY_PBR_SWITCH,
        CCI_FM_API_COMMAND_OPCODE.SET_DRT,
        CCI_FM_API_COMMAND_OPCODE.CONFIGURE_PID_ASSIGNMENT,
        CCI_FM_API_COMMAND_OPCODE.GET_DRT,
    ]
    for tag, opcode in enumerate(opcodes, start=1):
        resp = await client.send(opcode=opcode, tag=tag)
        assert resp.cci_msg_header.return_code == CCI_RETURN_CODE.SUCCESS
        assert resp.cci_msg_header.message_tag == tag
    assert mock_client.send_raw_cci.await_count == len(opcodes)
    await client.close()
