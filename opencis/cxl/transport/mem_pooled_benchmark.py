#!/usr/bin/env python3
"""
Measure build speed of CxlMemMemWrPacket.create() with buffer pooling.
"""

import os, sys, time, random, gc

from opencis.cxl.transport.packet_pooled import CxlMemPooledPacket

PAYLOAD = os.urandom(64)


class CxlMemKyeyoonPacket(CxlMemPooledPacket):
    @classmethod
    def create(
        cls,
        addr: int,
        opcode: int,
        meta_field: int,
        meta_value: int,
        snp_type: int,
        ld_id: int,
        data: bytes,
    ):
        return CxlMemPooledPacket.create(
            addr, opcode, meta_field, meta_value, snp_type, ld_id, data
        )


def bench(iters: int = 100_000):
    t0 = time.perf_counter()
    data = bytes(bytearray(64))
    for i in range(iters):
        with CxlMemKyeyoonPacket.create(
            addr=0x100,
            opcode=0x2,
            meta_field=0x5,
            meta_value=0x2,
            snp_type=0x2,
            ld_id=0x1,
            data=PAYLOAD,
        ):
            pass

    dt = time.perf_counter() - t0
    processed_mb = iters * (17 + len(data)) / 1024 / 1024
    print(
        f"{iters:,} pkts • {processed_mb/dt:6.2f} MB/s "
        f"(processed {processed_mb:.1f} MB in {dt:.3f} s)"
    )


if __name__ == "__main__":
    iters = int(sys.argv[1]) if len(sys.argv) > 1 else 100_000
    bench(iters)
