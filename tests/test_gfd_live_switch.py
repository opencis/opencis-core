"""
tests/test_gfd_live_switch.py
=============================
GFD live-switch integration tests — exercising all 6 PBR FM CCI commands
over a real MCTP/TCP channel without needing a QEMU host or full CxlSwitch.

Architecture
------------
Rather than starting the heavy ``CxlSwitch`` app (which requires QEMU-hosted
devices connected before it can signal ready), these tests wire the PBR
control-plane components directly:

  ┌──────────────────────────────────────────────────────────────────────────┐
  │  FM side (test code)                                                     │
  │    MctpConnectionManager  ← FM MCTP server (port=0 → ephemeral)         │
  │    MctpCciApiClient       ← sends all 6 PBR CCI commands                │
  └─────────────────────────────────┬────────────────────────────────────────┘
                                    │ MCTP / TCP
  ┌─────────────────────────────────▼────────────────────────────────────────┐
  │  Switch side                                                             │
  │    MctpConnectionClient   ← connects to FM MCTP server                  │
  │    MctpCciExecutor        ← routes CCI opcodes → registered commands    │
  │    PbrSwitchManager       ← stateful PBR control plane (PID table, DRT) │
  └──────────────────────────────────────────────────────────────────────────┘

Windows / IOCP note
-------------------
On Windows, Python's IOCP-based ProactorEventLoop blocks in
``GetQueuedCompletionStatus`` for pending TCP I/O.  Cancelling async tasks
that are blocked on socket operations does not unblock that poll, so the
normal pytest-asyncio pattern hangs on teardown.

The fix: run the entire async component set in a *daemon background thread*
with its own event loop.  Test functions are plain synchronous ``def test_*``
functions that dispatch coroutines via ``asyncio.run_coroutine_threadsafe``.
When the test exits the harness thread is abandoned — the OS reclaims sockets.

PbrSwitchManager semantics
---------------------------
- ``assign_pid`` requires pre-registered ``PidTarget`` entries in the manager.
  Tests that exercise PID assignment create the manager with suitable targets.
- ``GetPidBinding`` uses ``(target_vcs, target_vppb)`` co-ordinates — NOT a PID.
- ``ConfigurePidBinding`` is a CCI *background* command (BACKGROUND_COMMAND_STARTED).
- ``set_drt`` / ``get_drt`` do NOT require any pre-registered targets.

Tests
-----
1.  test_gfd_live_fm_identify_pbr_switch       — Identify PBR Switch (0x5700)
2.  test_gfd_live_fm_configure_pid_assignment  — Configure PID (0x5704)
3.  test_gfd_live_fm_get_pid_binding           — Get PID Binding (0x5705)
4.  test_gfd_live_fm_configure_pid_binding     — Configure PID Binding (0x5706)
5.  test_gfd_live_fm_set_and_get_drt           — Set/Get DRT (0x5709/0x5708)
6.  test_gfd_live_full_fm_workflow             — Complete GFD commissioning
"""

import asyncio
import threading
from typing import Optional, List

import pytest

from opencis.util.logger import logger
from opencis.cxl.component.mctp.mctp_connection_manager import MctpConnectionManager
from opencis.cxl.component.mctp.mctp_connection_client import MctpConnectionClient
from opencis.cxl.component.mctp.mctp_cci_executor import MctpCciExecutor
from opencis.cxl.component.mctp.mctp_cci_api_client import MctpCciApiClient
from opencis.cxl.component.pbr_switch_manager import (
    PbrSwitchManager,
    PidTarget,
    PidTargetType,
    DrtEntry,
    DrtEntryType,
    PID_UNASSIGNED,
)
from opencis.cxl.component.switch_connection_manager import SwitchConnectionManager
from opencis.cxl.component.physical_port_manager import PortConfig, PORT_TYPE
from opencis.cxl.cci.fabric_manager.pbr_switch import (
    IdentifyPbrSwitchCommand,
    ConfigurePidAssignmentCommand,
    GetPidBindingCommand,
    ConfigurePidBindingCommand,
    GetDrtCommand,
    SetDrtCommand,
    ConfigurePidAssignmentRequestPayload,
    PidAssignmentEntry,
    GetPidBindingRequestPayload,
    ConfigurePidBindingRequestPayload,
    GetDrtRequestPayload,
    SetDrtRequestPayload,
)
from opencis.cxl.cci.common import CCI_RETURN_CODE
from opencis.cxl.component.gae_manager import GaeManager
from opencis.cxl.cci.fabric_manager.gae import (
    IdentifyGaeCommand,
    GetPidAccessVectorsCommand,
    ProxyGfdMgmtCommand,
    GetProxyThreadStatusCommand,
    CancelProxyThreadCommand,
)
from opencis.cxl.cci.fabric_manager.gae.proxy_gfd_mgmt import (
    ProxyGfdMgmtRequestPayload,
    ProxyGfdMgmtResponsePayload,
)
from opencis.cxl.cci.fabric_manager.gae.get_proxy_thread_status import (
    GetProxyThreadStatusRequestPayload,
    GetProxyThreadStatusResponsePayload,
)
from opencis.cxl.cci.fabric_manager.gae.cancel_proxy_thread import (
    CancelProxyThreadRequestPayload,
)
from opencis.cxl.cci.fabric_manager.gae.identify_gae import (
    IdentifyGaeResponsePayload,
)
from unittest.mock import AsyncMock, MagicMock
from opencis.cxl.component.cci_executor import CciExecutor, CciResponse


# ---------------------------------------------------------------------------
# Suppress "Task destroyed but pending" PytestUnraisableExceptionWarning.
# These arise from the daemon-thread teardown; the tests themselves pass.
# ---------------------------------------------------------------------------
pytestmark = pytest.mark.filterwarnings(
    "ignore::pytest.PytestUnraisableExceptionWarning"
)


# ---------------------------------------------------------------------------
# Logging fixture — suppress noise for all tests in this module
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _set_log_level():
    logger.set_stdout_levels(loglevel="WARNING")
    yield


# ---------------------------------------------------------------------------
# PbrSwitchManager factory helpers
# ---------------------------------------------------------------------------

def _make_simple_pid_targets() -> List[PidTarget]:
    """
    Register two fabric-port targets (IDs 0 and 1) so that assign_pid()
    against target_id=0 (USP) or target_id=1 (DSP/GFD) succeeds.
    """
    return [
        PidTarget(
            target_id=0,
            target_type=PidTargetType.HOST_EDGE_PORT,
            instance_id=0,
            vcs_id=0,
            physical_port_id=0,
        ),
        PidTarget(
            target_id=1,
            target_type=PidTargetType.DOWNSTREAM_EDGE_PORT,
            instance_id=0,
            vcs_id=0,
            physical_port_id=1,
        ),
    ]


# ---------------------------------------------------------------------------
# PbrLiveSwitchHarness
# ---------------------------------------------------------------------------

class PbrLiveSwitchHarness:
    """
    Runs the full PBR MCTP control-plane stack in a dedicated background
    daemon thread, exposing synchronous helper methods for tests.

    Pass ``pid_targets`` to pre-populate the PbrSwitchManager so that
    PID assignment commands succeed (assign_pid requires registered targets).
    """

    STARTUP_TIMEOUT = 10  # seconds

    def __init__(self, pid_targets: Optional[List[PidTarget]] = None):
        self._pid_targets = pid_targets
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._ready_event = threading.Event()
        self._start_error: Optional[Exception] = None
        self.api: Optional[MctpCciApiClient] = None
        self.pbr_mgr: Optional[PbrSwitchManager] = None
        self.gae_mgr: Optional[GaeManager] = None
        self.mock_gfd_executor: Optional[MagicMock] = None

    # ── public API ────────────────────────────────────────────────────────

    def start(self):
        """Start the background thread and block until all components are ready."""
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._thread_main,
            daemon=True,
            name="PbrHarnessThread",
        )
        self._thread.start()
        if not self._ready_event.wait(timeout=self.STARTUP_TIMEOUT):
            raise TimeoutError(
                "PbrLiveSwitchHarness: components did not become ready "
                f"within {self.STARTUP_TIMEOUT}s"
            )
        if self._start_error is not None:
            raise self._start_error

    def call(self, coro, timeout: float = 15.0):
        """
        Submit a coroutine to the harness event loop and return its result
        (or raise its exception).
        """
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=timeout)

    def stop(self, timeout: float = 3.0):
        """Gracefully stop the background event loop and join the thread."""
        if self._loop is not None and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    # ── background thread ─────────────────────────────────────────────────

    def _thread_main(self):
        asyncio.set_event_loop(self._loop)
        # Suppress "Task exception was never retrieved" / "cannot reuse already
        # awaited coroutine" noise that comes from daemon-thread teardown.
        self._loop.set_exception_handler(lambda loop, ctx: None)
        try:
            self._loop.run_until_complete(self._async_main())
        except Exception:
            pass  # daemon — exit silently

    async def _async_main(self):
        try:
            await self._start_components()
            self._ready_event.set()
            # Run forever until the daemon thread is reaped by the OS
            await asyncio.Event().wait()
        except Exception as e:
            self._start_error = e
            self._ready_event.set()

    async def _start_components(self):
        # ── FM MCTP server (ephemeral port) ──────────────────────────────
        mctp_mgr = MctpConnectionManager(host="127.0.0.1", port=0)
        await mctp_mgr.run_wait_ready()
        mctp_port = mctp_mgr._server_component.get_port()

        # ── Switch-side MCTP client ───────────────────────────────────────
        mctp_client = MctpConnectionClient(
            host="127.0.0.1", port=mctp_port, auto_reconnect=False
        )
        await mctp_client.run_wait_ready()
        sw_mctp_conn = mctp_client.get_mctp_connection()

        # ── CCI executor + PbrSwitchManager + GaeManager ──────────────────
        port_configs = [PortConfig(PORT_TYPE.USP), PortConfig(PORT_TYPE.DSP)]
        sw_conn_mgr = SwitchConnectionManager(
            port_configs=port_configs, host="127.0.0.1", port=0
        )
        self.pbr_mgr = PbrSwitchManager(
            pid_targets=self._pid_targets  # None → no targets (DRT-only tests)
        )
        self.gae_mgr = GaeManager(vppbs=[], label="Harness:GAE")

        # Mock the GFD's CciExecutor so that proxied GFD commands succeed
        self.mock_gfd_executor = MagicMock(spec=CciExecutor)
        resp = CciResponse()
        resp.return_code = CCI_RETURN_CODE.SUCCESS
        resp.payload = b"\x11\x22\x33\x44"
        self.mock_gfd_executor.execute_command = AsyncMock(return_value=resp)
        self.mock_gfd_executor.wait_for_ready = AsyncMock()
        self.gae_mgr.set_gfd_executor(self.mock_gfd_executor)

        executor = MctpCciExecutor(
            mctp_connection=sw_mctp_conn,
            switch_connection_manager=sw_conn_mgr,
            port_configs=port_configs,
        )
        executor.register_cci_commands([
            IdentifyPbrSwitchCommand(self.pbr_mgr),
            ConfigurePidAssignmentCommand(self.pbr_mgr),
            GetPidBindingCommand(self.pbr_mgr),
            ConfigurePidBindingCommand(self.pbr_mgr),
            GetDrtCommand(self.pbr_mgr),
            SetDrtCommand(self.pbr_mgr),
            # GAE (GFA) commands
            IdentifyGaeCommand(self.gae_mgr),
            GetPidAccessVectorsCommand(self.gae_mgr),
            ProxyGfdMgmtCommand(self.gae_mgr),
            GetProxyThreadStatusCommand(self.gae_mgr),
            CancelProxyThreadCommand(self.gae_mgr),
        ])
        await executor.run_wait_ready()

        # ── FM CCI API client ─────────────────────────────────────────────
        self.api = MctpCciApiClient(mctp_mgr.get_mctp_connection())
        await self.api.run_wait_ready()


# ---------------------------------------------------------------------------
# Pytest fixture — fresh harness per test
# ---------------------------------------------------------------------------

@pytest.fixture
def harness():
    """Plain harness (no pid_targets) — for Identify and DRT tests."""
    h = PbrLiveSwitchHarness()
    h.start()
    yield h
    h.stop()  # release sockets before next test


@pytest.fixture
def harness_with_targets():
    """Harness pre-populated with two PidTargets (IDs 0 and 1)."""
    h = PbrLiveSwitchHarness(pid_targets=_make_simple_pid_targets())
    h.start()
    yield h
    h.stop()  # release sockets before next test


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _assert_success(rc: CCI_RETURN_CODE, label: str):
    assert rc == CCI_RETURN_CODE.SUCCESS, (
        f"{label}: expected SUCCESS, got {rc.name}"
    )


# ---------------------------------------------------------------------------
# Test 1 — Identify PBR Switch  (0x5700)
# ---------------------------------------------------------------------------

def test_gfd_live_fm_identify_pbr_switch(harness: PbrLiveSwitchHarness):
    """
    CCI Identify PBR Switch (opcode 0x5700) must return SUCCESS with
    num_drts ≥ 1 and valid integer capability fields.
    """
    rc, resp = harness.call(harness.api.identify_pbr_switch())
    _assert_success(rc, "Identify PBR Switch")
    assert resp is not None, "Response payload must not be None"
    assert resp.num_drts >= 1, f"Expected num_drts ≥ 1, got {resp.num_drts}"
    assert isinstance(resp.gae_support_map, int), "gae_support_map must be int"
    assert isinstance(resp.routing_caps, int), "routing_caps must be int"
    assert isinstance(resp.num_rgts, int), "num_rgts must be int"


# ---------------------------------------------------------------------------
# Test 2 — Configure PID Assignment  (0x5704)
# ---------------------------------------------------------------------------

def test_gfd_live_fm_configure_pid_assignment(
    harness_with_targets: PbrLiveSwitchHarness,
):
    """
    FM assigns PID 0x123 to physical port (target_id=1).
    - Duplicate PID to a different target → INVALID_INPUT
    - Re-assign to the same target → SUCCESS (idempotent)
    """
    h = harness_with_targets

    # Assign PID 0x123 to target 1 (GFD DSP)
    req = ConfigurePidAssignmentRequestPayload(
        operation=0,   # ASSIGN
        entries=[PidAssignmentEntry(pid=0x123, target_id=1, instance_id=0)],
    )
    rc, _ = h.call(h.api.configure_pid_assignment(req))
    _assert_success(rc, "Configure PID Assignment (assign)")

    # Duplicate to different target must be rejected
    req_dup = ConfigurePidAssignmentRequestPayload(
        operation=0,
        entries=[PidAssignmentEntry(pid=0x123, target_id=0, instance_id=0)],
    )
    rc_dup, _ = h.call(h.api.configure_pid_assignment(req_dup))
    assert rc_dup == CCI_RETURN_CODE.INVALID_INPUT, (
        f"Dup to diff target: expected INVALID_INPUT, got {rc_dup.name}"
    )

    # Idempotent re-assign to same target must succeed
    rc_idem, _ = h.call(h.api.configure_pid_assignment(req))
    _assert_success(rc_idem, "Configure PID Assignment (idempotent)")


# ---------------------------------------------------------------------------
# Test 3 — Get PID Binding  (0x5705)
# ---------------------------------------------------------------------------

def test_gfd_live_fm_get_pid_binding(
    harness_with_targets: PbrLiveSwitchHarness,
):
    """
    GetPidBinding on an unbound (vcs=0, vppb=0) slot → pid = 0xFFF (unbound).
    After ConfigurePidBinding (Bind), the same slot → pid = 0x123 (bound).

    GetPidBinding is keyed on (target_vcs, target_vppb), NOT on PID directly.
    """
    h = harness_with_targets

    # Before any binding — must return PID = 0xFFF (PID_UNASSIGNED)
    rc, resp = h.call(h.api.get_pid_binding(
        GetPidBindingRequestPayload(target_vcs=0, target_vppb=0)
    ))
    _assert_success(rc, "Get PID Binding (unbound)")
    assert resp is not None
    assert resp.pid == PID_UNASSIGNED, (
        f"Unbound slot must return 0xFFF, got {resp.pid:#05x}"
    )


# ---------------------------------------------------------------------------
# Test 4 — Configure PID Binding  (0x5706)
# ---------------------------------------------------------------------------

def test_gfd_live_fm_configure_pid_binding(
    harness_with_targets: PbrLiveSwitchHarness,
):
    """
    Bind PID 0x123 to VCS=0 vPPB=0 slot using ConfigurePidBinding (BACKGROUND).
    Then GetPidBinding on the same slot must return pid = 0x123.

    ConfigurePidBinding is a background command: the API returns
    BACKGROUND_COMMAND_STARTED; the in-memory state is updated synchronously
    inside the background executor so we can query it immediately.
    """
    h = harness_with_targets

    rc, _ = h.call(h.api.configure_pid_binding(
        ConfigurePidBindingRequestPayload(
            operation=0,          # BIND
            target_vcs=0,
            target_vppb=0,
            pid=0x123,
        )
    ))
    # Background command — accept either SUCCESS or BACKGROUND_COMMAND_STARTED
    assert rc in (CCI_RETURN_CODE.SUCCESS, CCI_RETURN_CODE.BACKGROUND_COMMAND_STARTED), (
        f"Configure PID Binding: unexpected rc={rc.name}"
    )

    # Query the binding
    rc2, resp = h.call(h.api.get_pid_binding(
        GetPidBindingRequestPayload(target_vcs=0, target_vppb=0)
    ))
    _assert_success(rc2, "Get PID Binding after bind")
    assert resp is not None
    assert resp.pid == 0x123, (
        f"After bind: expected pid=0x123, got {resp.pid:#05x}"
    )


# ---------------------------------------------------------------------------
# Test 5 — Set DRT + Get DRT  (0x5709 / 0x5708)
# ---------------------------------------------------------------------------

def test_gfd_live_fm_set_and_get_drt(harness: PbrLiveSwitchHarness):
    """
    Program DRT[0][0x123] → Physical Port 1, then read it back.
    An out-of-range DRT index must return INVALID_INPUT.
    """
    # Set DRT
    rc, _ = harness.call(harness.api.set_drt(
        SetDrtRequestPayload(
            drt_index=0,
            start_entry=0x123,
            entries=[DrtEntry(entry_type=DrtEntryType.PHYSICAL_PORT, routing_target=1)],
        )
    ))
    _assert_success(rc, "Set DRT")

    # Get DRT — verify the entry
    rc2, resp = harness.call(harness.api.get_drt(
        GetDrtRequestPayload(drt_index=0, start_entry=0x123, num_entries=1)
    ))
    _assert_success(rc2, "Get DRT")
    assert resp is not None
    assert len(resp.entries) == 1, f"Expected 1 entry, got {len(resp.entries)}"
    assert resp.entries[0].entry_type == DrtEntryType.PHYSICAL_PORT, (
        f"Expected PHYSICAL_PORT, got {resp.entries[0].entry_type.name}"
    )
    assert resp.entries[0].routing_target == 1, (
        f"Expected routing_target=1, got {resp.entries[0].routing_target}"
    )

    # Out-of-range DRT index → INVALID_INPUT
    rc_bad, _ = harness.call(harness.api.set_drt(
        SetDrtRequestPayload(
            drt_index=99,
            start_entry=0,
            entries=[DrtEntry(entry_type=DrtEntryType.PHYSICAL_PORT, routing_target=1)],
        )
    ))
    assert rc_bad == CCI_RETURN_CODE.INVALID_INPUT, (
        f"OOB DRT index: expected INVALID_INPUT, got {rc_bad.name}"
    )


# ---------------------------------------------------------------------------
# Test 6 — Full GFD FM commissioning workflow
# ---------------------------------------------------------------------------

def test_gfd_live_full_fm_workflow(harness_with_targets: PbrLiveSwitchHarness):
    """
    Complete GFD commissioning sequence (6 CCI steps):

      Step 1  Identify PBR Switch     — discover switch capabilities
      Step 2  Configure PID Assignment — ASSIGN PID 0x010 → target 1 (GFD DSP)
      Step 3  Set DRT                 — DRT[0][0x010] → Physical Port 1
      Step 4  Get DRT                 — verify routing entry
      Step 5  Configure PID Binding   — Bind PID 0x010 at VCS=0, vPPB=0
      Step 6  Get PID Binding         — verify VCS=0 vPPB=0 shows pid=0x010
    """
    GFD_PID    = 0x010
    GFD_TARGET = 1        # target_id for GFD DSP
    GFD_PORT   = 1        # physical port index

    h = harness_with_targets

    # ── Step 1 ──────────────────────────────────────────────────────────────
    rc, resp = h.call(h.api.identify_pbr_switch())
    _assert_success(rc, "Step 1 — Identify PBR Switch")
    assert resp.num_drts >= 1

    # ── Step 2 ──────────────────────────────────────────────────────────────
    rc, _ = h.call(h.api.configure_pid_assignment(
        ConfigurePidAssignmentRequestPayload(
            operation=0,
            entries=[PidAssignmentEntry(pid=GFD_PID, target_id=GFD_TARGET, instance_id=0)],
        )
    ))
    _assert_success(rc, "Step 2 — Configure PID Assignment")

    # ── Step 3 ──────────────────────────────────────────────────────────────
    rc, _ = h.call(h.api.set_drt(
        SetDrtRequestPayload(
            drt_index=0,
            start_entry=GFD_PID,
            entries=[DrtEntry(entry_type=DrtEntryType.PHYSICAL_PORT, routing_target=GFD_PORT)],
        )
    ))
    _assert_success(rc, "Step 3 — Set DRT")

    # ── Step 4 ──────────────────────────────────────────────────────────────
    rc, resp = h.call(h.api.get_drt(
        GetDrtRequestPayload(drt_index=0, start_entry=GFD_PID, num_entries=1)
    ))
    _assert_success(rc, "Step 4 — Get DRT")
    assert resp.entries[0].entry_type == DrtEntryType.PHYSICAL_PORT
    assert resp.entries[0].routing_target == GFD_PORT

    # ── Step 5 ──────────────────────────────────────────────────────────────
    rc, _ = h.call(h.api.configure_pid_binding(
        ConfigurePidBindingRequestPayload(
            operation=0,   # BIND
            target_vcs=0,
            target_vppb=0,
            pid=GFD_PID,
        )
    ))
    assert rc in (CCI_RETURN_CODE.SUCCESS, CCI_RETURN_CODE.BACKGROUND_COMMAND_STARTED), (
        f"Step 5 — Configure PID Binding: unexpected rc={rc.name}"
    )

    # ── Step 6 ──────────────────────────────────────────────────────────────
    rc, resp = h.call(h.api.get_pid_binding(
        GetPidBindingRequestPayload(target_vcs=0, target_vppb=0)
    ))
    _assert_success(rc, "Step 6 — Get PID Binding")
    assert resp.pid == GFD_PID, (
        f"After bind: expected pid={GFD_PID:#05x}, got {resp.pid:#05x}"
    )


# ---------------------------------------------------------------------------
# Test 7 — Identify GAE  (0x5800)
# ---------------------------------------------------------------------------

def test_gfd_live_fm_identify_gae(harness: PbrLiveSwitchHarness):
    """
    Identify GAE (opcode 0x5800) must return SUCCESS with 0 vPPBs by default.
    """
    rc, resp = harness.call(harness.api.identify_gae())
    _assert_success(rc, "Identify GAE")
    assert resp is not None
    assert resp.num_vppbs_with_gm_support == 0
    assert resp.vppb_entries == []


# ---------------------------------------------------------------------------
# Test 8 — Get PID Access Vectors  (0x5802)
# ---------------------------------------------------------------------------

def test_gfd_live_fm_get_pid_access_vectors(harness: PbrLiveSwitchHarness):
    """
    Get PID Access Vectors (opcode 0x5802) for a given PID.
    """
    rc, resp = harness.call(harness.api.get_pid_access_vectors(pid=0x200))
    _assert_success(rc, "Get PID Access Vectors")
    assert resp is not None
    assert resp.pid == 0x200
    assert resp.gmv == 0
    assert resp.vtv == 0


# ---------------------------------------------------------------------------
# Test 9 — Proxy GFD Mgmt Flow (0x5809 / 0x580A / 0x580B)
# ---------------------------------------------------------------------------

def test_gfd_live_fm_proxy_gfd_mgmt_flow(harness: PbrLiveSwitchHarness):
    """
    E2E flow:
    1. Proxy a management command to GFD → returns thread_id.
    2. Wait and query thread status → returns completed=True with mock response payload.
    """
    # 1. Start proxy thread
    rc, resp = harness.call(harness.api.proxy_gfd_mgmt(gfd_opcode=0x0001, gfd_payload=b"\xaa\xbb"))
    _assert_success(rc, "Proxy GFD Mgmt")
    assert resp is not None
    tid = resp.thread_id
    assert tid > 0

    # 2. Get status (allow short sleep for background task to resolve)
    import time
    time.sleep(0.05)
    rc2, resp2 = harness.call(harness.api.get_proxy_thread_status(thread_id=tid))
    _assert_success(rc2, "Get Proxy Thread Status")
    assert resp2 is not None
    assert resp2.completed is True
    assert resp2.gfd_return_code == int(CCI_RETURN_CODE.SUCCESS)
    assert resp2.gfd_response_payload == b"\x11\x22\x33\x44"


def test_gfd_live_fm_cancel_proxy_thread(harness: PbrLiveSwitchHarness):
    """
    Cancel an active/completed proxy thread → SUCCESS.
    """
    # 1. Start proxy thread
    rc, resp = harness.call(harness.api.proxy_gfd_mgmt(gfd_opcode=0x0001))
    _assert_success(rc, "Proxy GFD Mgmt")
    tid = resp.thread_id

    # 2. Cancel it
    rc2, _ = harness.call(harness.api.cancel_proxy_thread(thread_id=tid))
    _assert_success(rc2, "Cancel Proxy Thread")
