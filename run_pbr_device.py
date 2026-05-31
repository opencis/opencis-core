#!/usr/bin/env python3
"""
run_pbr_device.py — Start a CXL SingleLogicalDevice (Type-3 memory) that
connects to the PBR switch as a DSP device.

The device maps a local file (--mem-file) as its CXL memory backing store.
The FM CLI (pbr_fm_cli.py) reads/writes this same file to prove data
actually reaches the device — no QEMU or host root complex required.

Usage
-----
  python run_pbr_device.py
  python run_pbr_device.py --switch-host 127.0.0.1 --switch-port 8000
  python run_pbr_device.py --port-index 1 --mem-file pbr_dev_mem.bin

OS agnostic: Windows / Linux / macOS.
"""

import argparse
import asyncio
import sys
from pathlib import Path

# ── Make the opencis package importable from the repo root ───────────────────
sys.path.insert(0, str(Path(__file__).resolve().parent))

from opencis.apps.single_logical_device import SingleLogicalDevice  # noqa: E402


# ── ANSI colours ─────────────────────────────────────────────────────────────
if sys.platform == "win32":
    import os
    os.system("")

BOLD   = "\033[1m"
CYAN   = "\033[96m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
RESET  = "\033[0m"

DEFAULT_MEM_SIZE = 1 * 1024 * 1024   # 1 MiB
DEFAULT_MEM_FILE = "pbr_dev_mem.bin"


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="PBR CXL Memory Device — standalone process",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--switch-host", default="127.0.0.1", help="PBR switch host")
    p.add_argument("--switch-port", type=int, default=8000, help="PBR switch TCP port")
    p.add_argument(
        "--port-index", type=int, default=1,
        help="DSP port index to connect to on the switch"
    )
    p.add_argument(
        "--mem-file", default=DEFAULT_MEM_FILE,
        help="Path to memory backing file (created/zeroed if absent)"
    )
    p.add_argument(
        "--mem-size", type=int, default=DEFAULT_MEM_SIZE,
        help="Memory size in bytes"
    )
    p.add_argument(
        "--serial", default="0000000000000001",
        help="16-hex-digit device serial number"
    )
    return p.parse_args()


def _prepare_memory_file(path: Path, size: int) -> None:
    """Create or resize the backing file to exactly `size` bytes."""
    if not path.exists():
        path.write_bytes(b"\x00" * size)
        print(f"{YELLOW}[Device] Created memory file: {path.resolve()} ({size} bytes){RESET}")
    else:
        current = path.stat().st_size
        if current < size:
            # Pad to requested size
            with path.open("ab") as f:
                f.write(b"\x00" * (size - current))
            print(
                f"{YELLOW}[Device] Padded memory file: {path.resolve()} "
                f"({current} → {size} bytes){RESET}"
            )
        else:
            print(f"[Device] Using existing memory file: {path.resolve()} ({current} bytes)")


async def _run(args: argparse.Namespace) -> None:
    mem_path = Path(args.mem_file)
    _prepare_memory_file(mem_path, args.mem_size)

    print(f"\n{BOLD}{CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{RESET}")
    print(f"{BOLD}  CXL PBR Memory Device (SLD){RESET}")
    print(f"{CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{RESET}")
    print(f"  Switch       : {args.switch_host}:{args.switch_port}")
    print(f"  DSP port     : {args.port_index}")
    print(f"  Memory file  : {mem_path.resolve()}")
    print(f"  Memory size  : {args.mem_size:,} bytes  ({args.mem_size // 1024} KiB)")
    print(f"  Serial #     : {args.serial}")
    print(f"{CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{RESET}\n")

    device = SingleLogicalDevice(
        memory_size=args.mem_size,
        memory_file=str(mem_path),
        serial_number=args.serial,
        host=args.switch_host,
        port=args.switch_port,
        port_index=args.port_index,
    )

    print(f"{GREEN}[Device] Connecting to switch…{RESET}  Press Ctrl+C to stop.\n")
    await device.run()


def main() -> None:
    args = _parse_args()

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

    try:
        asyncio.run(_run(args))
    except KeyboardInterrupt:
        print(f"\n{BOLD}[Device] Stopped.{RESET}")


if __name__ == "__main__":
    main()
