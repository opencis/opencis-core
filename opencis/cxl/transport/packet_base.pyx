"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from libc.stdint cimport uintptr_t

cdef class PacketBuffer:
    def __cinit__(self, input_buf=None):
        self._buf = bytearray(200)
        if input_buf is not None:
            self._buf = input_buf[:]
            #print("cinit _buf", bytearray(self._buf))


    cpdef unsigned long long read_bits(self, int start_bit, int width):
        cdef int i, byte_index, bit_offset
        cdef unsigned long long result = 0
        for i in range(width):
            byte_index = (start_bit + i) // 8
            bit_offset = (start_bit + i) % 8
            #print("byte:",byte_index, "bits:",bit_offset )
            bit = (self._buf[byte_index] >> bit_offset) & 1
            result |= (bit << i)
        return result

    cpdef void write_bits(self, int start_bit, int width, unsigned long long value):
        cdef int i, byte_index, bit_offset
        for i in range(width):
            byte_index = (start_bit + i) // 8
            bit_offset = (start_bit + i) % 8
            if (value >> i) & 1:
                self._buf[byte_index] |= (1 << bit_offset)
            else:
                self._buf[byte_index] &= ~(1 << bit_offset)

    cpdef unsigned char[::1] get_bytes(self, int offset, int length):
        return self._buf[offset:offset + length]

    cpdef void set_bytes(self, int offset, object data):
        cdef const unsigned char[::1] view = data
        cdef int i
        for i in range(view.shape[0]):
            print("self._buf[offset + i]", self._buf[offset + i])
            print("view[i]", view[i])
            self._buf[offset + i] = view[i]

    cpdef bytes to_bytes(self):
        return bytes(self._buf[:self.get_size()])

    def __len__(self):
        return self.get_size()

    cpdef int get_byte_offset(self, PacketBuffer other):
        cdef uintptr_t base_ptr = <uintptr_t>&self._buf[0]
        cdef uintptr_t other_ptr = <uintptr_t>&other._buf[0]
        return <int>(other_ptr - base_ptr)

    @property
    def buf(self):
        return self._buf