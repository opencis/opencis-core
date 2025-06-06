import numpy as np
import time
from transaction import (
    CxlIoMemRdPacket,
    CxlIoMemWrPacket,
    CxlIoCompletionPacket,
    CxlIoCompletionWithDataPacket,
    CxlCacheD2HReqPacket,
    CxlCacheD2HRspPacket,
    CxlCacheD2HDataPacket,
    CxlCacheH2DReqPacket,
    CxlCacheH2DRspPacket,
    CxlCacheH2DDataPacket,
)


def handle_rd_packet(pkt):
    print("CxlIoMemRdPacket:")
    print(f"  req_id     = {pkt.mreq_header.req_id}")
    print(f"  tag        = {pkt.mreq_header.tag}")
    print(f"  addr_upper = {pkt.mreq_header.addr_upper}")
    print()


def handle_wr_packet(pkt):
    print("CxlIoMemWrPacket:")
    print(f"  req_id     = {pkt.mreq_header.req_id}")
    print(f"  tag        = {pkt.mreq_header.tag}")
    print(f"  addr_upper = {pkt.mreq_header.addr_upper}")
    print(f"  data       = {bytes(pkt.get_data())}")
    print()


def benchmark_packet_io(packet, data, iterations=10000):
    """Benchmark write + read data for a given packet."""
    start = time.time()
    for _ in range(iterations):
        packet.set_data(data)
    write_time = time.time() - start

    start = time.time()
    for _ in range(iterations):
        _ = bytes(packet.get_data())
    read_time = time.time() - start

    total_bytes = len(data) * iterations
    write_MBps = total_bytes / (1024 * 1024) / write_time
    read_MBps = total_bytes / (1024 * 1024) / read_time

    print(f"[WRITE] {total_bytes} bytes in {write_time:.3f}s → {write_MBps:.2f} MB/s")
    print(f"[READ]  {total_bytes} bytes in {read_time:.3f}s → {read_MBps:.2f} MB/s")
    print()


def main():
    buf_rd = np.zeros(24, dtype=np.uint8)
    rd_pkt = CxlIoMemRdPacket(buf_rd)
    rd_pkt.mreq_header.req_id = 0x1234
    rd_pkt.mreq_header.tag = 0x56
    rd_pkt.mreq_header.addr_upper = 0xFFFFFFFFABCDEFBA
    handle_rd_packet(rd_pkt)

    buf_wr = np.zeros(128, dtype=np.uint8)
    wr_pkt = CxlIoMemWrPacket(buf_wr)
    wr_pkt.mreq_header.req_id = 0x4341
    wr_pkt.mreq_header.tag = 0x78
    wr_pkt.mreq_header.addr_upper = 0xFFFFFFFF12345678

    data = np.random.randint(0, 256, size=64, dtype=np.uint8)
    print("Benchmarking data I/O...")
    benchmark_packet_io(wr_pkt, data, iterations=100000)

    # Demonstrate functionality
    wr_pkt.set_data(data[:10])
    handle_wr_packet(wr_pkt)

    pkt = CxlIoMemRdPacket.create(0x4000, 0x20)
    print(f"{pkt.is_cxl_io()}, {pkt.is_mmio()}, {pkt.is_cxl_mem()}")

    buf_wr = np.zeros(128, dtype=np.uint8)
    pkt = CxlIoMemWrPacket.create(0x4000, data[:10])
    print(f"{pkt.is_cxl_io()}, {pkt.is_mmio()}, {pkt.is_cxl_mem()}")

    print(f"pre: {pkt.get_size()}")
    data = np.array(list(b"Hello World"), dtype=np.uint8)
    pkt.set_data(data)
    print(f"post: {pkt.get_size()}")
    # handle_wr_packet(pkt)

    print(f"pre: {pkt.get_size()}")
    data = np.array(list(b"Hel"), dtype=np.uint8)
    pkt.set_data(data)
    print(f"post: {pkt.get_size()}")

    packet = CxlIoCompletionPacket.create(req_id=0, tag=1)


    # CXL Cache D2H Request
    d2h_req = CxlCacheD2HReqPacket.create(
        addr=0x1000,
        cache_id=1,
        opcode=5,
        cqid=5,
    )

    # CXL Cache D2H Response
    d2h_rsp = CxlCacheD2HRspPacket.create(
        uqid=42,
        opcode=6,
    )

    # CXL Cache D2H Data
    d2h_data = CxlCacheD2HDataPacket.create(
        uqid=42,
        data=0xDEADBEEFCAFEBABE,
    )

    # CXL Cache H2D Request
    h2d_req = CxlCacheH2DReqPacket.create(
        addr=0x2000,
        cache_id=2,
        opcode=7,
    )

    # CXL Cache H2D Response
    h2d_rsp = CxlCacheH2DRspPacket.create(
        cache_id=2,
        opcode=1,
        rsp_data=2,
        cqid=3,
    )

    # CXL Cache H2D Data
    h2d_data = CxlCacheH2DDataPacket.create(
        cache_id=2,
        data=0xAABBCCDDEEFF0011,
        cqid=3,
    )



if __name__ == "__main__":
    main()
