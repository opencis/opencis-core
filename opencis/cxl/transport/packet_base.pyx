"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from libc.stdint cimport uintptr_t
from libc.string cimport memcpy

cdef class PacketBuffer:
    def __cinit__(self, input_buf=None):
        self._buf = bytearray(200)
        if input_buf is not None:
            self._buf = input_buf[:]
            #print("cinit _buf", bytearray(self._buf))


    cpdef unsigned long long read_bits(self, int start_bit, int width):
        cdef unsigned char *buf = &self._buf[0]
        cdef unsigned long long res = 0
        cdef int byte = start_bit >> 3, bit = start_bit & 7, bits = 0
        cdef int n, i

        # head (unaligned start)
        if bit:
            n = min(8 - bit, width)
            for i in range(n):
                res |= ((buf[byte] >> (bit + i)) & 1) << bits
                bits += 1
            byte += 1
            width -= n
            bit = 0

        # middle (full bytes)
        n = width >> 3
        for i in range(n):
            res |= (<unsigned long long>buf[byte]) << bits
            byte += 1
            bits += 8
        width -= n << 3

        # tail (remaining bits)
        for i in range(width):
            res |= ((buf[byte] >> i) & 1) << bits
            bits += 1

        return res


    cpdef void write_bits(self, int start_bit, int width, unsigned long long v):
        cdef unsigned char *buf = &self._buf[0]
        cdef int byte = start_bit >> 3, bit = start_bit & 7, bits = 0
        cdef int n, i
        cdef unsigned char m, inv

        # head (unaligned start)
        if bit:
            n = min(8 - bit, width)
            for i in range(n):
                m   = 1 << (bit + i)
                inv = <unsigned char>(0xFF ^ m)
                if (v >> bits) & 1:
                    buf[byte] |= m
                else:
                    buf[byte] &= inv
                bits += 1
            byte += 1
            width -= n
            bit = 0

        # middle (full bytes)
        n = width >> 3
        for i in range(n):
            buf[byte] = <unsigned char>((v >> bits) & 0xFF)
            byte += 1
            bits += 8
        width -= n << 3

        # tail (remaining bits)
        for i in range(width):
            m   = 1 << i
            inv = <unsigned char>(0xFF ^ m)
            if (v >> bits) & 1:
                buf[byte] |= m
            else:
                buf[byte] &= inv
            bits += 1


























    cpdef unsigned char[::1] get_bytes(self, int offset, int length):
        return self._buf[offset:offset + length]

    cpdef void set_bytes(self, int offset, object data):
        cdef const unsigned char[::1] view = data
        cdef int i
        for i in range(view.shape[0]):
            #print("self._buf[offset + i]", self._buf[offset + i])
            #print("view[i]", view[i])
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