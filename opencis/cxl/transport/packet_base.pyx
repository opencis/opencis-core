"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from libc.stdint cimport uintptr_t
from libc.string cimport memcpy
from collections import deque


_pool = deque([bytearray(200) for _ in range(500000)], maxlen=500000)


cdef class PacketBuffer:
    def __cinit__(self, buf=None):
        if buf is None:
            try:
                b = _pool.popleft()
            except IndexError:
                b = bytearray(200)
        else:
            b = bytearray(buf)
        self._buf = b

    def __dealloc__(self):
        try:
            _pool.append(self._buf.base)
        except Exception:
            pass

    cpdef unsigned long long read_bits(self, int start_bit, int width):
        cdef unsigned char* buf = &self._buf[0]
        cdef int byte_off = start_bit >> 3
        cdef int bit_off  = start_bit & 7

        # fast-path: field fits in one byte
        if width <= 8 and bit_off + width <= 8:
            return (buf[byte_off] >> bit_off) & ((1 << width) - 1)

        cdef unsigned long long result = 0
        cdef int i, byte_index, bit_offset
        for i in range(width):
            byte_index = (start_bit + i) >> 3
            bit_offset = (start_bit + i) & 7
            if (buf[byte_index] >> bit_offset) & 1:
                result |= 1ULL << i
        return result

    cpdef void write_bits(self, int start_bit, int width,
                        unsigned long long value):
        cdef unsigned char* buf = &self._buf[0]
        cdef int byte_off = start_bit >> 3
        cdef int bit_off  = start_bit & 7
        cdef unsigned char mask

        # fast-path: field fits in one byte
        if width <= 8 and bit_off + width <= 8:
            mask = ((1 << width) - 1) << bit_off
            buf[byte_off] = (buf[byte_off] & ~mask) | \
                            (((<unsigned char>value) << bit_off) & mask)
            return

        cdef int i, byte_index, bit_offset
        for i in range(width):
            byte_index = (start_bit + i) >> 3
            bit_offset = (start_bit + i) & 7
            if (value >> i) & 1:
                buf[byte_index] |= 1 << bit_offset
            else:
                buf[byte_index] &= ~(1 << bit_offset)

    cpdef unsigned char[::1] get_bytes(self, int offset, int length):
        return self._buf[offset:offset + length]

    cpdef void set_bytes(self, int offset, object data):
        cdef const unsigned char[::1] view = data
        cdef int i
        for i in range(view.shape[0]):
            self._buf[offset + i] = view[i]

    cpdef bytes to_bytes(self):
        return bytes(self._buf[:self.get_size()])

    def __len__(self):
        return self.get_size()

    cpdef int get_byte_offset(self, object other):
        cdef unsigned char[::1] self_buf = self._buf
        cdef unsigned char[::1] other_buf
        try:
            other_buf = other.buf
        except AttributeError:
            raise TypeError("other must have a .buf property returning a memoryview")

        cdef uintptr_t base_ptr  = <uintptr_t>&self_buf[0]
        cdef uintptr_t other_ptr = <uintptr_t>&other_buf[0]
        return <int>(other_ptr - base_ptr)

    @property
    def buf(self):
        return self._buf


cdef class HeaderBuffer:
    cpdef unsigned long long read_bits(self, int start_bit, int width):
        cdef unsigned char* buf = &self._buf[0]
        cdef int byte_off = start_bit >> 3
        cdef int bit_off  = start_bit & 7

        # fast-path: field fits in one byte
        if width <= 8 and bit_off + width <= 8:
            return (buf[byte_off] >> bit_off) & ((1 << width) - 1)

        cdef unsigned long long result = 0
        cdef int i, byte_index, bit_offset
        for i in range(width):
            byte_index = (start_bit + i) >> 3
            bit_offset = (start_bit + i) & 7
            if (buf[byte_index] >> bit_offset) & 1:
                result |= 1ULL << i
        return result

    cpdef void write_bits(self, int start_bit, int width,
                        unsigned long long value):
        cdef unsigned char* buf = &self._buf[0]
        cdef int byte_off = start_bit >> 3
        cdef int bit_off  = start_bit & 7
        cdef unsigned char mask          # ← declare before any code that runs

        # fast-path: field fits in one byte
        if width <= 8 and bit_off + width <= 8:
            mask = ((1 << width) - 1) << bit_off
            buf[byte_off] = (buf[byte_off] & ~mask) | \
                            (((<unsigned char>value) << bit_off) & mask)
            return

        cdef int i, byte_index, bit_offset
        for i in range(width):
            byte_index = (start_bit + i) >> 3
            bit_offset = (start_bit + i) & 7
            if (value >> i) & 1:
                buf[byte_index] |= 1 << bit_offset
            else:
                buf[byte_index] &= ~(1 << bit_offset)

    cpdef unsigned char[::1] get_bytes(self, int offset, int length):
        return self._buf[offset:offset + length]

    cpdef bytes to_bytes(self):
        return bytes(self._buf[:self.get_size()])

    def __len__(self):
        return self.get_size()

    cpdef int get_byte_offset(self, object other):
        cdef unsigned char[::1] self_buf = self._buf
        cdef unsigned char[::1] other_buf
        try:
            other_buf = other.buf
        except AttributeError:
            raise TypeError("other must have a .buf property returning a memoryview")

        cdef uintptr_t base_ptr  = <uintptr_t>&self_buf[0]
        cdef uintptr_t other_ptr = <uintptr_t>&other_buf[0]
        return <int>(other_ptr - base_ptr)

    @property
    def buf(self):
        return self._buf