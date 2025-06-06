import numpy as np
import time
from transaction import (
    CxlIoMemRdPacket,
    CxlIoMemWrPacket,
    CxlIoCfgRdPacket,
    CxlIoCfgWrPacket,
    CxlIoCompletionPacket,
    CxlIoCompletionWithDataPacket,
    CxlCacheD2HReqPacket,
    CxlCacheD2HRspPacket,
    CxlCacheD2HDataPacket,
    CxlCacheH2DReqPacket,
    CxlCacheH2DRspPacket,
    CxlCacheH2DDataPacket,
    CxlMemMemRdPacket,
    CxlMemMemWrPacket,
    CxlMemBIRspPacket,
    CxlMemBISnpPacket,
    CxlMemMemDataPacket,
    CxlMemCmpPacket,
)
from packet_constants import (
    SYSTEM_PAYLOAD_TYPE,
    CXL_IO_FMT_TYPE,
    CXL_IO_CPL_STATUS,
    CXL_CACHE_MSG_CLASS,
    CXL_CACHE_D2HREQ_OPCODE,
    CXL_CACHE_D2HRSP_OPCODE,
    CXL_CACHE_H2DREQ_OPCODE,
    CXL_CACHE_H2DRSP_OPCODE,
    CXL_CACHE_H2DRSP_CACHE_STATE,
    CXL_MEM_MSG_CLASS,
    CXL_MEM_M2SREQ_OPCODE,
    CXL_MEM_M2SRWD_OPCODE,
    CXL_MEM_META_FIELD,
    CXL_MEM_META_VALUE,
    CXL_MEM_M2S_SNP_TYPE,
    CXL_MEM_M2SBIRSP_OPCODE,
    CXL_MEM_S2MBISNP_OPCODE,
    CXL_MEM_S2MDRS_OPCODE,
    CXL_MEM_S2MNDR_OPCODE,
)


def instantiate_packets():
    CxlMemBISnpPacket.tag = 0  # ensure static tag starts correctly

    packets = []

    buf = np.zeros(128, dtype=np.uint8)  # binary buffer for test payloads

    # side band packets
    packets.append(CxlIoMemRdPacket.create(addr=0x1000, length=4, req_id=1, tag=2))

    # CXL.io memory packets
    packets.append(CxlIoMemRdPacket.create(addr=0x1000, length=4, req_id=1, tag=2))
    packets.append(CxlIoMemWrPacket.create(addr=0x1000, data=buf[:4], req_id=1, tag=2))

    # CXL.io config packets
    packets.append(CxlIoCfgRdPacket.create(id=0x10, cfg_addr=0x04, size=1, req_id=1, tag=1))
    packets.append(
        CxlIoCfgWrPacket.create(id=0x10, cfg_addr=0x04, size=1, value=0xDE, req_id=1, tag=1)
    )

    # CXL.io completion packets
    packets.append(CxlIoCompletionPacket.create(req_id=0x10, tag=0x1A))
    packets.append(CxlIoCompletionWithDataPacket.create(req_id=0x10, tag=0x1A, data=buf))

    # CXL.cache packets
    packets.append(
        CxlCacheD2HReqPacket.create(
            addr=0x1000, cache_id=1, opcode=CXL_CACHE_D2HREQ_OPCODE.CACHE_RD_CURR, cqid=0
        )
    )
    packets.append(CxlCacheD2HRspPacket.create(uqid=1, opcode=CXL_CACHE_D2HRSP_OPCODE.RSP_I_HIT_I))
    packets.append(CxlCacheD2HDataPacket.create(uqid=1, data=0xDEADBEEF))
    packets.append(
        CxlCacheH2DReqPacket.create(
            addr=0x1000, cache_id=1, opcode=CXL_CACHE_H2DREQ_OPCODE.SNP_DATA
        )
    )
    packets.append(
        CxlCacheH2DRspPacket.create(
            cache_id=1,
            opcode=CXL_CACHE_H2DRSP_OPCODE.WRITE_PULL,
            rsp_data=CXL_CACHE_H2DRSP_CACHE_STATE.EXCLUSIVE,
        )
    )
    packets.append(CxlCacheH2DDataPacket.create(cache_id=1, data=0xBEEF))

    # CXL.mem packets
    packets.append(CxlMemMemRdPacket.create(addr=0x1000))
    packets.append(CxlMemMemWrPacket.create(addr=0x1000, data=0x12345678))
    packets.append(CxlMemBIRspPacket.create(opcode=CXL_MEM_M2SBIRSP_OPCODE.BIRSP_I))
    packets.append(CxlMemBISnpPacket.create(addr=0x1000, opcode=CXL_MEM_S2MBISNP_OPCODE.BISNP_DATA))
    packets.append(CxlMemMemDataPacket.create(data=buf))  # buffer passed directly
    packets.append(CxlMemCmpPacket.create())

    return packets


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
    handle_wr_packet(pkt)

    print(f"pre: {pkt.get_size()}")
    data = np.array(list(b"Hel"), dtype=np.uint8)
    pkt.set_data(data)
    print(f"post: {pkt.get_size()}")

    res = instantiate_packets()
    print(res)


if __name__ == "__main__":
    main()
