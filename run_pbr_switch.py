#!/usr/bin/env python3
"""
run_pbr_switch.py — Start a CXL PBR Switch as a standalone process.

Connection model
----------------
  The switch is a TCP CLIENT.  It CONNECTS OUTWARD to the FM CLI server.
  Start pbr_fm_cli.py (FM server) BEFORE starting this script.

Topology
--------
  Port 0 : USP  (upstream / host side)
  Port 1 : DSP  (device connects here — run_pbr_device.py)

Ports
-----
  Switch listen   :  --port       (default 8000) — devices connect here
  MCTP connect to :  --mctp-host  (default 127.0.0.1) — FM CLI server host
                     --mctp-port  (default 8100)       — FM CLI server port

Startup order
-------------
  Terminal 1:  python pbr_fm_cli.py        ← FM server (start FIRST)
  Terminal 2:  python run_pbr_switch.py    ← switch connects to FM
  Terminal 3:  python run_pbr_device.py    ← device connects to switch

Usage
-----
  python run_pbr_switch.py
  python run_pbr_switch.py --mctp-host 127.0.0.1 --mctp-port 8100

OS agnostic: Windows / Linux / macOS.
"""

import argparse
import asyncio
import sys
from pathlib import Path

# ── Make the opencis package importable from the repo root ───────────────────
sys.path.insert(0, str(Path(__file__).resolve().parent))

from opencis.apps.cxl_switch import CxlSwitch, CxlSwitchConfig  # noqa: E402
from opencis.cxl.component.physical_port_manager import PortConfig, PORT_TYPE  # noqa: E402


# ── ANSI colours (safe on all platforms) ────────────────────────────────────
if sys.platform == "win32":
    import os
    os.system("")  # enable VT100 escape codes on Windows 10+

BOLD  = "\033[1m"
CYAN  = "\033[96m"
GREEN = "\033[92m"
RESET = "\033[0m"


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="PBR CXL Switch — standalone process",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--host",       default="0.0.0.0",   help="Switch listen host (devices connect here)")
    p.add_argument("--port",       type=int, default=8000, help="Switch TCP port (devices)")
    p.add_argument("--mctp-host",  default="127.0.0.1", help="FM CLI host to CONNECT TO (pbr_fm_cli.py)")
    p.add_argument("--mctp-port",  type=int, default=8100, help="FM CLI MCTP port to connect to")
    return p.parse_args()


async def _run(args: argparse.Namespace) -> None:
    print(f"\n{BOLD}{CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{RESET}")
    print(f"{BOLD}  CXL PBR Switch{RESET}")
    print(f"{CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{RESET}")
    print(f"  Device listen  : {args.host}:{args.port}")
    print(f"  FM CLI connect : {args.mctp_host}:{args.mctp_port}  (switch → FM)")
    print(f"  Port 0         : USP (host side)")
    print(f"  Port 1         : DSP (device connects here)")
    print(f"{CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{RESET}\n")

    config = CxlSwitchConfig(
        port_configs=[
            PortConfig(PORT_TYPE.USP),   # port 0 — upstream
            PortConfig(PORT_TYPE.DSP),   # port 1 — downstream (device)
        ],
        host=args.host,
        port=args.port,
        mctp_host=args.mctp_host,
        mctp_port=args.mctp_port,
        enable_pbr=True,
        run_as_child=False,
    )

    switch = CxlSwitch(config, device_configs=[])
    print(f"{GREEN}[Switch] Starting…{RESET}  Press Ctrl+C to stop.\n")
    await switch.run()


def main() -> None:
    args = _parse_args()

    # Windows: ProactorEventLoop is required for asyncio TCP on Windows
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

    try:
        asyncio.run(_run(args))
    except KeyboardInterrupt:
        print(f"\n{BOLD}[Switch] Stopped.{RESET}")


if __name__ == "__main__":
    main()
