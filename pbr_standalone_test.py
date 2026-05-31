#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pbr_standalone_test.py
======================
Self-contained smoke-test for all 6 PBR CCI commands.

NO running switch or MCTP server required.
Tests the CCI command handlers directly in-process, which is exactly
what happens when an FM sends these commands over the wire.

Run from the opencis-core directory:
    py pbr_standalone_test.py

Exit code 0 = all pass, 1 = any failure.
"""

import asyncio
import sys
import os
import io

# Force UTF-8 output on Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------
from opencis.cxl.component.pbr_switch_manager import (
    PbrSwitchManager, PidTarget, PidTargetType,
    DrtEntry, DrtEntryType,
    PidBindingOperation,
)
from opencis.cxl.component.cci_executor import CciRequest, CciResponse
from opencis.cxl.cci.common import CCI_FM_API_COMMAND_OPCODE, CCI_RETURN_CODE
from opencis.cxl.cci.fabric_manager.pbr_switch import (
    IdentifyPbrSwitchCommand,
    IdentifyPbrSwitchResponsePayload,
    ConfigurePidAssignmentCommand,
    ConfigurePidAssignmentRequestPayload,
    PidAssignmentEntry,
    GetPidBindingCommand,
    GetPidBindingRequestPayload,
    GetPidBindingResponsePayload,
    ConfigurePidBindingCommand,
    ConfigurePidBindingRequestPayload,
    GetDrtCommand,
    GetDrtRequestPayload,
    GetDrtResponsePayload,
    SetDrtCommand,
    SetDrtRequestPayload,
)

# ---------------------------------------------------------------------------
# Console helpers
# ---------------------------------------------------------------------------
GREEN  = "\033[92m"
RED    = "\033[91m"
CYAN   = "\033[96m"
YELLOW = "\033[93m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

_passed = 0
_failed = 0


def bar(char="-"):
    print(CYAN + char * 62 + RESET)


def section(num: str, title: str, opcode: str):
    print()
    bar()
    print(f"{BOLD}  {num}. {title}  [{opcode}]{RESET}")
    bar()


def check(label: str, ok: bool, detail: str = ""):
    global _passed, _failed
    if ok:
        _passed += 1
        extra = f"  {YELLOW}({detail}){RESET}" if detail else ""
        print(f"  {GREEN}[PASS]{RESET}  {label}{extra}")
    else:
        _failed += 1
        extra = f"  <- {detail}" if detail else ""
        print(f"  {RED}[FAIL]  {label}{extra}{RESET}")


def make_req(opcode: int, payload: bytes = b"") -> CciRequest:
    r = CciRequest()
    r.opcode  = opcode
    r.payload = payload
    return r


async def noop_progress(pct: int):
    """Stub progress callback for background commands."""
    pass


# ---------------------------------------------------------------------------
# Main test sequence
# ---------------------------------------------------------------------------
async def run_all() -> bool:
    print(f"\n{BOLD}PBR FM CCI Commands  --  In-Process Smoke-Test{RESET}")
    print("No running switch required. Tests command handlers directly.\n")

    # ------------------------------------------------------------------ #
    # Bootstrap: create a PbrSwitchManager pre-loaded with two PID        #
    # targets (ports 2 and 3) so that assign_pid() can validate them.     #
    # ------------------------------------------------------------------ #
    pid_targets = [
        PidTarget(
            target_id=2,
            target_type=PidTargetType.DOWNSTREAM_EDGE_PORT,
            instance_id=0,
            vcs_id=0,
            physical_port_id=2,
        ),
        PidTarget(
            target_id=3,
            target_type=PidTargetType.DOWNSTREAM_EDGE_PORT,
            instance_id=0,
            vcs_id=0,
            physical_port_id=3,
        ),
    ]
    mgr = PbrSwitchManager(pid_targets=pid_targets)

    # ================================================================== #
    # 1. Identify PBR Switch  (0x5700)                                    #
    # ================================================================== #
    section("1", "Identify PBR Switch", "0x5700")
    cmd  = IdentifyPbrSwitchCommand(mgr)
    resp = await cmd._execute(make_req(CCI_FM_API_COMMAND_OPCODE.IDENTIFY_PBR_SWITCH))

    check("Return code SUCCESS",    resp.return_code == CCI_RETURN_CODE.SUCCESS)
    info = IdentifyPbrSwitchResponsePayload.parse(resp.payload)
    check("num_drts >= 1",          info.num_drts >= 1,
          f"num_drts={info.num_drts}")
    check("gae_support_map is int", isinstance(info.gae_support_map, int),
          f"0x{info.gae_support_map:016x}")
    check("routing_caps is int",    isinstance(info.routing_caps, int),
          f"0x{info.routing_caps:02x}")

    # ================================================================== #
    # 2. Configure PID Assignment — Assign  (0x5704)                      #
    # ================================================================== #
    section("2", "Configure PID Assignment  (ASSIGN)", "0x5704")
    cmd = ConfigurePidAssignmentCommand(mgr)

    # Assign two PIDs
    req_payload = ConfigurePidAssignmentRequestPayload(
        operation=0,  # ASSIGN
        entries=[
            PidAssignmentEntry(pid=0x100, target_id=2, instance_id=0),
            PidAssignmentEntry(pid=0x200, target_id=3, instance_id=0),
        ]
    )
    resp = await cmd._execute(
        make_req(CCI_FM_API_COMMAND_OPCODE.CONFIGURE_PID_ASSIGNMENT, req_payload.dump())
    )
    check("Assign PID 0x100 -> port 2 and PID 0x200 -> port 3",
          resp.return_code == CCI_RETURN_CODE.SUCCESS)

    # Assigning an already-taken PID to a DIFFERENT target must be rejected
    dup = ConfigurePidAssignmentRequestPayload(
        operation=0,
        entries=[PidAssignmentEntry(pid=0x100, target_id=3, instance_id=0)]
    )
    resp_dup = await cmd._execute(
        make_req(CCI_FM_API_COMMAND_OPCODE.CONFIGURE_PID_ASSIGNMENT, dup.dump())
    )
    check("Duplicate PID to different target -> INVALID_INPUT",
          resp_dup.return_code == CCI_RETURN_CODE.INVALID_INPUT,
          f"rc={resp_dup.return_code.name}")

    # Re-assigning same PID to same target (idempotent) must succeed
    same = ConfigurePidAssignmentRequestPayload(
        operation=0,
        entries=[PidAssignmentEntry(pid=0x100, target_id=2, instance_id=0)]
    )
    resp_same = await cmd._execute(
        make_req(CCI_FM_API_COMMAND_OPCODE.CONFIGURE_PID_ASSIGNMENT, same.dump())
    )
    check("Re-assign same PID to same target (idempotent) -> SUCCESS",
          resp_same.return_code == CCI_RETURN_CODE.SUCCESS)

    # ================================================================== #
    # 3. Get PID Binding  (0x5705)  -- before any binding                 #
    # ================================================================== #
    section("3", "Get PID Binding  (before bind)", "0x5705")
    cmd   = GetPidBindingCommand(mgr)
    g_req = GetPidBindingRequestPayload(target_vcs=0, target_vppb=0)
    resp  = await cmd._execute(
        make_req(CCI_FM_API_COMMAND_OPCODE.GET_PID_BINDING, g_req.dump())
    )
    check("Return code SUCCESS", resp.return_code == CCI_RETURN_CODE.SUCCESS)
    binfo = GetPidBindingResponsePayload.parse(resp.payload)
    check("pid = 0xFFF (not yet bound)", binfo.pid == 0xFFF,
          f"pid=0x{binfo.pid:03x}")

    # ================================================================== #
    # 4. Configure PID Binding  (0x5706)                                  #
    # ================================================================== #
    section("4", "Configure PID Binding  (BIND)", "0x5706")
    # This is a CciBackgroundCommand — _execute needs a progress callback
    cmd = ConfigurePidBindingCommand(mgr)
    b_req = ConfigurePidBindingRequestPayload(
        operation=PidBindingOperation.BIND,
        target_vcs=0,
        target_vppb=0,
        pid=0x100,              # bind vcs0/vppb0 to PID 0x100
        latency_entry_base_unit=1000,
        latency_entry=5,
        bw_entry_base_unit=500,
        bw_entry=10,
    )
    resp = await cmd._execute(
        make_req(CCI_FM_API_COMMAND_OPCODE.CONFIGURE_PID_BINDING, b_req.dump()),
        noop_progress,
    )
    check("Bind vcs0/vppb0 -> PID 0x100 succeeds",
          resp.return_code == CCI_RETURN_CODE.SUCCESS)

    # Verify: Get PID Binding should now return PID 0x100
    resp2 = await GetPidBindingCommand(mgr)._execute(
        make_req(CCI_FM_API_COMMAND_OPCODE.GET_PID_BINDING, g_req.dump())
    )
    binfo2 = GetPidBindingResponsePayload.parse(resp2.payload)
    check("Binding now shows PID = 0x100", binfo2.pid == 0x100,
          f"pid=0x{binfo2.pid:03x}")
    check("HMAT latency entry = 5",        binfo2.latency_entry == 5,
          f"latency={binfo2.latency_entry}")
    check("HMAT bw entry = 10",            binfo2.bw_entry == 10,
          f"bw={binfo2.bw_entry}")

    # ================================================================== #
    # 5. Set DRT  (0x5709)                                                #
    # ================================================================== #
    section("5", "Set DRT", "0x5709")
    cmd = SetDrtCommand(mgr)

    s_req = SetDrtRequestPayload(
        drt_index=0,
        start_entry=0x100,
        entries=[
            DrtEntry(entry_type=DrtEntryType.PHYSICAL_PORT, routing_target=2),
        ]
    )
    resp = await cmd._execute(
        make_req(CCI_FM_API_COMMAND_OPCODE.SET_DRT, s_req.dump())
    )
    check("DRT[0][0x100] -> Physical Port 2",
          resp.return_code == CCI_RETURN_CODE.SUCCESS)

    s_req2 = SetDrtRequestPayload(
        drt_index=0,
        start_entry=0x200,
        entries=[
            DrtEntry(entry_type=DrtEntryType.PHYSICAL_PORT, routing_target=3),
        ]
    )
    resp2 = await cmd._execute(
        make_req(CCI_FM_API_COMMAND_OPCODE.SET_DRT, s_req2.dump())
    )
    check("DRT[0][0x200] -> Physical Port 3",
          resp2.return_code == CCI_RETURN_CODE.SUCCESS)

    # RESERVED entry type must be rejected per spec
    bad = SetDrtRequestPayload(
        drt_index=0, start_entry=0x001,
        entries=[DrtEntry(entry_type=DrtEntryType.RESERVED, routing_target=0)]
    )
    resp_bad = await cmd._execute(make_req(CCI_FM_API_COMMAND_OPCODE.SET_DRT, bad.dump()))
    check("RESERVED entry type -> INVALID_INPUT",
          resp_bad.return_code == CCI_RETURN_CODE.INVALID_INPUT,
          f"rc={resp_bad.return_code.name}")

    # Out-of-range DRT index
    bad2 = SetDrtRequestPayload(
        drt_index=99, start_entry=0,
        entries=[DrtEntry(entry_type=DrtEntryType.PHYSICAL_PORT, routing_target=2)]
    )
    resp_bad2 = await cmd._execute(make_req(CCI_FM_API_COMMAND_OPCODE.SET_DRT, bad2.dump()))
    check("Invalid DRT index -> INVALID_INPUT",
          resp_bad2.return_code == CCI_RETURN_CODE.INVALID_INPUT,
          f"rc={resp_bad2.return_code.name}")

    # ================================================================== #
    # 6. Get DRT  (0x5708)                                                #
    # ================================================================== #
    section("6", "Get DRT", "0x5708")
    cmd = GetDrtCommand(mgr)

    # Read exactly 1 entry
    g_req = GetDrtRequestPayload(drt_index=0, start_entry=0x100, num_entries=1)
    resp  = await cmd._execute(make_req(CCI_FM_API_COMMAND_OPCODE.GET_DRT, g_req.dump()))
    check("Return code SUCCESS",       resp.return_code == CCI_RETURN_CODE.SUCCESS)
    dinfo = GetDrtResponsePayload.parse(resp.payload)
    check("1 entry returned",          len(dinfo.entries) == 1,
          f"count={len(dinfo.entries)}")
    check("entry type = PHYSICAL_PORT",
          dinfo.entries[0].entry_type == DrtEntryType.PHYSICAL_PORT,
          f"type={dinfo.entries[0].entry_type.name}")
    check("routing_target = 2",
          dinfo.entries[0].routing_target == 2,
          f"target={dinfo.entries[0].routing_target}")

    # Read 2 entries starting at 0x100 (0x100=PHYSICAL_PORT/2, 0x101=INVALID)
    g_req2 = GetDrtRequestPayload(drt_index=0, start_entry=0x100, num_entries=2)
    resp2  = await cmd._execute(make_req(CCI_FM_API_COMMAND_OPCODE.GET_DRT, g_req2.dump()))
    dinfo2 = GetDrtResponsePayload.parse(resp2.payload)
    check("2 entries returned for num_entries=2", len(dinfo2.entries) == 2,
          f"count={len(dinfo2.entries)}")
    check("Entry[0x100] = PHYSICAL_PORT/2",
          dinfo2.entries[0].entry_type   == DrtEntryType.PHYSICAL_PORT and
          dinfo2.entries[0].routing_target == 2)
    check("Entry[0x101] = INVALID (unset)",
          dinfo2.entries[1].entry_type == DrtEntryType.INVALID,
          f"type={dinfo2.entries[1].entry_type.name}")

    # Invalid DRT index
    bad_req = GetDrtRequestPayload(drt_index=99, start_entry=0, num_entries=1)
    resp_bad = await cmd._execute(make_req(CCI_FM_API_COMMAND_OPCODE.GET_DRT, bad_req.dump()))
    check("Invalid DRT index -> INVALID_INPUT",
          resp_bad.return_code == CCI_RETURN_CODE.INVALID_INPUT)

    # ================================================================== #
    # Bonus: Clear PID Assignment  (0x5704 operation=1)                   #
    # ================================================================== #
    section("B", "Configure PID Assignment  (CLEAR)", "0x5704")
    cmd = ConfigurePidAssignmentCommand(mgr)
    c_req = ConfigurePidAssignmentRequestPayload(
        operation=1,  # CLEAR
        entries=[PidAssignmentEntry(pid=0x100, target_id=2, instance_id=0)]
    )
    resp = await cmd._execute(
        make_req(CCI_FM_API_COMMAND_OPCODE.CONFIGURE_PID_ASSIGNMENT, c_req.dump())
    )
    check("Clear PID 0x100 succeeds", resp.return_code == CCI_RETURN_CODE.SUCCESS)

    # After clear, can re-assign the PID to a different target
    re_assign = ConfigurePidAssignmentRequestPayload(
        operation=0,
        entries=[PidAssignmentEntry(pid=0x100, target_id=3, instance_id=0)]
    )
    resp2 = await cmd._execute(
        make_req(CCI_FM_API_COMMAND_OPCODE.CONFIGURE_PID_ASSIGNMENT, re_assign.dump())
    )
    check("Re-assign cleared PID to new target -> SUCCESS",
          resp2.return_code == CCI_RETURN_CODE.SUCCESS)

    # ================================================================== #
    # Summary                                                             #
    # ================================================================== #
    total = _passed + _failed
    print()
    bar("=")
    status_str = (
        f"{GREEN}{_passed} passed{RESET}{BOLD}, {RED}{_failed} FAILED{RESET}{BOLD}"
        if _failed else
        f"{GREEN}ALL {_passed} PASSED{RESET}{BOLD}"
    )
    print(f"{BOLD}  RESULT : {status_str} / {total} total checks{RESET}")
    bar("=")
    print()
    return _failed == 0


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    success = asyncio.run(run_all())
    sys.exit(0 if success else 1)
