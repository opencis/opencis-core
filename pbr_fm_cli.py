#!/usr/bin/env python3
"""
pbr_fm_cli.py — Interactive FM CLI for PBR switch testing.

Connects to CxlFabricManager via Socket.IO on port :8200 (the correct
external FM API).  Uses socketio.AsyncSimpleClient which relies on aiohttp
(already in pyproject.toml) — no extra dependencies needed.

Startup
-------
  Terminal 1:  python run_pbr_env.py    ← all-in-one: FM + switch + SLD + GFD
  Terminal 2:  python pbr_fm_cli.py     ← this CLI

Menu
----
  [1]  Identify PBR Switch
  [2]  Assign PID 0x100 → port 1 (SLD)
  [3]  Assign PID 0x200 → port 2 (GFD)
  [4]  Set DRT  DPID=0x100 → Port 1
  [5]  Set DRT  DPID=0x200 → Port 2
  [6]  Get DRT (SLD)
  [7]  Get DRT (GFD)
  [8]  Get PID Binding (SLD)
  [9]  Configure PID Binding
  [w]  Mem-Write   write DEADBEEF to SLD memory file
  [r]  Mem-Read    read back and verify
  [a]  Run All     full workflow in one shot
  [c]  Clear PID 0x100
  [z]  Reset Memory File
  [0]  Quit

Usage
-----
  python pbr_fm_cli.py
  python pbr_fm_cli.py --fm-host 127.0.0.1 --fm-port 8200
  python pbr_fm_cli.py --mem-file pbr_dev_mem.bin

OS agnostic: Windows / Linux / macOS.
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import socketio  # python-socketio, already in pyproject.toml  # noqa

# ── ANSI colours ─────────────────────────────────────────────────────────────
if sys.platform == "win32":
    import os
    os.system("")

BOLD   = "\033[1m"
DIM    = "\033[2m"
CYAN   = "\033[96m"
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
RESET  = "\033[0m"

WRITE_PATTERN = b"\xDE\xAD\xBE\xEF" * 4   # 16 bytes
WRITE_OFFSET  = 0

PID_SLD  = 0x100
PID_GFD  = 0x200
PORT_SLD = 1
PORT_GFD = 2


# ─────────────────────────────────────────────────────────────────────────────
# Output helpers
# ─────────────────────────────────────────────────────────────────────────────

def _ok(msg: str)   -> None: print(f"  {GREEN}✓ PASS{RESET}  {msg}")
def _fail(msg: str) -> None: print(f"  {RED}✗ FAIL{RESET}  {msg}")
def _info(msg: str) -> None: print(f"  {CYAN}ℹ{RESET}      {msg}")


def _section(title: str) -> None:
    w = 60
    print(f"\n{BOLD}{CYAN}{'─' * w}{RESET}")
    print(f"{BOLD}  {title}{RESET}")
    print(f"{BOLD}{CYAN}{'─' * w}{RESET}")


def _banner(host: str, port: int, sld_mem: str, gfd_mem: str) -> None:
    print(f"\n{BOLD}{CYAN}{'━' * 62}{RESET}")
    print(f"{BOLD}  PBR FM Interactive CLI  (Socket.IO / aiohttp){RESET}")
    print(f"{CYAN}{'━' * 62}{RESET}")
    print(f"  FM Socket.IO  : http://{host}:{port}")
    print(f"  SLD memory    : {Path(sld_mem).resolve()}")
    print(f"  GFD memory    : {Path(gfd_mem).resolve()}")
    print(f"  PID_SLD       : {PID_SLD:#05x}  →  DSP port {PORT_SLD} (SLD)")
    print(f"  PID_GFD       : {PID_GFD:#05x}  →  DSP port {PORT_GFD} (GFD)")
    print(f"{CYAN}{'━' * 62}{RESET}\n")


def _menu() -> None:
    print(f"\n{BOLD}{'─' * 62}{RESET}")
    print(f"{BOLD}  Menu{RESET}")
    print(f"{'─' * 62}")
    items = [
        ("[1]", "Identify PBR Switch",      "pbr:identify"),
        ("[2]", "Assign PID 0x100 (SLD)",   f"pbr:configurePid → port {PORT_SLD}"),
        ("[3]", "Assign PID 0x200 (GFD)",   f"pbr:configurePid → port {PORT_GFD}"),
        ("[4]", "Set DRT for SLD",          f"pbr:setDrt  {PID_SLD:#05x} → port {PORT_SLD}"),
        ("[5]", "Set DRT for GFD",          f"pbr:setDrt  {PID_GFD:#05x} → port {PORT_GFD}"),
        ("[6]", "Get DRT (SLD)",            f"pbr:getDrt  {PID_SLD:#05x}"),
        ("[7]", "Get DRT (GFD)",            f"pbr:getDrt  {PID_GFD:#05x}"),
        ("[8]", "Get PID Binding",         "pbr:getPidBinding  VCS=0 vPPB=0"),
        ("[9]", "Configure PID Binding",    "pbr:configurePidBinding  Bind PID_SLD→VCS0/vPPB0"),
        ("[w]", "Mem-Write (SLD)",         "DEADBEEF → SLD memory file (Port 1)"),
        ("[r]", "Mem-Read  (SLD)",         "read back & verify (Port 1)"),
        ("[s]", "Mem-Write (GFD)",         "DEADBEEF → GFD memory file (Port 2)"),
        ("[g]", "Mem-Read  (GFD)",         "read back & verify (Port 2)"),
        ("[a]", "Run All",                 "full workflow 1→g"),
        ("[c]", "Clear PID 0x100",         "pbr:configurePid CLEAR"),
        ("[z]", "Reset Memory Files",      "zero-fill both"),
        ("[e]", "Identify GAE (GFA)",      "gae:identify"),
        ("[v]", "Get PID Access Vectors",   "gae:getPidAccessVectors  PID=0x200"),
        ("[p]", "Proxy GFD Mgmt Command",   "gae:proxyGfdMgmt (Forward Identify to GFD)"),
        ("[t]", "Get Proxy Thread Status",  "gae:getProxyStatus  Thread ID"),
        ("[y]", "Cancel Proxy Thread",      "gae:cancelProxy  Thread ID"),
        ("[0]", "Quit",                    ""),
    ]
    for key, label, note in items:
        note_str = f"  {DIM}{note}{RESET}" if note else ""
        print(f"  {BOLD}{CYAN}{key}{RESET}  {label}{note_str}")
    print(f"{'─' * 62}")


# ─────────────────────────────────────────────────────────────────────────────
# Async Socket.IO call wrapper
# ─────────────────────────────────────────────────────────────────────────────

async def _call(sio: socketio.AsyncSimpleClient, event: str, data=None) -> dict:
    """Emit a Socket.IO event and return the response dict."""
    if data is None:
        resp = await sio.call(event)
    else:
        resp = await sio.call(event, data)
    return resp if isinstance(resp, dict) else {"error": str(resp), "result": None}


def _check(resp: dict, label: str) -> bool:
    err = resp.get("error", "")
    if err:
        _fail(f"{label}: {err}")
        return False
    return True


# ─────────────────────────────────────────────────────────────────────────────
# PBR command implementations (async)
# ─────────────────────────────────────────────────────────────────────────────

async def cmd_identify(sio: socketio.AsyncSimpleClient) -> bool:
    _section("1. Identify PBR Switch  [pbr:identify]")
    resp = await _call(sio, "pbr:identify")
    if not _check(resp, "pbr:identify"):
        return False
    r = resp.get("result", {})
    _ok(f"GAE Support Map : {r.get('gaeSupportMap', '?'):#018x}")
    _ok(f"Num DRTs        : {r.get('numDrts', '?')}")
    _ok(f"Num RGTs        : {r.get('numRgts', '?')}")
    _ok(f"Routing Caps    : {r.get('routingCaps', '?'):#04x}")
    return True


async def cmd_assign_pid(
    sio: socketio.AsyncSimpleClient, pid: int, port: int, label: str
) -> bool:
    _section(f"Assign PID  PID={pid:#05x} → port {port} ({label})")
    data = {
        "operation": 0,  # ASSIGN
        "entries": [{"pid": pid, "targetId": port, "instanceId": 0}],
    }
    resp = await _call(sio, "pbr:configurePid", data)
    if not _check(resp, "pbr:configurePid"):
        return False
    _ok(f"PID {pid:#05x} assigned to port {port} ({label})  → {resp.get('result')}")
    return True


async def cmd_set_drt(
    sio: socketio.AsyncSimpleClient, pid: int, port: int, label: str
) -> bool:
    _section(f"Set DRT  DPID={pid:#05x} → Physical Port {port} ({label})")
    data = {
        "drtIndex": 0,
        "startEntry": pid,
        "entries": [{"entryType": "PHYSICAL_PORT", "routingTarget": port}],
    }
    resp = await _call(sio, "pbr:setDrt", data)
    if not _check(resp, "pbr:setDrt"):
        return False
    _ok(f"DRT[0][{pid:#05x}] → Physical Port {port}  → {resp.get('result')}")
    return True


async def cmd_get_drt(
    sio: socketio.AsyncSimpleClient, pid: int, label: str
) -> bool:
    _section(f"Get DRT  DPID={pid:#05x} ({label})")
    data = {"drtIndex": 0, "startEntry": pid, "numEntries": 1}
    resp = await _call(sio, "pbr:getDrt", data)
    if not _check(resp, "pbr:getDrt"):
        return False
    r = resp.get("result", {})
    _ok(f"DRT index   : {r.get('drtIndex', '?')}")
    _ok(f"Start entry : {r.get('startEntry', '?'):#05x}")
    for i, e in enumerate(r.get("entries", [])):
        _ok(
            f"Entry[{(r.get('startEntry', 0) + i):#05x}]  "
            f"type={e.get('entryType')}  target={e.get('routingTarget')}"
        )
    return True


async def cmd_get_pid_binding(
    sio: socketio.AsyncSimpleClient, vcs: int = 0, vppb: int = 0
) -> bool:
    _section(f"Get PID Binding  [pbr:getPidBinding]  VCS={vcs}  vPPB={vppb}")
    resp = await _call(sio, "pbr:getPidBinding", {"targetVcs": vcs, "targetVppb": vppb})
    if not _check(resp, "pbr:getPidBinding"):
        return False
    r = resp.get("result", {})
    pid = r.get("pid", 0xFFF)
    _ok(f"PID             : {pid:#05x}  {'(unbound)' if pid == 0xFFF else '(bound)'}")
    _ok(f"Latency Base    : {r.get('latencyEntryBaseUnit', 0)}")
    _ok(f"Latency Entry   : {r.get('latencyEntry', 0)}")
    _ok(f"BW Base         : {r.get('bwEntryBaseUnit', 0)}")
    _ok(f"BW Entry        : {r.get('bwEntry', 0)}")
    return True


async def cmd_configure_pid_binding(
    sio: socketio.AsyncSimpleClient,
    operation: int = 0,    # 0=Bind, 1=Unbind
    target_vcs: int = 0,
    target_vppb: int = 0,
    pid: int = 0,
) -> bool:
    op_str = "Bind" if operation == 0 else "Unbind"
    _section(f"Configure PID Binding  [{op_str}]  VCS={target_vcs}  vPPB={target_vppb}  PID={pid:#05x}")
    data = {
        "operation": operation,
        "targetVcs": target_vcs,
        "targetVppb": target_vppb,
        "pid": pid,
        "latencyEntryBaseUnit": 0,
        "latencyEntry": 0,
        "bwEntryBaseUnit": 0,
        "bwEntry": 0,
    }
    resp = await _call(sio, "pbr:configurePidBinding", data)
    if not _check(resp, "pbr:configurePidBinding"):
        return False
    _ok(f"{op_str} PID {pid:#05x} on VCS={target_vcs} vPPB={target_vppb}  → {resp.get('result')}")
    return True


async def cmd_clear_pid(
    sio: socketio.AsyncSimpleClient, pid: int, port: int
) -> bool:
    _section(f"Clear PID  PID={pid:#05x}")
    data = {
        "operation": 1,  # CLEAR
        "entries": [{"pid": pid, "targetId": port, "instanceId": 0}],
    }
    resp = await _call(sio, "pbr:configurePid", data)
    if not _check(resp, "pbr:configurePid CLEAR"):
        return False
    _ok(f"PID {pid:#05x} cleared from port {port}  → {resp.get('result')}")
    return True


async def cmd_identify_gae(sio: socketio.AsyncSimpleClient) -> bool:
    _section("Identify GAE  [gae:identify]")
    resp = await _call(sio, "gae:identify")
    if not _check(resp, "gae:identify"):
        return False
    r = resp.get("result", {})
    _ok(f"Num vPPBs with Global Memory : {r.get('numVppbsWithGlobalMemory', '?')}")
    for e in r.get("vppbEntries", []):
        _ok(f"  vPPB[{e.get('vppbId')}]  globalMemorySupport={e.get('globalMemorySupport')}")
    return True


async def cmd_get_pid_access_vectors(
    sio: socketio.AsyncSimpleClient, pid: int
) -> bool:
    _section(f"Get PID Access Vectors  [gae:getPidAccessVectors]  PID={pid:#05x}")
    resp = await _call(sio, "gae:getPidAccessVectors", {"pid": pid})
    if not _check(resp, "gae:getPidAccessVectors"):
        return False
    r = resp.get("result", {})
    _ok(f"PID           : {r.get('pid', 0):#05x}")
    _ok(f"GMV (Memory)  : {r.get('gmv', 0)}")
    _ok(f"VTV (Virtual) : {r.get('vtv', 0)}")
    return True


async def cmd_proxy_gfd_mgmt(
    sio: socketio.AsyncSimpleClient, gfd_opcode: int = 0x0001, gfd_payload: bytes = b""
) -> Optional[int]:
    _section(f"Proxy GFD Mgmt Command  [gae:proxyGfdMgmt]  Opcode={gfd_opcode:#06x}")
    data = {
        "gfdOpcode": gfd_opcode,
        "gfdPayload": list(gfd_payload) if gfd_payload else []
    }
    resp = await _call(sio, "gae:proxyGfdMgmt", data)
    if not _check(resp, "gae:proxyGfdMgmt"):
        return None
    r = resp.get("result", {})
    tid = r.get("threadId", 0)
    _ok(f"Started proxy thread ID: {tid}")
    return tid


async def cmd_get_proxy_status(
    sio: socketio.AsyncSimpleClient, thread_id: int
) -> bool:
    _section(f"Get Proxy Thread Status  [gae:getProxyStatus]  Thread ID={thread_id}")
    resp = await _call(sio, "gae:getProxyStatus", {"threadId": thread_id})
    if not _check(resp, "gae:getProxyStatus"):
        return False
    r = resp.get("result", {})
    _ok(f"Thread ID   : {r.get('threadId', '?')}")
    _ok(f"Completed   : {r.get('completed', '?')}")
    _ok(f"Return Code : {r.get('gfdReturnCode', '?')}")
    raw_payload = r.get("gfdResponsePayload", [])
    hex_payload = bytes(raw_payload).hex().upper() if raw_payload else "None"
    _ok(f"GFD Payload : {hex_payload}")
    return True


async def cmd_cancel_proxy(
    sio: socketio.AsyncSimpleClient, thread_id: int
) -> bool:
    _section(f"Cancel Proxy Thread  [gae:cancelProxy]  Thread ID={thread_id}")
    resp = await _call(sio, "gae:cancelProxy", {"threadId": thread_id})
    if not _check(resp, "gae:cancelProxy"):
        return False
    _ok(f"Cancelled thread {thread_id}  → {resp.get('result')}")
    return True


async def cmd_run_all(sio: socketio.AsyncSimpleClient, sld_mem: str, gfd_mem: str) -> None:
    results = []
    results.append(("Identify PBR Switch",    await cmd_identify(sio)))
    results.append(("Assign PID SLD (0x100)", await cmd_assign_pid(sio, PID_SLD, PORT_SLD, "SLD")))
    results.append(("Assign PID GFD (0x200)", await cmd_assign_pid(sio, PID_GFD, PORT_GFD, "GFD")))
    results.append(("Set DRT SLD",            await cmd_set_drt(sio, PID_SLD, PORT_SLD, "SLD")))
    results.append(("Set DRT GFD",            await cmd_set_drt(sio, PID_GFD, PORT_GFD, "GFD")))
    results.append(("Get DRT SLD",            await cmd_get_drt(sio, PID_SLD, "SLD")))
    results.append(("Get DRT GFD",            await cmd_get_drt(sio, PID_GFD, "GFD")))
    results.append(("Get PID Binding (VCS=0 vPPB=0)",          await cmd_get_pid_binding(sio, vcs=0, vppb=0)))
    results.append(("Configure PID Binding (Bind PID_SLD→VCS0)", await cmd_configure_pid_binding(sio, operation=0, target_vcs=0, target_vppb=0, pid=PID_SLD)))
    results.append(("Identify GAE (GFA)",     await cmd_identify_gae(sio)))
    results.append(("Get PID Access Vectors", await cmd_get_pid_access_vectors(sio, PID_GFD)))
    
    # GAE Proxy workflow
    tid = await cmd_proxy_gfd_mgmt(sio, gfd_opcode=0x0001)
    results.append(("Proxy GFD Mgmt (Start)", tid is not None))
    if tid:
        await asyncio.sleep(0.1)
        results.append(("Get Proxy Thread Status", await cmd_get_proxy_status(sio, tid)))
        results.append(("Cancel Proxy Thread (Idempotent)", await cmd_cancel_proxy(sio, tid)))

    results.append(("Mem-Write (SLD)",        cmd_mem_write(sld_mem)))
    results.append(("Mem-Read  (SLD)",        cmd_mem_read(sld_mem)))
    results.append(("Mem-Write (GFD)",        cmd_mem_write(gfd_mem)))
    results.append(("Mem-Read  (GFD)",        cmd_mem_read(gfd_mem)))

    passed = sum(1 for _, ok in results if ok)
    total  = len(results)
    print(f"\n{BOLD}{'═' * 62}{RESET}")
    print(f"{BOLD}  Run-All Results{RESET}")
    print(f"{'═' * 62}")
    for name, ok in results:
        mark = f"{GREEN}✓{RESET}" if ok else f"{RED}✗{RESET}"
        print(f"  {mark}  {name}")
    colour = GREEN if passed == total else RED
    print(f"{'─' * 62}")
    print(f"  {BOLD}{colour}{passed}/{total} passed{RESET}")
    print(f"{'═' * 62}\n")


# ─────────────────────────────────────────────────────────────────────────────
# Synchronous mem-write / mem-read (file I/O — no async needed)
# ─────────────────────────────────────────────────────────────────────────────

def cmd_mem_write(
    mem_file: str,
    pattern: bytes = WRITE_PATTERN,
    offset: int = WRITE_OFFSET,
) -> bool:
    _section(f"Mem-Write  →  {Path(mem_file).name}  @ offset {offset}")
    path = Path(mem_file)
    if not path.exists():
        _fail(f"Memory file not found: {path.resolve()}")
        _info("Is run_pbr_env.py running?")
        return False
    try:
        with path.open("r+b") as f:
            f.seek(offset)
            f.write(pattern)
        _ok(f"Wrote {len(pattern)} bytes: {pattern.hex().upper()}")
        _ok(f"File: {path.resolve()}")
        return True
    except OSError as exc:
        _fail(f"Write failed: {exc}")
        return False


def cmd_mem_read(
    mem_file: str,
    pattern: bytes = WRITE_PATTERN,
    offset: int = WRITE_OFFSET,
) -> bool:
    _section(f"Mem-Read   ←  {Path(mem_file).name}  @ offset {offset}")
    path = Path(mem_file)
    if not path.exists():
        _fail(f"Memory file not found: {path.resolve()}")
        return False
    try:
        with path.open("rb") as f:
            f.seek(offset)
            data = f.read(len(pattern))
        _info(f"Expected : {pattern.hex().upper()}")
        _info(f"Got      : {data.hex().upper()}")
        if data == pattern:
            _ok("Pattern matches — data is in the SLD device's memory ✓")
            return True
        _fail("Pattern mismatch")
        return False
    except OSError as exc:
        _fail(f"Read failed: {exc}")
        return False


def cmd_reset_mem(mem_file: str, size: int) -> bool:
    _section(f"Reset Memory File  →  {Path(mem_file).name}")
    path = Path(mem_file)
    try:
        path.write_bytes(b"\x00" * size)
        _ok(f"Zeroed {size:,} bytes in {path.resolve()}")
        return True
    except OSError as exc:
        _fail(f"Reset failed: {exc}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Async input helper (non-blocking in the event loop)
# ─────────────────────────────────────────────────────────────────────────────

async def _ainput(prompt: str = "") -> str:
    """Run input() in a thread-pool so the event loop stays unblocked."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: input(prompt))


# ─────────────────────────────────────────────────────────────────────────────
# Main async loop
# ─────────────────────────────────────────────────────────────────────────────

async def _main(args: argparse.Namespace) -> None:
    url = f"http://{args.fm_host}:{args.fm_port}"

    _banner(args.fm_host, args.fm_port, args.sld_mem, args.gfd_mem)
    print(f"{YELLOW}Connecting to FM Socket.IO server at {url}…{RESET}")
    print(f"{YELLOW}(Make sure run_pbr_env.py is running first){RESET}\n")

    sio = socketio.AsyncSimpleClient()
    try:
        await sio.connect(url, wait_timeout=10)
    except Exception as exc:
        print(f"{RED}[FM CLI] Connection failed: {exc}{RESET}")
        print(f"{YELLOW}  → Start run_pbr_env.py first, then retry.{RESET}")
        return

    print(f"{GREEN}Connected to FM Socket.IO server.{RESET}\n")

    try:
        while True:
            _menu()
            try:
                choice = (await _ainput(f"\n{BOLD}>{RESET} ")).strip().lower()
            except (EOFError, KeyboardInterrupt):
                choice = "0"

            if   choice == "1": await cmd_identify(sio)
            elif choice == "2": await cmd_assign_pid(sio, PID_SLD, PORT_SLD, "SLD")
            elif choice == "3": await cmd_assign_pid(sio, PID_GFD, PORT_GFD, "GFD")
            elif choice == "4": await cmd_set_drt(sio, PID_SLD, PORT_SLD, "SLD")
            elif choice == "5": await cmd_set_drt(sio, PID_GFD, PORT_GFD, "GFD")
            elif choice == "6": await cmd_get_drt(sio, PID_SLD, "SLD")
            elif choice == "7": await cmd_get_drt(sio, PID_GFD, "GFD")
            elif choice == "8": await cmd_get_pid_binding(sio, vcs=0, vppb=0)
            elif choice == "9": await cmd_configure_pid_binding(sio, operation=0, target_vcs=0, target_vppb=0, pid=PID_SLD)
            elif choice == "w": cmd_mem_write(args.sld_mem)
            elif choice == "r": cmd_mem_read(args.sld_mem)
            elif choice == "s": cmd_mem_write(args.gfd_mem)
            elif choice == "g": cmd_mem_read(args.gfd_mem)
            elif choice == "a": await cmd_run_all(sio, args.sld_mem, args.gfd_mem)
            elif choice == "c": await cmd_clear_pid(sio, PID_SLD, PORT_SLD)
            elif choice == "z": 
                cmd_reset_mem(args.sld_mem, args.mem_size)
                cmd_reset_mem(args.gfd_mem, args.mem_size)
            elif choice == "e": await cmd_identify_gae(sio)
            elif choice == "v": await cmd_get_pid_access_vectors(sio, PID_GFD)
            elif choice == "p": await cmd_proxy_gfd_mgmt(sio, gfd_opcode=0x0001)
            elif choice == "t":
                print("Enter Thread ID:")
                try:
                    t_val = int((await _ainput("> ")).strip())
                    await cmd_get_proxy_status(sio, t_val)
                except ValueError:
                    print("Invalid Thread ID")
            elif choice == "y":
                print("Enter Thread ID to cancel:")
                try:
                    t_val = int((await _ainput("> ")).strip())
                    await cmd_cancel_proxy(sio, t_val)
                except ValueError:
                    print("Invalid Thread ID")
            elif choice == "0":
                print(f"\n{BOLD}[FM CLI] Disconnecting…{RESET}")
                break
            else:
                print(f"  {YELLOW}Unknown choice '{choice}' — try again.{RESET}")

    except KeyboardInterrupt:
        print(f"\n{BOLD}[FM CLI] Interrupted.{RESET}")
    finally:
        await sio.disconnect()
        print(f"{BOLD}[FM CLI] Done.{RESET}\n")


# ─────────────────────────────────────────────────────────────────────────────
# Argument parsing & entry point
# ─────────────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="PBR FM Interactive CLI (Socket.IO / aiohttp)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--fm-host",  default="127.0.0.1",
                   help="FM Socket.IO host (run_pbr_env.py)")
    p.add_argument("--fm-port",  type=int, default=8200,
                   help="FM Socket.IO port")
    p.add_argument("--sld-mem",  default="pbr_sld_mem.bin",
                   help="SLD memory backing file")
    p.add_argument("--gfd-mem",  default="pbr_gfd_mem.bin",
                   help="GFD memory backing file")
    p.add_argument("--mem-size", type=int, default=1 * 1024 * 1024,
                   help="Memory size in bytes (used for reset)")
    return p.parse_args()


def main() -> None:
    args = _parse_args()

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

    try:
        asyncio.run(_main(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
