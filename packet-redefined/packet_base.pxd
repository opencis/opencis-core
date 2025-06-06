# packet_base.pxd

cdef class PacketBuffer:
    cdef unsigned char[::1] buf
    cpdef unsigned long long read_bits(self, int start_bit, int width)
    cpdef void write_bits(self, int start_bit, int width, unsigned long long value)
    cpdef unsigned char[::1] get_bytes(self, int offset, int length)
    cpdef void set_bytes(self, int offset, unsigned char[::1] data)
    cpdef bytes to_bytes(self)
