# packet_base.pyx

cdef class PacketBuffer:
    def __cinit__(self, unsigned char[::1] input_buf):
        self.buf = input_buf  # buf is declared in .pxd

    cpdef int get_size(self):
        return self.buf.shape[0]

    cpdef unsigned long long read_bits(self, int start_bit, int width):
        cdef unsigned long long result = 0
        cdef int i, byte_index, bit_offset
        for i in range(start_bit, start_bit + width):
            byte_index = i // 8
            bit_offset = i % 8
            if self.buf[byte_index] & (1 << bit_offset):
                result |= 1 << (i - start_bit)
        return result

    cpdef void write_bits(self, int start_bit, int width, unsigned long long value):
        cdef int i, byte_index, bit_offset
        for i in range(start_bit, start_bit + width):
            byte_index = i // 8
            bit_offset = i % 8
            if value & (1 << (i - start_bit)):
                self.buf[byte_index] |= (1 << bit_offset)
            else:
                self.buf[byte_index] &= ~(1 << bit_offset)

    cpdef unsigned char[::1] get_bytes(self, int offset, int length):
        return self.buf[offset:offset + length]

    cpdef void set_bytes(self, int offset, unsigned char[::1] data):
        cdef int i
        for i in range(data.shape[0]):
            self.buf[offset + i] = data[i]
