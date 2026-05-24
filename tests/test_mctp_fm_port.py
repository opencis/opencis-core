"""
test_mctp_fm_port.py
====================
Pytest async tests for the FM's new external MCTP CCI port (port 8300).

Tests send raw MCTP-over-TCP packets containing CCI commands directly to
FmMctpCciServer and assert the responses — no Socket.IO, no CLI.

What is tested
--------------
1. Identify PBR Switch  (5700h) → SUCCESS, num_drts >= 1
2. Set DRT              (5709h) → SUCCESS; programs DRT[0][0x042] → port 1
3. Get DRT              (5708h) → SUCCESS; verifies entry is PHYSICAL_PORT → 1
4. Configure PID Assign (5704h) → SUCCESS; assigns PID 0x010 → target 0
5. Invalid opcode       (0xDEAD) → UNSUPPORTED return code

Architecture note
-----------------
Each test uses a helper ``MctpCciClient`` — a thin raw-TCP client that
wraps ``asyncio.open_connection``, sends CciPayloadPackets, and reads back
CciMessagePacket responses.  This is intentionally *not* the production
MctpConnectionClient so the test is as close to "raw wire" as possible.
"""

import asyncio
import pytest
import pytest_asyncio

from opencis.util.logger import logger as opencis_logger
from opencis.cxl.component.mctp.fm_mctp_cci_server import FmMctpCciServer
from opencis.cxl.component.pbr_switch_manager import (
    PbrSwitchManager,
    PidTarget,
    PidTargetType,
)
from opencis.cxl.cci.fabric_manager.pbr_switch import (
    IdentifyPbrSwitchCommand,
    IdentifyPbrSwitchResponsePayload,
    ConfigurePidAssignmentCommand,
    ConfigurePidAssignmentRequestPayload,
    GetDrtCommand,
    GetDrtRequestPayload,
    GetDrtResponsePayload,
    SetDrtCommand,
    SetDrtRequestPayload,
)
from opencis.cxl.cci.fabric_manager.pbr_switch.configure_pid_assignment import (
    PidAssignmentEntry,
    PidAssignmentOperation,
)
from opencis.cxl.component.pbr_switch_manager import DrtEntry, DrtEntryType
from opencis.cxl.cci.common import CCI_RETURN_CODE
from opencis.cxl.transport.cci_packets import CciMessagePacket, CciPayloadPacket
from opencis.cxl.transport.packet_constants import CCI_MCTP_MESSAGE_CATEGORY
from opencis.cxl.component.cci_executor import CciRequest


# ---------------------------------------------------------------------------
# Shared PBR manager + server fixtures
# ---------------------------------------------------------------------------

def _make_pbr_manager() -> PbrSwitchManager:
    """FM-side standalone PbrSwitchManager."""
    return PbrSwitchManager(
        num_drts=2,
        num_rgts=1,
        pid_targets=[
            PidTarget(target_id=0, target_type=PidTargetType.FABRIC_PORT,
                      instance_id=0, vcs_id=0, physical_port_id=0),
            PidTarget(target_id=1, target_type=PidTargetType.HOST_EDGE_PORT,
                      instance_id=0, vcs_id=0, physical_port_id=1),
            PidTarget(target_id=2, target_type=PidTargetType.DOWNSTREAM_EDGE_PORT,
                      instance_id=0, vcs_id=0, physical_port_id=2),
        ],
        label="test-FM-PbrManager",
    )


@pytest.fixture(autouse=True)
def enable_logs():
    opencis_logger.set_stdout_levels(loglevel="DEBUG")


@pytest_asyncio.fixture(loop_scope="function")
async def fm_server():
    """
    Spin up FmMctpCciServer on an ephemeral port (port=0).
    Yields the server instance with .get_port() returning the real port.

    NOTE: loop_scope="function" is mandatory — the server's asyncio callbacks
    (TCP accept, queue I/O) must run in the same event loop as the test body.
    With the default session-scoped fixture loop the server never processes
    connections during a function-scoped test.
    """
    pbr_mgr = _make_pbr_manager()
    commands = [
        IdentifyPbrSwitchCommand(pbr_mgr),
        ConfigurePidAssignmentCommand(pbr_mgr),
        SetDrtCommand(pbr_mgr),
        GetDrtCommand(pbr_mgr),
    ]
    server = FmMctpCciServer(host="127.0.0.1", port=0, cci_commands=commands)
    server_task = asyncio.create_task(server.run())
    await server.wait_for_ready()

    yield server

    await server.stop()
    try:
        await asyncio.wait_for(server_task, timeout=5.0)
    except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
        pass




# ---------------------------------------------------------------------------
# Raw MCTP test client
# ---------------------------------------------------------------------------

class MctpCciTestClient:
    """
    Thin raw-TCP client for MCTP CCI testing.

    Sends CciPayloadPacket (wrapping CciMessagePacket) and reads back the
    response using the same framing as MctpPacketReader:
        read SystemHeader.size bytes → determine remaining_length → read rest
    """

    def __init__(self, host: str, port: int):
        self._host = host
        self._port = port
        self._reader: asyncio.StreamReader = None
        self._writer: asyncio.StreamWriter = None
        self._tag = 0

    async def connect(self):
        self._reader, self._writer = await asyncio.open_connection(self._host, self._port)

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

    async def send_command(self, request: CciRequest) -> CciMessagePacket:
        """Send a CCI request and return the decoded CciMessagePacket response."""
        tag = self._next_tag()

        # Build CciMessagePacket (REQUEST)
        msg = CciMessagePacket.create(
            message_category=CCI_MCTP_MESSAGE_CATEGORY.REQUEST,
            opcode=request.opcode,
            data=request.payload if request.payload else b"",
            message_tag=tag,
        )
        # Wrap in CciPayloadPacket
        pkt = CciPayloadPacket.create(msg)

        # Send raw bytes
        self._writer.write(bytes(pkt))
        await self._writer.drain()

        # Read response using same framing as MctpPacketReader
        response_pkt = await self._read_packet()
        return response_pkt.get_cci_message()

    async def _read_packet(self) -> CciPayloadPacket:
        """Read one framed CciPayloadPacket from the stream."""
        from opencis.cxl.transport.packet_structs import SystemHeader
        from opencis.cxl.transport.common import BasePacket

        # 1. Read system header
        hdr_size = SystemHeader.get_size()
        hdr_bytes = await self._reader.readexactly(hdr_size)
        base = BasePacket(bytearray(hdr_bytes))
        remaining = base.system_header.payload_length - len(base)
        if remaining < 0:
            raise ValueError(f"Negative remaining length: {remaining}")

        # 2. Read the rest
        body = await self._reader.readexactly(remaining)
        return CciPayloadPacket(bytearray(hdr_bytes + body))


# ---------------------------------------------------------------------------
# Helper to run one complete request/response round-trip
# ---------------------------------------------------------------------------

async def _round_trip(
    server: FmMctpCciServer, request: CciRequest
) -> CciMessagePacket:
    client = MctpCciTestClient("127.0.0.1", server.get_port())
    await client.connect()
    try:
        return await asyncio.wait_for(client.send_command(request), timeout=5.0)
    finally:
        await client.close()


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_identify_pbr_switch(fm_server):
    """
    Opcode 5700h — Identify PBR Switch
    Expect: SUCCESS, num_drts >= 1, num_rgts >= 0
    """
    req = IdentifyPbrSwitchCommand.create_cci_request()
    response = await _round_trip(fm_server, req)

    assert response.cci_msg_header.return_code == CCI_RETURN_CODE.SUCCESS
    payload = IdentifyPbrSwitchResponsePayload.parse(response.get_payload())
    assert payload.num_drts >= 1, f"Expected num_drts >= 1, got {payload.num_drts}"
    assert payload.num_rgts >= 0


@pytest.mark.asyncio
async def test_set_drt_programs_route(fm_server):
    """
    Opcode 5709h — Set DRT
    Write DRT[0][0x042] = PHYSICAL_PORT → port 1.
    Expect: SUCCESS.
    """
    entries = [DrtEntry(DrtEntryType.PHYSICAL_PORT, routing_target=1)]
    req = SetDrtCommand.create_cci_request(
        SetDrtRequestPayload(drt_index=0, start_entry=0x042, entries=entries)
    )
    response = await _round_trip(fm_server, req)
    assert response.cci_msg_header.return_code == CCI_RETURN_CODE.SUCCESS


@pytest.mark.asyncio
async def test_get_drt_after_set(fm_server):
    """
    Opcode 5708h — Get DRT
    First program DRT[0][0x050] via Set DRT, then read it back via Get DRT.
    Expect: PHYSICAL_PORT → port 2.
    """
    # Set
    entries = [DrtEntry(DrtEntryType.PHYSICAL_PORT, routing_target=2)]
    set_req = SetDrtCommand.create_cci_request(
        SetDrtRequestPayload(drt_index=0, start_entry=0x050, entries=entries)
    )
    set_resp = await _round_trip(fm_server, set_req)
    assert set_resp.cci_msg_header.return_code == CCI_RETURN_CODE.SUCCESS

    # Get
    get_req = GetDrtCommand.create_cci_request(
        GetDrtRequestPayload(drt_index=0, start_entry=0x050, num_entries=1)
    )
    get_resp = await _round_trip(fm_server, get_req)
    assert get_resp.cci_msg_header.return_code == CCI_RETURN_CODE.SUCCESS

    drt_payload = GetDrtResponsePayload.parse(get_resp.get_payload())
    assert len(drt_payload.entries) == 1
    assert drt_payload.entries[0].entry_type == DrtEntryType.PHYSICAL_PORT
    assert drt_payload.entries[0].routing_target == 2


@pytest.mark.asyncio
async def test_configure_pid_assignment(fm_server):
    """
    Opcode 5704h — Configure PID Assignment (ASSIGN)
    Assign PID 0x010 → target_id 0.
    Expect: SUCCESS.
    """
    payload = ConfigurePidAssignmentRequestPayload(
        operation=PidAssignmentOperation.ASSIGN,
        entries=[PidAssignmentEntry(pid=0x010, target_id=0, instance_id=0)],
    )
    req = ConfigurePidAssignmentCommand.create_cci_request(payload)
    response = await _round_trip(fm_server, req)
    assert response.cci_msg_header.return_code == CCI_RETURN_CODE.SUCCESS


@pytest.mark.asyncio
async def test_invalid_opcode_returns_unsupported(fm_server):
    """
    Sending an unregistered opcode (0xDEAD) must return UNSUPPORTED.
    """
    req = CciRequest(opcode=0xDEAD, payload=b"")
    response = await _round_trip(fm_server, req)
    assert response.cci_msg_header.return_code == CCI_RETURN_CODE.UNSUPPORTED


@pytest.mark.asyncio
async def test_multiple_commands_same_connection(fm_server):
    """
    Send multiple commands over the same TCP connection (persistent client).
    Verifies that the tag matching and response routing work across commands.
    """
    client = MctpCciTestClient("127.0.0.1", fm_server.get_port())
    await client.connect()
    try:
        # Command 1: Identify
        r1 = await asyncio.wait_for(
            client.send_command(IdentifyPbrSwitchCommand.create_cci_request()),
            timeout=5.0,
        )
        assert r1.cci_msg_header.return_code == CCI_RETURN_CODE.SUCCESS

        # Command 2: Set DRT
        entries = [DrtEntry(DrtEntryType.PHYSICAL_PORT, routing_target=3)]
        r2 = await asyncio.wait_for(
            client.send_command(
                SetDrtCommand.create_cci_request(
                    SetDrtRequestPayload(drt_index=0, start_entry=0x100, entries=entries)
                )
            ),
            timeout=5.0,
        )
        assert r2.cci_msg_header.return_code == CCI_RETURN_CODE.SUCCESS

        # Command 3: Invalid
        r3 = await asyncio.wait_for(
            client.send_command(CciRequest(opcode=0xFFFF, payload=b"")),
            timeout=5.0,
        )
        assert r3.cci_msg_header.return_code == CCI_RETURN_CODE.UNSUPPORTED
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_set_drt_out_of_range_returns_invalid_input(fm_server):
    """
    Writing past the DRT table boundary must return INVALID_INPUT.
    """
    # start=4095 + 2 entries = 4097 > 4096 → invalid
    entries = [DrtEntry(DrtEntryType.PHYSICAL_PORT, 0)] * 2
    req = SetDrtCommand.create_cci_request(
        SetDrtRequestPayload(drt_index=0, start_entry=4095, entries=entries)
    )
    response = await _round_trip(fm_server, req)
    assert response.cci_msg_header.return_code == CCI_RETURN_CODE.INVALID_INPUT
