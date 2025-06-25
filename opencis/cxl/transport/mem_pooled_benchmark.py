#!/usr/bin/env python3
"""
Measure build speed of CxlMemMemWrPacket.create() with buffer pooling.
"""

import os, sys, time, random, gc

from opencis.cxl.transport.cxl_mem_packets import CxlMemKyeyoonPacket
from opencis.cxl.transport.packet_pooled import CxlMemPooledPacket

PAYLOAD = os.urandom(64)


def bench(iters: int = 100_000):
    #gc.disable()
    t0 = time.perf_counter()
    for i in range(iters):
        pkt = CxlMemKyeyoonPacket.create(
            addr=0x100,
            opcode=0x2,
            meta_field=0x5,
            meta_value=0x2,
            snp_type=0x2,
            ld_id=0x1
        )
        del pkt
    dt = time.perf_counter() - t0
    #gc.enable()
    processed_mb = iters * 17 / 1024 / 1024
    print(
        f"{iters:,} pkts • {processed_mb/dt:6.2f} MB/s "
        f"(processed {processed_mb:.1f} MB in {dt:.3f} s)"
    )


if __name__ == "__main__":
    iters = int(sys.argv[1]) if len(sys.argv) > 1 else 100_000
    bench(iters)
