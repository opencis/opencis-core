#!/usr/bin/env python3
"""
pbr_cli_test.py — Standalone smoke-test for all 6 PBR FM CCI commands.

Run against a running opencis-core CXL switch with enable_pbr=True and
the MCTP server listening (default: localhost:8100).

Usage:
    py pbr_cli_test.py [--mctp-host 127.0.0.1] [--mctp-port 8100]

The script:
  1. Connects to the switch MCTP endpoint
  2. Runs all 6 PBR commands in FM-workflow order
  3. Prints pass/fail for each command

This does NOT require a QEMU host or Socket.IO server — it talks directly
over the MCTP CCI TCP connection, the same channel the FM uses internally.
"""

import asyncio
import argparse
import sys
from typing import Optional

# ---------------------------------------------------------------------------
# Patch PATH for the opencis package
# ---------------------------------------------------------------------------
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from opencis.cxl.component.mctp.mctp_connection import MctpConnection
from opencis.cxl.component.mctp.mctp_connection_client import MctpConnectionClient
from opencis.cxl.component.mctp.mctp_cci_api_client import MctpCciApiClient
from opencis.cxl.cci.fabric_manager.pbr_switch import (
    ConfigurePidAssignmentRequestPayload,
    PidAssignmentEntry,
    GetPidBindingRequestPayload,
    ConfigurePidBindingRequestPayload,
    GetDrtRequestPayload,
    SetDrtRequestPayload,
)
from opencis.cxl.component.pbr_switch_manager import DrtEntry, DrtEntryType
from opencis.cxl.cci.common import CCI_RETURN_CODE

# ANSI colours
GREEN = "\033[92m"
RED   = "\033[91m"
CYAN  = "\033[96m"
RESET = "\033[0m"
BOLD  = "\033[1m"


def ok(msg):  print(f"  {GREEN}✓ PASS{RESET}  {msg}")
def fail(msg): print(f"  {RED}✗ FAIL{RESET}  {msg}")
def header(msg): print(f"\n{BOLD}{CYAN}{'─'*60}{RESET}\n{BOLD}{msg}{RESET}")


async def run_tests(host: str, port: int):
    print(f"\n{BOLD}PBR FM CCI Command Smoke-Test{RESET}")
    print(f"Connecting to MCTP endpoint at {host}:{port} …")

    mctp_client_conn = MctpConnectionClient(host, port)
    api = MctpCciApiClient(mctp_client_conn.get_mctp_connection())

    # Start both components
    conn_task = asyncio.create_task(mctp_client_conn.run())
    api_task  = asyncio.create_task(api.run())
    await mctp_client_conn.wait_for_ready()
    await api.wait_for_ready()
    print(f"{GREEN}Connected.{RESET}\n")

    passed = 0
    failed = 0

    # ------------------------------------------------------------------
    # 1. Identify PBR Switch  (opcode 0x5700)
    # ------------------------------------------------------------------
    header("1. Identify PBR Switch  [5700h]")
    rc, resp = await api.identify_pbr_switch()
    if rc == CCI_RETURN_CODE.SUCCESS and resp:
        ok(f"GAE Support Map : {resp.gae_support_map:#018x}")
        ok(f"Num DRTs        : {resp.num_drts}")
        ok(f"Num RGTs        : {resp.num_rgts}")
        ok(f"Routing Caps    : {resp.routing_caps:#04x}")
        passed += 1
    else:
        fail(f"identify_pbr_switch returned {rc.name}")
        failed += 1

    # ------------------------------------------------------------------
    # 2. Configure PID Assignment — Assign  (opcode 0x5704)
    # ------------------------------------------------------------------
    header("2. Configure PID Assignment — ASSIGN  [5704h]")
    req = ConfigurePidAssignmentRequestPayload(
        operation=0,   # ASSIGN
        entries=[
            PidAssignmentEntry(pid=0x123, target_id=2, instance_id=0),
        ]
    )
    rc, resp = await api.configure_pid_assignment(req)
    if rc == CCI_RETURN_CODE.SUCCESS:
        ok(f"PID 0x123 → target_id=2 assigned successfully")
        passed += 1
    else:
        fail(f"configure_pid_assignment returned {rc.name}")
        failed += 1

    # ------------------------------------------------------------------
    # 3. Get PID Binding  (opcode 0x5705)
    # ------------------------------------------------------------------
    header("3. Get PID Binding  [5705h]")
    req = GetPidBindingRequestPayload(pid=0x123)
    rc, resp = await api.get_pid_binding(req)
    if rc == CCI_RETURN_CODE.SUCCESS and resp:
        ok(f"PID         : {resp.pid:#05x}")
        ok(f"Bound PID   : {resp.bound_pid:#05x}")
        ok(f"HMAT index  : {resp.hmat_entry_index}")
        passed += 1
    else:
        fail(f"get_pid_binding returned {rc.name}")
        failed += 1

    # ------------------------------------------------------------------
    # 4. Configure PID Binding  (opcode 0x5706)
    # ------------------------------------------------------------------
    header("4. Configure PID Binding  [5706h]")
    req = ConfigurePidBindingRequestPayload(
        pid=0x123,
        target_pid=0x456,
        hmat_entry_index=0,
    )
    rc, resp = await api.configure_pid_binding(req)
    if rc == CCI_RETURN_CODE.SUCCESS:
        ok(f"PID 0x123 bound to target PID 0x456")
        passed += 1
    else:
        fail(f"configure_pid_binding returned {rc.name}")
        failed += 1

    # ------------------------------------------------------------------
    # 5. Set DRT  (opcode 0x5709)
    # ------------------------------------------------------------------
    header("5. Set DRT  [5709h]")
    req = SetDrtRequestPayload(
        drt_index=0,
        start_entry=0x123,
        entries=[
            DrtEntry(entry_type=DrtEntryType.PHYSICAL_PORT, routing_target=2),
        ]
    )
    rc, resp = await api.set_drt(req)
    if rc == CCI_RETURN_CODE.SUCCESS:
        ok(f"DRT[0][0x123] → Physical Port 2 programmed")
        passed += 1
    else:
        fail(f"set_drt returned {rc.name}")
        failed += 1

    # ------------------------------------------------------------------
    # 6. Get DRT  (opcode 0x5708)
    # ------------------------------------------------------------------
    header("6. Get DRT  [5708h]")
    req = GetDrtRequestPayload(drt_index=0, start_entry=0x123, num_entries=1)
    rc, resp = await api.get_drt(req)
    if rc == CCI_RETURN_CODE.SUCCESS and resp:
        ok(f"DRT Index   : {resp.drt_index}")
        ok(f"Start Entry : {resp.start_entry:#05x}")
        for i, e in enumerate(resp.entries):
            ok(f"Entry[{resp.start_entry + i:#05x}] type={e.entry_type.name}  target={e.routing_target}")
        passed += 1
    else:
        fail(f"get_drt returned {rc.name}")
        failed += 1

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    print(f"\n{'─'*60}")
    print(f"{BOLD}Results: {GREEN}{passed} passed{RESET}{BOLD}, {RED}{failed} failed{RESET}")
    print(f"{'─'*60}\n")

    await api.stop()
    await mctp_client_conn.stop()
    conn_task.cancel()
    api_task.cancel()
    return failed == 0


def main():
    parser = argparse.ArgumentParser(description="PBR FM CCI command smoke-test")
    parser.add_argument("--mctp-host", default="127.0.0.1", help="MCTP server host")
    parser.add_argument("--mctp-port", type=int, default=8100,  help="MCTP server port")
    args = parser.parse_args()

    success = asyncio.run(run_tests(args.mctp_host, args.mctp_port))
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
