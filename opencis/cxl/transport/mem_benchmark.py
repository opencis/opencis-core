#!/usr/bin/env python3
"""
Measure build speed of CxlMemMemWrPacket.create() with buffer pooling.
"""

import os, sys, time, random, gc

from opencis.cxl.transport.cxl_mem_packets import CxlMemMemWrPacket
from opencis.cxl.transport.cxl_mem_packets import CxlMemMemWrPacket

PAYLOAD = os.urandom(64)


data = b"\xa5" * 64


def bench_create(iters: int = 100_000):
    gc.disable()
    t0 = time.perf_counter()
    for _ in range(iters):
        with CxlMemMemWrPacket.create(
            addr=0x100,
            data=0xDEADBEEF,
            opcode=0x2,
            meta_field=0x5,
            meta_value=0x2,
            snp_type=0x2,
            ld_id=0x1,
        ) as packet:
            pass
    gc.enable()
    dt = time.perf_counter() - t0
    processed_mb = iters * (17 + len(PAYLOAD)) / 1024 / 1024
    print("Create loop: "
        f"{iters:,} pkts • {processed_mb/dt:6.2f} MB/s "
        f"(processed {processed_mb:.1f} MB in {dt:.3f} s)"
    )

def bench_create_assign(iters: int = 100_000):
    gc.disable()
    t0 = time.perf_counter()
    packet = CxlMemMemWrPacket.create(
        addr=0x100,
        data=0xDEADBEEF,
        opcode=0x2,
        meta_field=0x5,
        meta_value=0x2,
        snp_type=0x2,
        ld_id=0x1,
    )
    for _ in range(iters):
        packet.assign(
            addr=0x100,
            data=0xDEADBEEF,
            opcode=0x2,
            meta_field=0x5,
            meta_value=0x2,
            snp_type=0x2,
            ld_id=0x1,
        )
    gc.enable()
    dt = time.perf_counter() - t0
    processed_mb = iters * (17 + len(PAYLOAD)) / 1024 / 1024
    print("Create-Assign loop: "
        f"{iters:,} pkts • {processed_mb/dt:6.2f} MB/s "
        f"(processed {processed_mb:.1f} MB in {dt:.3f} s)"
    )


if __name__ == "__main__":
    iters = int(sys.argv[1]) if len(sys.argv) > 1 else 100_000
    bench_create(iters)
    bench_create_assign(iters)