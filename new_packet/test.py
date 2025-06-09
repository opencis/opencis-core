import asyncio
import time
import io
import platform
import os
import cProfile
import pstats

from opencis.util.logger import logger
from transaction import (
    SidebandConnectionRequestPacket,
    CxlIoMemRdPacket,
    CxlIoMemWrPacket,
    CxlIoCfgRdPacket,
    CxlIoCfgWrPacket,
    CxlIoCompletionPacket,
    CxlIoCompletionWithDataPacket,
    CxlCacheCacheD2HReqPacket,
    CxlCacheCacheD2HRspPacket,
    CxlCacheCacheD2HDataPacket,
    CxlCacheCacheH2DReqPacket,
    CxlCacheCacheH2DRspPacket,
    CxlCacheCacheH2DDataPacket,
    CxlMemMemRdPacket,
    CxlMemMemWrPacket,
    CxlMemBIRspPacket,
    CxlMemBISnpPacket,
    CxlMemMemDataPacket,
    CxlMemCmpPacket,
)
from packet_constants import (
    CXL_CACHE_D2HREQ_OPCODE,
    CXL_CACHE_D2HRSP_OPCODE,
    CXL_CACHE_H2DREQ_OPCODE,
    CXL_CACHE_H2DRSP_OPCODE,
    CXL_CACHE_H2DRSP_CACHE_STATE,
    CXL_MEM_M2SREQ_OPCODE,
    CXL_MEM_M2SRWD_OPCODE,
    CXL_MEM_META_FIELD,
    CXL_MEM_META_VALUE,
    CXL_MEM_M2S_SNP_TYPE,
    CXL_MEM_M2SBIRSP_OPCODE,
    CXL_MEM_S2MBISNP_OPCODE,
)
from new_packet.packet_reader import PacketReader


def instantiate_packets():
    CxlMemBISnpPacket.tag = 0  # ensure static tag starts correctly

    packets = []

    buf = bytes([1] * 128)

    packets.append(SidebandConnectionRequestPacket.create(port_index=1))
    packets.append(CxlIoMemRdPacket.create(addr=0x1000, length=4, req_id=1, tag=2))
    packets.append(CxlIoMemWrPacket.create(addr=0x1000, length=4, data=0xDEADBEEF, req_id=1, tag=2))
    packets.append(CxlIoCfgRdPacket.create(id=0x10, cfg_addr=0x04, size=1, req_id=1, tag=1))
    packets.append(
        CxlIoCfgWrPacket.create(id=0x10, cfg_addr=0x04, size=1, value=0xDE, req_id=1, tag=1)
    )
    packets.append(CxlIoCompletionPacket.create(req_id=0x10, tag=0x1A))
    packets.append(CxlIoCompletionWithDataPacket.create(req_id=0x10, tag=0x1A, data=buf))
    packets.append(
        CxlCacheCacheD2HReqPacket.create(
            addr=0x1000, cache_id=1, opcode=CXL_CACHE_D2HREQ_OPCODE.CACHE_RD_CURR, cqid=0
        )
    )
    packets.append(
        CxlCacheCacheD2HRspPacket.create(uqid=1, opcode=CXL_CACHE_D2HRSP_OPCODE.RSP_I_HIT_I)
    )
    packets.append(CxlCacheCacheD2HDataPacket.create(uqid=1, data=0xDEADBEEF))
    packets.append(
        CxlCacheCacheH2DReqPacket.create(
            addr=0x1000, cache_id=1, opcode=CXL_CACHE_H2DREQ_OPCODE.SNP_DATA
        )
    )
    packets.append(
        CxlCacheCacheH2DRspPacket.create(
            cache_id=1,
            opcode=CXL_CACHE_H2DRSP_OPCODE.WRITE_PULL,
            rsp_data=CXL_CACHE_H2DRSP_CACHE_STATE.EXCLUSIVE,
        )
    )
    packets.append(CxlCacheCacheH2DDataPacket.create(cache_id=1, data=0xBEEF))
    packets.append(CxlMemMemRdPacket.create(addr=0x1000))
    packets.append(CxlMemMemWrPacket.create(addr=0x1000, data=0x12345678))
    packets.append(CxlMemBIRspPacket.create(opcode=CXL_MEM_M2SBIRSP_OPCODE.BIRSP_I))
    packets.append(CxlMemBISnpPacket.create(addr=0x1000, opcode=CXL_MEM_S2MBISNP_OPCODE.BISNP_DATA))
    packets.append(CxlMemMemDataPacket.create(data=buf))
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


def run_benchmarks_on_data_packets(packets, data, iterations=10000):
    print("=" * 80)
    print("Running benchmarks on packets supporting get_data()/set_data()")
    print("=" * 80)
    for pkt in packets:
        pkt_type = pkt.__class__.__name__
        if not all(hasattr(pkt, attr) for attr in ("get_data", "set_data")):
            continue
        print(f"\n--- [Packet Type: {pkt_type}] ---\n")
        try:
            benchmark_packet_io(pkt, data, iterations)
        except Exception as e:
            print(f"[ERROR] Benchmark failed for {pkt_type}: {e}")

    print("Benchmark done. Proceeding to reader test...", flush=True)


def main():
    data = bytes([1] * 128)

    print(f"Python: {platform.python_version()}, PID: {os.getpid()}")
    print("Initial sanity benchmark with CxlIoMemWrPacket:")
    wr_pkt = CxlIoMemWrPacket.create(addr=0x100, length=len(data), data=data)
    wr_pkt.mreq_header.req_id = 0x4341
    wr_pkt.mreq_header.tag = 0x78
    benchmark_packet_io(wr_pkt, data, iterations=100000)

    print("Sanity check: CxlIoMemRdPacket:")
    rd_pkt = CxlIoMemRdPacket.create(addr=0x100, length=4, req_id=0x1234, tag=0x56)
    handle_rd_packet(rd_pkt)

    print("Write Packet Data:")
    wr_pkt.set_data(data[:10])
    handle_wr_packet(wr_pkt)

    packets = instantiate_packets()
    run_benchmarks_on_data_packets(packets, data, iterations=10000)
    test_packet_reader()


class MockStreamReader:
    def __init__(self, data: bytes = b""):
        self._buffer = None
        self._read_event = asyncio.Event()

    def feed(self, data: bytes):
        self._buffer = bytearray(data)
        self._read_event.set()

    async def read(self, n=-1):
        while not self._buffer:
            self._read_event.clear()
            await self._read_event.wait()

        if n == -1 or n > len(self._buffer):
            n = len(self._buffer)
        data = self._buffer[:n]
        del self._buffer[:n]
        return bytes(data)


async def simulate_packet_reader(packets):
    reader = MockStreamReader()
    packet_reader = PacketReader(reader, label="TestReader")

    results = []
    try:
        for pkt in packets:
            reader.feed(bytes(pkt))
            received = await packet_reader.get_packet()
            print(f"[RECEIVED] {received.__class__.__name__}")
            results.append(received)
            if received.__class__.__name__ == "CxlIoMemWrPacket":
                print(f"{bytes(received.get_data())}, {bytes(received)}")
    except Exception as e:
        print(f"[END] PacketReader stopped: {e}")
    return results


def test_packet_reader():
    packets = instantiate_packets()
    asyncio.run(simulate_packet_reader(packets))


if __name__ == "__main__":
    main()
