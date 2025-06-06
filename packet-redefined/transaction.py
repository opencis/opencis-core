from packet_structs import RawCxlIoMemReqPacket


class CxlIoMemReqPacket(RawCxlIoMemReqPacket):
    def fill(self, addr: int, length: int, req_id: int, tag: int):
        address_offset = addr % 4
        length_dword = (address_offset + length + 3) // 4

        self.system_header.payload_type = 0x42  # example
        self.io_header.length_upper = length_dword & 0x300
        self.io_header.length_lower = length_dword & 0xFF
        self.mreq_header.req_id = req_id
        self.mreq_header.tag = tag

        bytes_enabled = (1 << length) - 1
        bytes_enabled_with_offset = bytes_enabled << address_offset
        self.mreq_header.first_dw_be = bytes_enabled_with_offset & 0xF
        self.mreq_header.last_dw_be = (
            (bytes_enabled_with_offset >> ((length_dword - 1) * 4)) & 0xF if length_dword > 1 else 0
        )

        addr_upper_bytes = (addr >> 8).to_bytes(7, byteorder="big")
        self.mreq_header.addr_upper = int.from_bytes(addr_upper_bytes, byteorder="little")
        self.mreq_header.addr_lower = (addr & 0xFF) >> 2

    def get_address(self) -> int:
        addr = (
            int.from_bytes(
                self.mreq_header.addr_upper.to_bytes(7, byteorder="little"), byteorder="big"
            )
            << 8
        )
        addr |= self.mreq_header.addr_lower << 2
        return addr

    def get_data_size(self) -> int:
        return ((self.io_header.length_upper << 8) | self.io_header.length_lower) * 4


class CxlIoMemRdPacket(CxlIoMemReqPacket):
    @classmethod
    def create(cls, addr: int, length: int, req_id: int = 0, tag: int = 0, ld_id: int = 0):
        pkt = cls()
        pkt.fill(addr, length, req_id, tag)
        pkt.io_header.fmt_type = 0x0  # CXL_IO_FMT_TYPE.MRD_64B
        pkt.tlp_prefix.ld_id = ld_id
        pkt.system_header.payload_length = pkt.get_data_size() // 4
        return pkt


class CxlIoMemWrPacket(CxlIoMemReqPacket):
    @classmethod
    def create(cls, addr: int, data: bytes, req_id: int = 0, tag: int = 0, ld_id: int = 0):
        pkt = cls()
        pkt.set_data(data)
        pkt.fill(addr, len(data), req_id, tag)
        pkt.io_header.fmt_type = 0x1  # CXL_IO_FMT_TYPE.MWR_64B
        pkt.tlp_prefix.ld_id = ld_id
        pkt.system_header.payload_length = pkt.get_size() // 4
        return pkt
