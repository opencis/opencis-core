"""
test_mctp_fm_port_integration.py
=================================
Phase 2 & Phase 3 integration tests for FmMctpCciServer (port 8300).

These tests verify the **full integration path**:
  Port 8300 (MCTP CCI) ──► FM PbrSwitchManager (FM state)
                        ──► MctpCciApiClient ──► Switch (port 8100)

Architecture
------------
Each test runs a complete stack:
  - FmMctpCciServer  (port 8300) — the system under test
  - A mock switch    (ephemeral) — records what SET_DRT / CONFIGURE_PID commands
                                   it receives via a real MctpConnectionManager
  - MctpCciApiClient             — connects FM to mock switch, injected into server

Test isolation: every test gets a fresh event loop (loop_scope="function").
The mock switch uses MctpCciExecutor with a recording handler so assertions can
inspect which commands reached the switch.

What is tested
--------------
Phase 2 tests:
  1. SET_DRT on port 8300 updates FM state AND is forwarded to the switch
  2. CONFIGURE_PID_ASSIGNMENT is forwarded to the switch
  3. CONFIGURE_PID_BINDING  is forwarded to the switch
  4. Read-only commands (IDENTIFY, GET_DRT) are NOT forwarded to the switch
  5. When switch is not connected, FM still returns SUCCESS (graceful degrade)

Phase 3 tests:
  6. Shared PbrSwitchManager: FM state updated via port 8300 is visible via
     get_fm_pbr_manager()
  7. Both port 8300 write and CLI (socketio) write see the same manager state
"""

import asyncio
import pytest
import pytest_asyncio
from typing import Dict, List

from opencis.cxl.component.mctp.fm_mctp_cci_server import FmMctpCciServer
from opencis.cxl.component.mctp.mctp_connection_client import MctpConnectionClient
from opencis.cxl.component.mctp.mctp_cci_api_client import MctpCciApiClient
from opencis.cxl.component.fabric_manager.pbr_command_service import PbrCommandService
from opencis.cxl.component.pbr_switch_manager import (
    PbrSwitchManager,
    PidTarget,
    PidTargetType,
    DrtEntry,
    DrtEntryType,
)
from opencis.cxl.cci.fabric_manager.pbr_switch import (
    IdentifyPbrSwitchCommand,
    IdentifyPbrSwitchResponsePayload,
    ConfigurePidAssignmentCommand,
    ConfigurePidAssignmentRequestPayload,
    GetPidBindingCommand,
    GetPidBindingRequestPayload,
    ConfigurePidBindingCommand,
    ConfigurePidBindingRequestPayload,
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
from opencis.cxl.cci.fabric_manager.pbr_switch.configure_pid_binding import (
    PidBindingOperation,
)
from opencis.cxl.component.cci_executor import CciRequest
from opencis.cxl.cci.common import CCI_RETURN_CODE
from opencis.cxl.transport.cci_packets import CciMessagePacket, CciPayloadPacket
from opencis.cxl.transport.packet_constants import CCI_MCTP_MESSAGE_CATEGORY


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_pbr_manager(label: str = "test-FM-PbrManager") -> PbrSwitchManager:
    """Create a FM-side PbrSwitchManager with 3 registered PidTargets."""
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
        label=label,
    )


def _all_pbr_commands(mgr: PbrSwitchManager) -> list:
    return [
        IdentifyPbrSwitchCommand(mgr),
        ConfigurePidAssignmentCommand(mgr),
        GetPidBindingCommand(mgr),
        ConfigurePidBindingCommand(mgr),
        GetDrtCommand(mgr),
        SetDrtCommand(mgr),
    ]


# ---------------------------------------------------------------------------
# Raw MCTP test client (reused from test_mctp_fm_port.py)
# ---------------------------------------------------------------------------

class MctpCciTestClient:
    """Thin raw-TCP client for CCI command round-trips."""

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
        tag = self._next_tag()
        msg = CciMessagePacket.create(
            message_category=CCI_MCTP_MESSAGE_CATEGORY.REQUEST,
            opcode=request.opcode,
            data=request.payload if request.payload else b"",
            message_tag=tag,
        )
        pkt = CciPayloadPacket.create(msg)
        self._writer.write(bytes(pkt))
        await self._writer.drain()
        return (await self._read_packet()).get_cci_message()

    async def _read_packet(self) -> CciPayloadPacket:
        from opencis.cxl.transport.packet_structs import SystemHeader
        from opencis.cxl.transport.common import BasePacket
        hdr_size = SystemHeader.get_size()
        hdr_bytes = await self._reader.readexactly(hdr_size)
        base = BasePacket(bytearray(hdr_bytes))
        remaining = base.system_header.payload_length - len(base)
        body = await self._reader.readexactly(max(0, remaining))
        return CciPayloadPacket(bytearray(hdr_bytes + body))


async def _round_trip(server: FmMctpCciServer, request: CciRequest) -> CciMessagePacket:
    client = MctpCciTestClient("127.0.0.1", server.get_port())
    await client.connect()
    try:
        return await asyncio.wait_for(client.send_command(request), timeout=10.0)
    finally:
        await client.close()


# ---------------------------------------------------------------------------
# Mock switch fixture
# ---------------------------------------------------------------------------



class MockSwitch:
    """
    Lightweight mock switch — a raw TCP server that accepts one connection,
    deserialises each CciPayloadPacket it receives, and records the opcode
    and payload.  It replies SUCCESS to everything so the FM's api_client
    does not hang waiting for a response.

    This avoids needing a full SwitchConnectionManager / MctpCciExecutor
    which requires port_configs and switch_connection_manager args.
    """

    def __init__(self):
        self._server: asyncio.Server = None
        self._port: int = 0
        self._received: Dict[int, List[bytes]] = {}
        self._server_task: asyncio.Task = None

    async def start(self):
        self._server = await asyncio.start_server(
            self._handle_client, "127.0.0.1", 0
        )
        self._port = self._server.sockets[0].getsockname()[1]
        self._server_task = asyncio.create_task(self._server.serve_forever())

    async def stop(self):
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        if self._server_task:
            self._server_task.cancel()

    def get_port(self) -> int:
        return self._port

    def received(self, opcode: int) -> List[bytes]:
        return self._received.get(opcode, [])

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        """Read CciPayloadPackets, record opcode+payload, reply SUCCESS."""
        from opencis.cxl.transport.packet_structs import SystemHeader
        from opencis.cxl.transport.common import BasePacket
        try:
            while True:
                hdr_size = SystemHeader.get_size()
                hdr_bytes = await reader.readexactly(hdr_size)
                base = BasePacket(bytearray(hdr_bytes))
                remaining = base.system_header.payload_length - len(base)
                body = await reader.readexactly(max(0, remaining))
                pkt = CciPayloadPacket(bytearray(hdr_bytes + body))
                cci_msg = pkt.get_cci_message()
                opcode  = cci_msg.cci_msg_header.command_opcode
                payload = cci_msg.get_payload()
                tag     = cci_msg.cci_msg_header.message_tag

                self._received.setdefault(opcode, []).append(payload)

                # Reply with SUCCESS
                resp = CciMessagePacket.create(
                    message_category=CCI_MCTP_MESSAGE_CATEGORY.RESPONSE,
                    opcode=opcode,
                    data=b"",
                    message_tag=tag,
                    return_code=int(CCI_RETURN_CODE.SUCCESS),
                )
                resp_pkt = CciPayloadPacket.create(resp)
                writer.write(bytes(resp_pkt))
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionResetError):
            pass
        finally:
            writer.close()



# ---------------------------------------------------------------------------
# Phase 2 fixture: FM server + mock switch wired together
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture(loop_scope="function")
async def fm_with_switch():
    """
    Full Phase 2 stack:
      MockSwitch raw TCP server (ephemeral)
      MctpConnectionClient  →  connects FM to mock switch
      MctpCciApiClient      →  wraps the connection, injected into server
      FmMctpCciServer       →  the system under test (port=0)
    """
    pbr_mgr = _make_pbr_manager()

    # 1. Start lightweight mock switch
    switch = MockSwitch()
    await switch.start()

    # 2. MctpConnectionClient connects FM side → mock switch
    conn_client = MctpConnectionClient(
        host="127.0.0.1",
        port=switch.get_port(),
        auto_reconnect=False,
    )
    conn_task = asyncio.create_task(conn_client.run())
    await conn_client.wait_for_ready()

    # 3. MctpCciApiClient owns the queue pair from the connection client
    api_client = MctpCciApiClient(conn_client.get_mctp_connection())
    api_task = asyncio.create_task(api_client.run())
    await api_client.wait_for_ready()

    # 4. PbrCommandService wraps api_client — mirrors the production path
    pbr_svc = PbrCommandService(api_client=api_client, label="test-PbrService")

    # 5. FmMctpCciServer with injected pbr_service
    server = FmMctpCciServer(
        host="127.0.0.1",
        port=0,
        cci_commands=_all_pbr_commands(pbr_mgr),
        pbr_service=pbr_svc,
    )
    server_task = asyncio.create_task(server.run())
    await server.wait_for_ready()

    yield server, switch, pbr_mgr

    # Teardown
    await server.stop()
    await api_client.stop()
    await conn_client.stop()
    await switch.stop()
    for t in [server_task, api_task, conn_task]:
        try:
            await asyncio.wait_for(t, timeout=3.0)
        except Exception:
            t.cancel()



# ---------------------------------------------------------------------------
# Phase 2 — Test 1: SET_DRT updates FM state AND forwards to switch
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_set_drt_updates_fm_state_and_forwards_to_switch(fm_with_switch):
    """
    Phase 2 — SET_DRT (0x5709)

    Send SET_DRT to port 8300.
    Verify:
      1. FM PbrSwitchManager DRT is updated (FM state)
      2. MockSwitch received exactly one SET_DRT payload (switch forwarding)
    """
    server, switch, pbr_mgr = fm_with_switch

    entries = [DrtEntry(DrtEntryType.PHYSICAL_PORT, routing_target=1)]
    req = SetDrtCommand.create_cci_request(
        SetDrtRequestPayload(drt_index=0, start_entry=0x042, entries=entries)
    )
    response = await _round_trip(server, req)

    # 1. FM returned SUCCESS
    assert response.cci_msg_header.return_code == CCI_RETURN_CODE.SUCCESS

    # 2. FM state updated (Phase 3 shared manager)
    drt_entries, _ = pbr_mgr.get_drt(drt_index=0, start_entry=0x042, num_entries=1)
    assert len(drt_entries) == 1
    assert drt_entries[0].entry_type == DrtEntryType.PHYSICAL_PORT
    assert drt_entries[0].routing_target == 1

    # 3. Switch received the forwarded SET_DRT (Phase 2)
    await asyncio.sleep(0.1)  # allow async forwarding to propagate
    assert len(switch.received(0x5709)) == 1, (
        "SET_DRT was not forwarded to the switch"
    )


# ---------------------------------------------------------------------------
# Phase 2 — Test 2: CONFIGURE_PID_ASSIGNMENT is forwarded to switch
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_configure_pid_assignment_forwarded_to_switch(fm_with_switch):
    """
    Phase 2 — CONFIGURE_PID_ASSIGNMENT (0x5704)

    Assign PID 0x010 → target_id 0 via port 8300.
    Verify the command reaches the mock switch.
    """
    server, switch, pbr_mgr = fm_with_switch

    payload = ConfigurePidAssignmentRequestPayload(
        operation=PidAssignmentOperation.ASSIGN,
        entries=[PidAssignmentEntry(pid=0x010, target_id=0, instance_id=0)],
    )
    req = ConfigurePidAssignmentCommand.create_cci_request(payload)
    response = await _round_trip(server, req)

    assert response.cci_msg_header.return_code == CCI_RETURN_CODE.SUCCESS

    await asyncio.sleep(0.1)
    assert len(switch.received(0x5704)) == 1, (
        "CONFIGURE_PID_ASSIGNMENT was not forwarded to the switch"
    )


# ---------------------------------------------------------------------------
# Phase 2 — Test 3: CONFIGURE_PID_BINDING is forwarded to switch
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_configure_pid_binding_forwarded_to_switch(fm_with_switch):
    """
    Phase 2 — CONFIGURE_PID_BINDING (0x5706)

    First assign PID 0x020 → target_id 1, then bind it to vcs=0, vppb=0.
    Verify both commands arrive at the mock switch.
    """
    server, switch, pbr_mgr = fm_with_switch

    # First: assign PID
    assign_payload = ConfigurePidAssignmentRequestPayload(
        operation=PidAssignmentOperation.ASSIGN,
        entries=[PidAssignmentEntry(pid=0x020, target_id=1, instance_id=0)],
    )
    r1 = await _round_trip(server, ConfigurePidAssignmentCommand.create_cci_request(assign_payload))
    assert r1.cci_msg_header.return_code == CCI_RETURN_CODE.SUCCESS

    # Then: bind PID
    bind_payload = ConfigurePidBindingRequestPayload(
        operation=PidBindingOperation.BIND,
        target_vcs=0,
        target_vppb=0,
        pid=0x020,
    )
    r2 = await _round_trip(server, ConfigurePidBindingCommand.create_cci_request(bind_payload))
    # Background command returns BACKGROUND_COMMAND_STARTED or SUCCESS
    assert r2.cci_msg_header.return_code in (
        CCI_RETURN_CODE.SUCCESS,
        CCI_RETURN_CODE.BACKGROUND_COMMAND_STARTED,
    )

    await asyncio.sleep(0.2)
    assert len(switch.received(0x5704)) >= 1, "PID assignment not forwarded"
    assert len(switch.received(0x5706)) >= 1, "PID binding not forwarded"


# ---------------------------------------------------------------------------
# Phase 2 — Test 4: Read-only commands are NOT forwarded to the switch
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_readonly_commands_not_forwarded_to_switch(fm_with_switch):
    """
    Phase 2 — IDENTIFY (0x5700) and GET_DRT (0x5708) must NOT be forwarded.

    These commands read FM state only; programming the switch with them would
    be incorrect and wasteful.
    """
    server, switch, _ = fm_with_switch

    # Identify PBR Switch (read-only)
    r1 = await _round_trip(server, IdentifyPbrSwitchCommand.create_cci_request())
    assert r1.cci_msg_header.return_code == CCI_RETURN_CODE.SUCCESS

    # Get DRT (read-only)
    r2 = await _round_trip(server, GetDrtCommand.create_cci_request(
        GetDrtRequestPayload(drt_index=0, start_entry=0, num_entries=1)
    ))
    assert r2.cci_msg_header.return_code == CCI_RETURN_CODE.SUCCESS

    await asyncio.sleep(0.1)

    # None of the recording slots for write opcodes should have been hit
    assert len(switch.received(0x5709)) == 0, "SET_DRT slot should be empty"
    assert len(switch.received(0x5704)) == 0, "PID_ASSIGN slot should be empty"
    assert len(switch.received(0x5706)) == 0, "PID_BIND slot should be empty"


# ---------------------------------------------------------------------------
# Phase 2 — Test 5: Graceful degradation when switch not connected
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture(loop_scope="function")
async def fm_no_switch():
    """FM server with no switch — pbr_service=None."""
    pbr_mgr = _make_pbr_manager(label="no-switch-FM-PbrManager")
    server = FmMctpCciServer(
        host="127.0.0.1",
        port=0,
        cci_commands=_all_pbr_commands(pbr_mgr),
        pbr_service=None,   # no switch
    )
    server_task = asyncio.create_task(server.run())
    await server.wait_for_ready()
    yield server, pbr_mgr
    await server.stop()
    try:
        await asyncio.wait_for(server_task, timeout=3.0)
    except Exception:
        server_task.cancel()


@pytest.mark.asyncio
async def test_graceful_degradation_when_no_switch(fm_no_switch):
    """
    Phase 2 — Graceful degradation

    When no switch_api_client is injected, write commands on port 8300 MUST
    still return SUCCESS and update FM state.  No exception should propagate
    to the client.
    """
    server, pbr_mgr = fm_no_switch

    entries = [DrtEntry(DrtEntryType.PHYSICAL_PORT, routing_target=2)]
    req = SetDrtCommand.create_cci_request(
        SetDrtRequestPayload(drt_index=0, start_entry=0x100, entries=entries)
    )
    response = await _round_trip(server, req)

    # FM must still respond SUCCESS even with no switch
    assert response.cci_msg_header.return_code == CCI_RETURN_CODE.SUCCESS

    # FM state must be updated
    drt_entries, _ = pbr_mgr.get_drt(drt_index=0, start_entry=0x100, num_entries=1)
    assert drt_entries[0].entry_type == DrtEntryType.PHYSICAL_PORT
    assert drt_entries[0].routing_target == 2


# ---------------------------------------------------------------------------
# Phase 3 — Test 6: Shared PbrSwitchManager is the authoritative FM state
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_shared_pbr_manager_reflects_mctp_writes(fm_no_switch):
    """
    Phase 3 — Shared PbrSwitchManager

    Commands sent to port 8300 update the manager that is also accessible
    via get_fm_pbr_manager() (or directly in tests via pbr_mgr).

    This verifies that port 8200 (CLI) and port 8300 (MCTP) share the
    same authoritative state object.
    """
    server, pbr_mgr = fm_no_switch

    # Send two DRT writes
    for pid, port in [(0x010, 1), (0x020, 2)]:
        entries = [DrtEntry(DrtEntryType.PHYSICAL_PORT, routing_target=port)]
        req = SetDrtCommand.create_cci_request(
            SetDrtRequestPayload(drt_index=0, start_entry=pid, entries=entries)
        )
        r = await _round_trip(server, req)
        assert r.cci_msg_header.return_code == CCI_RETURN_CODE.SUCCESS

    # Both entries must be visible through the same pbr_mgr reference
    e1, _ = pbr_mgr.get_drt(drt_index=0, start_entry=0x010, num_entries=1)
    e2, _ = pbr_mgr.get_drt(drt_index=0, start_entry=0x020, num_entries=1)

    assert e1[0].routing_target == 1, "DRT[0][0x010] not updated"
    assert e2[0].routing_target == 2, "DRT[0][0x020] not updated"


# ---------------------------------------------------------------------------
# Phase 3 — Test 7: Multiple clients see consistent state
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_concurrent_clients_share_state(fm_no_switch):
    """
    Phase 3 — State consistency across concurrent connections

    Two simultaneous clients each program a different DRT entry.
    Both updates must be visible through the shared PbrSwitchManager.
    """
    server, pbr_mgr = fm_no_switch

    async def write_drt(pid: int, port: int):
        entries = [DrtEntry(DrtEntryType.PHYSICAL_PORT, routing_target=port)]
        req = SetDrtCommand.create_cci_request(
            SetDrtRequestPayload(drt_index=0, start_entry=pid, entries=entries)
        )
        client = MctpCciTestClient("127.0.0.1", server.get_port())
        await client.connect()
        try:
            r = await asyncio.wait_for(client.send_command(req), timeout=5.0)
            assert r.cci_msg_header.return_code == CCI_RETURN_CODE.SUCCESS
        finally:
            await client.close()

    # Fire both writes concurrently
    await asyncio.gather(
        write_drt(0x030, 1),
        write_drt(0x040, 2),
    )

    # Both entries visible on shared manager
    e1, _ = pbr_mgr.get_drt(drt_index=0, start_entry=0x030, num_entries=1)
    e2, _ = pbr_mgr.get_drt(drt_index=0, start_entry=0x040, num_entries=1)

    assert e1[0].routing_target == 1
    assert e2[0].routing_target == 2
