"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

cdef class PacketBuffer:
    cdef unsigned char[::1] _buf
    cdef int _data_length
    cpdef unsigned long long read_bits(self, int start_bit, int width)
    cpdef void write_bits(self, int start_bit, int width, unsigned long long value)
    cpdef unsigned char[::1] get_bytes(self, int offset, int length)
    cpdef void set_bytes(self, int offset, object data)
    cpdef bytes to_bytes(self)
    cpdef int get_byte_offset(self, object other)


cdef class HeaderBuffer:
    cdef unsigned char[::1] _buf
    cpdef unsigned long long read_bits(self, int start_bit, int width)
    cpdef void write_bits(self, int start_bit, int width, unsigned long long value)
    cpdef unsigned char[::1] get_bytes(self, int offset, int length)
    cpdef bytes to_bytes(self)
    cpdef int get_byte_offset(self, object other)

