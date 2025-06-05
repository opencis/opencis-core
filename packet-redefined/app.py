import numpy as np
from transaction import CxlIoMemRdPacket, CxlIoMemWrPacket



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


def main():
    buf_rd = np.zeros(24, dtype=np.uint8)
    rd_pkt = CxlIoMemRdPacket(buf_rd)
    rd_pkt.mreq_header.req_id = 0x1234
    rd_pkt.mreq_header.tag = 0x56
    rd_pkt.mreq_header.addr_upper = 0xFFFFFFFFABCDEFBA

    handle_rd_packet(rd_pkt)

    buf_wr = np.zeros(40, dtype=np.uint8)
    wr_pkt = CxlIoMemWrPacket(buf_wr)
    wr_pkt.mreq_header.req_id = 0x4341
    wr_pkt.mreq_header.tag = 0x78
    wr_pkt.mreq_header.addr_upper = 0xFFFFFFFF12345678
    print(f"pre: {wr_pkt.get_size()}")
    data = np.array(list(b"Hello World"), dtype=np.uint8)
    wr_pkt.set_data(data)
    print(f"post: {wr_pkt.get_size()}")
    handle_wr_packet(wr_pkt)

    print(f"pre: {wr_pkt.get_size()}")
    data = np.array(list(b"Hello"), dtype=np.uint8)
    wr_pkt.set_data(data)
    print(f"post: {wr_pkt.get_size()}")
    handle_wr_packet(wr_pkt)


if __name__ == "__main__":
    main()
