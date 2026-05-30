#!/usr/bin/env python3
"""
run_pbr_env.py — Single-script PBR test environment.

Launches EVERYTHING in one process — no startup ordering issues:
  • SmbusToMctpBridge (optional) — Unix socket ↔ FM MCTP :8300 adapter
  • CxlFabricManager  (FM MCTP server on :8100, switch connects here)
  • CxlSwitch         (PBR mode, connects to FM on :8100, devices on :8000)
                       Port 0: USP | Port 1: DSP (SLD) | Port 2: DSP (GFD)
  • SingleLogicalDevice  (1 MiB memory, connects to switch port 1)
  • GenericFabricDevice  (GFD, connects to switch port 2)

Once running, use pbr_fm_cli.py in another terminal to send commands.

Usage
-----
  python run_pbr_env.py
  python run_pbr_env.py --switch-port 8000 --fm-port 8100 --mem-file pbr_dev_mem.bin

OS agnostic: Windows / Linux / macOS.
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from opencis.apps.cxl_switch import CxlSwitch, CxlSwitchConfig      # noqa
from opencis.apps.fabric_manager import CxlFabricManager              # noqa
from opencis.apps.single_logical_device import SingleLogicalDevice    # noqa
from opencis.apps.generic_fabric_device import GenericFabricDevice    # noqa
from opencis.apps.cxl_simple_host import CxlSimpleHost                # noqa
from opencis.cxl.component.physical_port_manager import PortConfig, PORT_TYPE  # noqa
from opencis.cxl.component.hdm_decoder import DecoderInfo, INTERLEAVE_GRANULARITY, INTERLEAVE_WAYS  # noqa

# ── ANSI colours ─────────────────────────────────────────────────────────────
if sys.platform == "win32":
    import os
    os.system("")
BOLD  = "\033[1m"
CYAN  = "\033[96m"
GREEN = "\033[92m"
YELLOW= "\033[93m"
RESET = "\033[0m"

DEFAULT_SLD_MEM_FILE = "pbr_sld_mem.bin"
DEFAULT_GFD_MEM_FILE = "pbr_gfd_mem.bin"
DEFAULT_MEM_SIZE = 1 * 1024 * 1024   # 1 MiB
# Legacy alias kept for backward compat
DEFAULT_MEM_FILE = DEFAULT_SLD_MEM_FILE


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="PBR all-in-one environment (switch + FM + SLD + GFD)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--switch-host", default="0.0.0.0",   help="Switch device listen host")
    p.add_argument("--switch-port", type=int, default=8000, help="Switch TCP port (devices connect here)")
    p.add_argument("--fm-host",     default="0.0.0.0",   help="FM MCTP listen host (switch connects here)")
    p.add_argument("--fm-port",     type=int, default=8100, help="FM MCTP port")
    p.add_argument("--sio-host",    default="0.0.0.0",   help="FM Socket.IO listen host")
    p.add_argument("--sio-port",    type=int, default=8200, help="FM Socket.IO port (CLI connects here)")
    p.add_argument("--sld-mem",     default=DEFAULT_SLD_MEM_FILE, help="SLD (port 1) memory file")
    p.add_argument("--gfd-mem",     default=DEFAULT_GFD_MEM_FILE, help="SLD2/GFD (port 2) memory file")
    p.add_argument("--mem-size",    type=int, default=DEFAULT_MEM_SIZE, help="Memory size per device (bytes)")
    # Legacy alias
    p.add_argument("--mem-file",    default=None, help="Legacy alias for --sld-mem")
    # ── SMBus-MCTP bridge (optional) ─────────────────────────────────────────
    p.add_argument(
        "--smbus-bridge",
        default=None,
        metavar="SOCKET_PATH",
        help=(
            "If set, start the SMBus-MCTP bridge on this Unix socket path "
            "(e.g. /tmp/smbus_mctp.sock).  QEMU SMBus Slave connects here; "
            "bridge forwards raw MCTP CciPayloadPackets to FM port 8300."
        ),
    )
    p.add_argument(
        "--smbus-fm-port",
        type=int,
        default=8300,
        help="FM MCTP CCI port that the SMBus bridge connects to (default 8300).",
    )
    return p.parse_args()


def _prepare_memory_file(path: Path, size: int) -> None:
    if not path.exists():
        path.write_bytes(b"\x00" * size)
        print(f"{YELLOW}[Env] Created memory file: {path.resolve()} ({size:,} bytes){RESET}")
    else:
        existing = path.stat().st_size
        if existing < size:
            with path.open("ab") as f:
                f.write(b"\x00" * (size - existing))


async def _run(args: argparse.Namespace) -> None:
    # Resolve memory file paths (legacy --mem-file overrides --sld-mem)
    sld_mem = Path(args.mem_file if args.mem_file else args.sld_mem)
    gfd_mem = Path(args.gfd_mem)
    _prepare_memory_file(sld_mem, args.mem_size)
    _prepare_memory_file(gfd_mem, args.mem_size)

    print(f"\n{BOLD}{CYAN}{'━' * 62}{RESET}")
    print(f"{BOLD}  PBR Test Environment (all-in-one){RESET}")
    print(f"{CYAN}{'━' * 62}{RESET}")
    print(f"  FM MCTP (switch) : {args.fm_host}:{args.fm_port}   ← switch connects here")
    print(f"  FM Socket.IO     : {args.sio_host}:{args.sio_port}  ← pbr_fm_cli.py connects here")
    print(f"  FM MCTP CCI      : {args.fm_host}:{args.smbus_fm_port}  ← MCTP clients / SMBus bridge")
    print(f"  Switch devices   : {args.switch_host}:{args.switch_port}")
    print(f"    Port 0 : USP")
    print(f"    Port 1 : DSP  ← SLD  (memory: {sld_mem.name})")
    print(f"    Port 2 : DSP  ← SLD2 (memory: {gfd_mem.name})")
    print(f"  SLD memory file  : {sld_mem.resolve()}")
    print(f"  GFD memory file  : {gfd_mem.resolve()}")
    if args.smbus_bridge:
        print(f"  SMBus-MCTP bridge: {args.smbus_bridge} → :{args.smbus_fm_port}")
    print(f"{CYAN}{'━' * 62}{RESET}")
    print(f"\n{YELLOW}Tip: Run  python pbr_fm_cli.py  in another terminal.{RESET}\n")

    # ── Fabric Manager (MCTP server — switch connects to this) ───────────────
    fm = CxlFabricManager(
        mctp_host=args.fm_host,
        mctp_port=args.fm_port,
        socketio_host=args.sio_host,
        socketio_port=args.sio_port,
    )

    # ── PBR Switch (client → FM, server ← devices) ──────────────────────────
    sw_config = CxlSwitchConfig(
        port_configs=[
            PortConfig(PORT_TYPE.USP),   # port 0 — upstream
            PortConfig(PORT_TYPE.DSP),   # port 1 — SLD connects here
            PortConfig(PORT_TYPE.DSP),   # port 2 — GFD connects here
        ],
        host=args.switch_host,
        port=args.switch_port,
        mctp_host="127.0.0.1",          # switch connects TO FM on loopback
        mctp_port=args.fm_port,
        enable_pbr=True,
        run_as_child=False,
    )
    switch = CxlSwitch(sw_config, device_configs=[])

    # ── Pre-program HDM Decoder for Host Injection ───────────────────────────
    # This allows a Host (Port 0) to send pure HBR packets. The Switch will
    # translate Address 0x0 -> DPID 0x100, then encapsulate it into a PBR Flit.
    if switch._pbr_hdm_decoder_manager:
        # Decoder 0: Map 0x00000 to 0x100000 to Port 1 (DPID 0x100)
        decoder_info_0 = DecoderInfo(
            base=0x0,
            size=args.mem_size,  # Assuming 256MB from args.mem_size
            ig=INTERLEAVE_GRANULARITY.SIZE_256B,
            iw=INTERLEAVE_WAYS.WAY_1,
            target_ports=[0x100]  # Map base address to DPID 0x100
        )
        switch._pbr_hdm_decoder_manager.commit(0, decoder_info_0)

        # Decoder 1: Map the next contiguous block to Port 2 (DPID 0x200)
        decoder_info_1 = DecoderInfo(
            base=args.mem_size,
            size=args.mem_size,
            ig=INTERLEAVE_GRANULARITY.SIZE_256B,
            iw=INTERLEAVE_WAYS.WAY_1,
            target_ports=[0x200]  # Map base address to DPID 0x200
        )
        switch._pbr_hdm_decoder_manager.commit(1, decoder_info_1)

    # ── SLD port 1 — Type-3 CXL memory device ────────────────────────────────
    sld = SingleLogicalDevice(
        memory_size=args.mem_size,
        memory_file=str(sld_mem),
        serial_number="0000000000000001",
        host="127.0.0.1",
        port=args.switch_port,
        port_index=1,
    )

    # ── GFD port 2 — Generic Fabric Device ───────────────────────────────────
    gfd = GenericFabricDevice(
        host="127.0.0.1",
        port=args.switch_port,
        port_index=2,
        serial_number="0000000000000002",
    )

    # ── Start FM server first so the switch can connect ──────────────────────
    fm_task     = asyncio.create_task(fm.run())
    await fm.wait_for_ready()
    print(f"{GREEN}[Env] FM server ready on :{args.fm_port}{RESET}")

    # ── Optional SMBus-MCTP bridge ────────────────────────────────────────────
    bridge      = None
    bridge_task = None
    if args.smbus_bridge:
        from opencis.cxl.component.smbus.smbus_mctp_bridge import SmbusToMctpBridge
        bridge = SmbusToMctpBridge(
            unix_socket_path=args.smbus_bridge,
            fm_host="127.0.0.1",
            fm_port=args.smbus_fm_port,
        )
        bridge_task = asyncio.create_task(bridge.run())
        await bridge.wait_for_ready()
        print(f"{GREEN}[Env] SMBus-MCTP bridge ready on {args.smbus_bridge}{RESET}")

    # ── Start switch — connects to FM, listens for devices ───────────────────
    sw_task     = asyncio.create_task(switch.run())
    await switch.wait_for_ready()
    print(f"{GREEN}[Env] Switch ready on :{args.switch_port}{RESET}")

    # ── Start Host on port 0 ─────────────────────────────────────────────────
    host = CxlSimpleHost(
        port_index=0,
        switch_port=args.switch_port,
        hm_mode=False,
    )
    host_task   = asyncio.create_task(host.run())
    await host.wait_for_ready()
    print(f"{GREEN}[Env] Host ready (port 0){RESET}")

    # ── Start SLD and GFD — connect to switch ────────────────────────────────
    sld_task    = asyncio.create_task(sld.run())
    gfd_task    = asyncio.create_task(gfd.run())
    
    await sld.wait_for_ready()
    print(f"{GREEN}[Env] SLD ready (port 1, memory: {sld_mem.name}){RESET}")
    await gfd.wait_for_ready()
    print(f"{GREEN}[Env] GFD ready (port 2){RESET}")

    print(f"\n{BOLD}{GREEN}All components up. Run pbr_data_plane_injector.py to test host.{RESET}")
    if args.smbus_bridge:
        print(f"{GREEN}SMBus bridge active on {args.smbus_bridge}{RESET}")
    print(f"{CYAN}Press Ctrl+C to stop.{RESET}\n")

    tasks = [fm_task, sw_task, host_task, sld_task, gfd_task]
    if bridge_task is not None:
        tasks.append(bridge_task)
    await asyncio.gather(*tasks)


def main() -> None:
    args = _parse_args()

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

    try:
        asyncio.run(_run(args))
    except KeyboardInterrupt:
        print(f"\n{BOLD}[Env] Stopped.{RESET}")


if __name__ == "__main__":
    main()
