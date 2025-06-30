"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

# pylint: disable=import-error, no-name-in-module
import os
import sys
import time
import gc

from opencis.cxl.transport.transaction import CxlMemMemWrPacket

PAYLOAD = os.urandom(64)


def bench(iters: int = 100_000):
    gc.disable()
    t0 = time.perf_counter()
    payload = int.from_bytes(PAYLOAD, "little")
    for i in range(iters):
        pkt = CxlMemMemWrPacket.create(
            addr=0x200,
            data=payload,
            ld_id=i % 16,
        )
    dt = time.perf_counter() - t0
    gc.enable()
    processed_mb = iters * len(pkt) / 1024 / 1024
    print(
        f"{iters:,} pkts • {processed_mb/dt:6.2f} MB/s "
        f"(processed {processed_mb:.1f} MB in {dt:.3f} s)"
    )


if __name__ == "__main__":
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 100_000
    bench(count)
