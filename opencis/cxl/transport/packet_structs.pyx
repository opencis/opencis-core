
# cython: language_level=3, boundscheck=False, wraparound=False, no_gc=True, infer_types=True

from libc.stdint cimport uint8_t, uint16_t, uint32_t, uint64_t
from libc.string  cimport memcpy, memset
from cpython.bytes cimport PyBytes_FromStringAndSize
from cpython.ref cimport Py_INCREF, Py_DECREF
from cpython.object cimport PyObject


cdef unsigned long long _read_bits(unsigned char* p, int start_bit, int width) nogil:
    cdef unsigned char* buf = p
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


cdef void _write_bits(unsigned char* p, int start_bit, int width,
                    unsigned long long value) noexcept nogil:
    cdef unsigned char* buf = p
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


# ───── Pooling structs ────────────────────────────────────────────────
ctypedef enum:
    MAX_PACKET_SIZE = 200
    POOL_SIZE = 4


cdef struct PoolStruct:
    PyObject *buf[POOL_SIZE]
    Py_ssize_t head
    Py_ssize_t tail
    Py_ssize_t count


cdef inline void pool_push(PoolStruct *p, PyObject *obj) noexcept nogil:
    if p.count == POOL_SIZE:
        with gil:
            Py_DECREF(<object>obj)
        return

    with gil:
        Py_INCREF(<object>obj)

    p.buf[p.tail] = obj
    p.tail    = (p.tail + 1) & (POOL_SIZE - 1)
    p.count  += 1


cdef inline PyObject* pool_pop(PoolStruct *p) noexcept nogil:
    if p.count == 0:
        return NULL

    cdef PyObject *obj = p.buf[p.head]
    p.buf[p.head]    = NULL
    p.head           = (p.head + 1) & (POOL_SIZE - 1)
    p.count         -= 1

    # caller owns the reference held by the pool
    with gil:
        Py_INCREF(<object>obj)
    return obj

# ───────────────────────────────────────────────────────────────────────────
#    SystemHeader  (2 bytes)
# ───────────────────────────────────────────────────────────────────────────
cdef class SystemHeader:
    __slots__ = ('_p')
    cdef uint8_t* _p

    def __cinit__(self):
        self._p = <uint8_t*>NULL  # NULL until first attach()

    cdef void attach(self, uint8_t* p) noexcept nogil:
        self._p = p

    # ───── payload_type : bits 0-3 (4 b) ───────────────────────────────────
    cdef inline uint8_t _get_payload_type(self) noexcept nogil:
        return self._p[0] & 0x0F

    cdef inline void _set_payload_type(self, uint8_t v) noexcept nogil:
        self._p[0] = (self._p[0] & 0xF0) | (v & 0x0F)

    @property
    def payload_type(self):
        return self._get_payload_type()

    @payload_type.setter
    def payload_type(self, v):
        self._set_payload_type(<uint8_t>v)

    # ───── payload_length : bits 4-15 (12 b) ───────────────────────────────
    cdef inline uint16_t _get_payload_length(self) noexcept nogil:
        return <uint16_t>_read_bits(self._p, 4, 12)

    cdef inline void _set_payload_length(self, uint16_t v) noexcept nogil:
        _write_bits(self._p, 4, 12, v)

    @property
    def payload_length(self):
        return self._get_payload_length()

    @payload_length.setter
    def payload_length(self, v):
        self._set_payload_length(<uint16_t>v)

    # ───── misc helpers ────────────────────────────────────────────────────
    @classmethod
    def get_size(cls):
        return 2

    def __len__(self):
        return 2

    def __bytes__(self):
        return PyBytes_FromStringAndSize(<char*>self._p, 2)

# ───────────────────────────────────────────────────────────────────────────
#    SidebandHeader  (1 bytes)
# ───────────────────────────────────────────────────────────────────────────
cdef class SidebandHeader:
    __slots__ = ('_p')
    cdef uint8_t* _p

    def __cinit__(self):
        self._p = <uint8_t*>NULL  # NULL until first attach()

    cdef void attach(self, uint8_t* p) noexcept nogil:
        self._p = p

    # ───── type : bits 0-7 (8 b) ───────────────────────────────────────────
    cdef inline uint8_t _get_type(self) noexcept nogil:
        return self._p[0]

    cdef inline void _set_type(self, uint8_t v) noexcept nogil:
        self._p[0] = v

    @property
    def type(self):
        return self._get_type()

    @type.setter
    def type(self, v):
        self._set_type(<uint8_t>v)

    # ───── misc helpers ────────────────────────────────────────────────────
    @classmethod
    def get_size(cls):
        return 1

    def __len__(self):
        return 1

    def __bytes__(self):
        return PyBytes_FromStringAndSize(<char*>self._p, 1)

# ───────────────────────────────────────────────────────────────────────────
#    TlpPrefix  (4 bytes)
# ───────────────────────────────────────────────────────────────────────────
cdef class TlpPrefix:
    __slots__ = ('_p')
    cdef uint8_t* _p

    def __cinit__(self):
        self._p = <uint8_t*>NULL  # NULL until first attach()

    cdef void attach(self, uint8_t* p) noexcept nogil:
        self._p = p

    # ───── pcie_base_spec_defined : bits 0-7 (8 b) ─────────────────────────
    cdef inline uint8_t _get_pcie_base_spec_defined(self) noexcept nogil:
        return self._p[0]

    cdef inline void _set_pcie_base_spec_defined(self, uint8_t v) noexcept nogil:
        self._p[0] = v

    @property
    def pcie_base_spec_defined(self):
        return self._get_pcie_base_spec_defined()

    @pcie_base_spec_defined.setter
    def pcie_base_spec_defined(self, v):
        self._set_pcie_base_spec_defined(<uint8_t>v)

    # ───── ld_id : bits 8-23 (16 b) ────────────────────────────────────────
    cdef inline uint16_t _get_ld_id(self) noexcept nogil:
        return <uint16_t>_read_bits(self._p, 8, 16)

    cdef inline void _set_ld_id(self, uint16_t v) noexcept nogil:
        _write_bits(self._p, 8, 16, v)

    @property
    def ld_id(self):
        return self._get_ld_id()

    @ld_id.setter
    def ld_id(self, v):
        self._set_ld_id(<uint16_t>v)

    # ───── reserved : bits 24-31 (8 b) ─────────────────────────────────────
    cdef inline uint8_t _get_reserved(self) noexcept nogil:
        return self._p[3]

    cdef inline void _set_reserved(self, uint8_t v) noexcept nogil:
        self._p[3] = v

    @property
    def reserved(self):
        return self._get_reserved()

    @reserved.setter
    def reserved(self, v):
        self._set_reserved(<uint8_t>v)

    # ───── misc helpers ────────────────────────────────────────────────────
    @classmethod
    def get_size(cls):
        return 4

    def __len__(self):
        return 4

    def __bytes__(self):
        return PyBytes_FromStringAndSize(<char*>self._p, 4)

# ───────────────────────────────────────────────────────────────────────────
#    CxlIoHeader  (4 bytes)
# ───────────────────────────────────────────────────────────────────────────
cdef class CxlIoHeader:
    __slots__ = ('_p')
    cdef uint8_t* _p

    def __cinit__(self):
        self._p = <uint8_t*>NULL  # NULL until first attach()

    cdef void attach(self, uint8_t* p) noexcept nogil:
        self._p = p

    # ───── fmt_type : bits 0-7 (8 b) ───────────────────────────────────────
    cdef inline uint8_t _get_fmt_type(self) noexcept nogil:
        return self._p[0]

    cdef inline void _set_fmt_type(self, uint8_t v) noexcept nogil:
        self._p[0] = v

    @property
    def fmt_type(self):
        return self._get_fmt_type()

    @fmt_type.setter
    def fmt_type(self, v):
        self._set_fmt_type(<uint8_t>v)

    # ───── th : bit 8 (1 b) ────────────────────────────────────────────────
    cdef inline uint8_t _get_th(self) noexcept nogil:
        return self._p[1] & 0x01

    cdef inline void _set_th(self, uint8_t v) noexcept nogil:
        self._p[1] = (self._p[1] & 0xFE) | (v & 0x01)

    @property
    def th(self):
        return self._get_th()

    @th.setter
    def th(self, v):
        self._set_th(<uint8_t>v)

    # ───── rsvd : bit 9 (1 b) ──────────────────────────────────────────────
    cdef inline uint8_t _get_rsvd(self) noexcept nogil:
        return (self._p[1] >> 1) & 0x01

    cdef inline void _set_rsvd(self, uint8_t v) noexcept nogil:
        self._p[1] = (self._p[1] & 0xFD) | ((v & 0x01) << 1)

    @property
    def rsvd(self):
        return self._get_rsvd()

    @rsvd.setter
    def rsvd(self, v):
        self._set_rsvd(<uint8_t>v)

    # ───── attr_b2 : bit 10 (1 b) ──────────────────────────────────────────
    cdef inline uint8_t _get_attr_b2(self) noexcept nogil:
        return (self._p[1] >> 2) & 0x01

    cdef inline void _set_attr_b2(self, uint8_t v) noexcept nogil:
        self._p[1] = (self._p[1] & 0xFB) | ((v & 0x01) << 2)

    @property
    def attr_b2(self):
        return self._get_attr_b2()

    @attr_b2.setter
    def attr_b2(self, v):
        self._set_attr_b2(<uint8_t>v)

    # ───── t8 : bit 11 (1 b) ───────────────────────────────────────────────
    cdef inline uint8_t _get_t8(self) noexcept nogil:
        return (self._p[1] >> 3) & 0x01

    cdef inline void _set_t8(self, uint8_t v) noexcept nogil:
        self._p[1] = (self._p[1] & 0xF7) | ((v & 0x01) << 3)

    @property
    def t8(self):
        return self._get_t8()

    @t8.setter
    def t8(self, v):
        self._set_t8(<uint8_t>v)

    # ───── tc : bits 12-14 (3 b) ───────────────────────────────────────────
    cdef inline uint8_t _get_tc(self) noexcept nogil:
        return (self._p[1] >> 4) & 0x07

    cdef inline void _set_tc(self, uint8_t v) noexcept nogil:
        self._p[1] = (self._p[1] & 0x8F) | ((v & 0x07) << 4)

    @property
    def tc(self):
        return self._get_tc()

    @tc.setter
    def tc(self, v):
        self._set_tc(<uint8_t>v)

    # ───── t9 : bit 15 (1 b) ───────────────────────────────────────────────
    cdef inline uint8_t _get_t9(self) noexcept nogil:
        return (self._p[1] >> 7) & 0x01

    cdef inline void _set_t9(self, uint8_t v) noexcept nogil:
        self._p[1] = (self._p[1] & 0x7F) | ((v & 0x01) << 7)

    @property
    def t9(self):
        return self._get_t9()

    @t9.setter
    def t9(self, v):
        self._set_t9(<uint8_t>v)

    # ───── length_upper : bits 16-17 (2 b) ─────────────────────────────────
    cdef inline uint8_t _get_length_upper(self) noexcept nogil:
        return self._p[2] & 0x03

    cdef inline void _set_length_upper(self, uint8_t v) noexcept nogil:
        self._p[2] = (self._p[2] & 0xFC) | (v & 0x03)

    @property
    def length_upper(self):
        return self._get_length_upper()

    @length_upper.setter
    def length_upper(self, v):
        self._set_length_upper(<uint8_t>v)

    # ───── at : bits 18-19 (2 b) ───────────────────────────────────────────
    cdef inline uint8_t _get_at(self) noexcept nogil:
        return (self._p[2] >> 2) & 0x03

    cdef inline void _set_at(self, uint8_t v) noexcept nogil:
        self._p[2] = (self._p[2] & 0xF3) | ((v & 0x03) << 2)

    @property
    def at(self):
        return self._get_at()

    @at.setter
    def at(self, v):
        self._set_at(<uint8_t>v)

    # ───── attr : bits 20-21 (2 b) ─────────────────────────────────────────
    cdef inline uint8_t _get_attr(self) noexcept nogil:
        return (self._p[2] >> 4) & 0x03

    cdef inline void _set_attr(self, uint8_t v) noexcept nogil:
        self._p[2] = (self._p[2] & 0xCF) | ((v & 0x03) << 4)

    @property
    def attr(self):
        return self._get_attr()

    @attr.setter
    def attr(self, v):
        self._set_attr(<uint8_t>v)

    # ───── ep : bit 22 (1 b) ───────────────────────────────────────────────
    cdef inline uint8_t _get_ep(self) noexcept nogil:
        return (self._p[2] >> 6) & 0x01

    cdef inline void _set_ep(self, uint8_t v) noexcept nogil:
        self._p[2] = (self._p[2] & 0xBF) | ((v & 0x01) << 6)

    @property
    def ep(self):
        return self._get_ep()

    @ep.setter
    def ep(self, v):
        self._set_ep(<uint8_t>v)

    # ───── td : bit 23 (1 b) ───────────────────────────────────────────────
    cdef inline uint8_t _get_td(self) noexcept nogil:
        return (self._p[2] >> 7) & 0x01

    cdef inline void _set_td(self, uint8_t v) noexcept nogil:
        self._p[2] = (self._p[2] & 0x7F) | ((v & 0x01) << 7)

    @property
    def td(self):
        return self._get_td()

    @td.setter
    def td(self, v):
        self._set_td(<uint8_t>v)

    # ───── length_lower : bits 24-31 (8 b) ─────────────────────────────────
    cdef inline uint8_t _get_length_lower(self) noexcept nogil:
        return self._p[3]

    cdef inline void _set_length_lower(self, uint8_t v) noexcept nogil:
        self._p[3] = v

    @property
    def length_lower(self):
        return self._get_length_lower()

    @length_lower.setter
    def length_lower(self, v):
        self._set_length_lower(<uint8_t>v)

    # ───── misc helpers ────────────────────────────────────────────────────
    @classmethod
    def get_size(cls):
        return 4

    def __len__(self):
        return 4

    def __bytes__(self):
        return PyBytes_FromStringAndSize(<char*>self._p, 4)

# ───────────────────────────────────────────────────────────────────────────
#    CxlIoMReqHeader  (12 bytes)
# ───────────────────────────────────────────────────────────────────────────
cdef class CxlIoMReqHeader:
    __slots__ = ('_p')
    cdef uint8_t* _p

    def __cinit__(self):
        self._p = <uint8_t*>NULL  # NULL until first attach()

    cdef void attach(self, uint8_t* p) noexcept nogil:
        self._p = p

    # ───── req_id : bits 0-15 (16 b) ───────────────────────────────────────
    cdef inline uint16_t _get_req_id(self) noexcept nogil:
        return <uint16_t>_read_bits(self._p, 0, 16)

    cdef inline void _set_req_id(self, uint16_t v) noexcept nogil:
        _write_bits(self._p, 0, 16, v)

    @property
    def req_id(self):
        return self._get_req_id()

    @req_id.setter
    def req_id(self, v):
        self._set_req_id(<uint16_t>v)

    # ───── tag : bits 16-23 (8 b) ──────────────────────────────────────────
    cdef inline uint8_t _get_tag(self) noexcept nogil:
        return self._p[2]

    cdef inline void _set_tag(self, uint8_t v) noexcept nogil:
        self._p[2] = v

    @property
    def tag(self):
        return self._get_tag()

    @tag.setter
    def tag(self, v):
        self._set_tag(<uint8_t>v)

    # ───── first_dw_be : bits 24-27 (4 b) ──────────────────────────────────
    cdef inline uint8_t _get_first_dw_be(self) noexcept nogil:
        return self._p[3] & 0x0F

    cdef inline void _set_first_dw_be(self, uint8_t v) noexcept nogil:
        self._p[3] = (self._p[3] & 0xF0) | (v & 0x0F)

    @property
    def first_dw_be(self):
        return self._get_first_dw_be()

    @first_dw_be.setter
    def first_dw_be(self, v):
        self._set_first_dw_be(<uint8_t>v)

    # ───── last_dw_be : bits 28-31 (4 b) ───────────────────────────────────
    cdef inline uint8_t _get_last_dw_be(self) noexcept nogil:
        return (self._p[3] >> 4) & 0x0F

    cdef inline void _set_last_dw_be(self, uint8_t v) noexcept nogil:
        self._p[3] = (self._p[3] & 0x0F) | ((v & 0x0F) << 4)

    @property
    def last_dw_be(self):
        return self._get_last_dw_be()

    @last_dw_be.setter
    def last_dw_be(self, v):
        self._set_last_dw_be(<uint8_t>v)

    # ───── addr_upper : bits 32-87 (56 b) ──────────────────────────────────
    cdef inline uint64_t _get_addr_upper(self) noexcept nogil:
        return <uint64_t>_read_bits(self._p, 32, 56)

    cdef inline void _set_addr_upper(self, uint64_t v) noexcept nogil:
        _write_bits(self._p, 32, 56, v)

    @property
    def addr_upper(self):
        return self._get_addr_upper()

    @addr_upper.setter
    def addr_upper(self, v):
        self._set_addr_upper(<uint64_t>v)

    # ───── rsvd : bits 88-89 (2 b) ─────────────────────────────────────────
    cdef inline uint8_t _get_rsvd(self) noexcept nogil:
        return self._p[11] & 0x03

    cdef inline void _set_rsvd(self, uint8_t v) noexcept nogil:
        self._p[11] = (self._p[11] & 0xFC) | (v & 0x03)

    @property
    def rsvd(self):
        return self._get_rsvd()

    @rsvd.setter
    def rsvd(self, v):
        self._set_rsvd(<uint8_t>v)

    # ───── addr_lower : bits 90-95 (6 b) ───────────────────────────────────
    cdef inline uint8_t _get_addr_lower(self) noexcept nogil:
        return (self._p[11] >> 2) & 0x3F

    cdef inline void _set_addr_lower(self, uint8_t v) noexcept nogil:
        self._p[11] = (self._p[11] & 0x03) | ((v & 0x3F) << 2)

    @property
    def addr_lower(self):
        return self._get_addr_lower()

    @addr_lower.setter
    def addr_lower(self, v):
        self._set_addr_lower(<uint8_t>v)

    # ───── misc helpers ────────────────────────────────────────────────────
    @classmethod
    def get_size(cls):
        return 12

    def __len__(self):
        return 12

    def __bytes__(self):
        return PyBytes_FromStringAndSize(<char*>self._p, 12)

# ───────────────────────────────────────────────────────────────────────────
#    CxlIoCfgReqHeader  (8 bytes)
# ───────────────────────────────────────────────────────────────────────────
cdef class CxlIoCfgReqHeader:
    __slots__ = ('_p')
    cdef uint8_t* _p

    def __cinit__(self):
        self._p = <uint8_t*>NULL  # NULL until first attach()

    cdef void attach(self, uint8_t* p) noexcept nogil:
        self._p = p

    # ───── req_id : bits 0-15 (16 b) ───────────────────────────────────────
    cdef inline uint16_t _get_req_id(self) noexcept nogil:
        return <uint16_t>_read_bits(self._p, 0, 16)

    cdef inline void _set_req_id(self, uint16_t v) noexcept nogil:
        _write_bits(self._p, 0, 16, v)

    @property
    def req_id(self):
        return self._get_req_id()

    @req_id.setter
    def req_id(self, v):
        self._set_req_id(<uint16_t>v)

    # ───── tag : bits 16-23 (8 b) ──────────────────────────────────────────
    cdef inline uint8_t _get_tag(self) noexcept nogil:
        return self._p[2]

    cdef inline void _set_tag(self, uint8_t v) noexcept nogil:
        self._p[2] = v

    @property
    def tag(self):
        return self._get_tag()

    @tag.setter
    def tag(self, v):
        self._set_tag(<uint8_t>v)

    # ───── first_dw_be : bits 24-27 (4 b) ──────────────────────────────────
    cdef inline uint8_t _get_first_dw_be(self) noexcept nogil:
        return self._p[3] & 0x0F

    cdef inline void _set_first_dw_be(self, uint8_t v) noexcept nogil:
        self._p[3] = (self._p[3] & 0xF0) | (v & 0x0F)

    @property
    def first_dw_be(self):
        return self._get_first_dw_be()

    @first_dw_be.setter
    def first_dw_be(self, v):
        self._set_first_dw_be(<uint8_t>v)

    # ───── last_dw_be : bits 28-31 (4 b) ───────────────────────────────────
    cdef inline uint8_t _get_last_dw_be(self) noexcept nogil:
        return (self._p[3] >> 4) & 0x0F

    cdef inline void _set_last_dw_be(self, uint8_t v) noexcept nogil:
        self._p[3] = (self._p[3] & 0x0F) | ((v & 0x0F) << 4)

    @property
    def last_dw_be(self):
        return self._get_last_dw_be()

    @last_dw_be.setter
    def last_dw_be(self, v):
        self._set_last_dw_be(<uint8_t>v)

    # ───── dest_id : bits 32-47 (16 b) ─────────────────────────────────────
    cdef inline uint16_t _get_dest_id(self) noexcept nogil:
        return <uint16_t>_read_bits(self._p, 32, 16)

    cdef inline void _set_dest_id(self, uint16_t v) noexcept nogil:
        _write_bits(self._p, 32, 16, v)

    @property
    def dest_id(self):
        return self._get_dest_id()

    @dest_id.setter
    def dest_id(self, v):
        self._set_dest_id(<uint16_t>v)

    # ───── ext_reg_num : bits 48-51 (4 b) ──────────────────────────────────
    cdef inline uint8_t _get_ext_reg_num(self) noexcept nogil:
        return self._p[6] & 0x0F

    cdef inline void _set_ext_reg_num(self, uint8_t v) noexcept nogil:
        self._p[6] = (self._p[6] & 0xF0) | (v & 0x0F)

    @property
    def ext_reg_num(self):
        return self._get_ext_reg_num()

    @ext_reg_num.setter
    def ext_reg_num(self, v):
        self._set_ext_reg_num(<uint8_t>v)

    # ───── rsvd : bits 52-55 (4 b) ─────────────────────────────────────────
    cdef inline uint8_t _get_rsvd(self) noexcept nogil:
        return (self._p[6] >> 4) & 0x0F

    cdef inline void _set_rsvd(self, uint8_t v) noexcept nogil:
        self._p[6] = (self._p[6] & 0x0F) | ((v & 0x0F) << 4)

    @property
    def rsvd(self):
        return self._get_rsvd()

    @rsvd.setter
    def rsvd(self, v):
        self._set_rsvd(<uint8_t>v)

    # ───── r : bits 56-57 (2 b) ────────────────────────────────────────────
    cdef inline uint8_t _get_r(self) noexcept nogil:
        return self._p[7] & 0x03

    cdef inline void _set_r(self, uint8_t v) noexcept nogil:
        self._p[7] = (self._p[7] & 0xFC) | (v & 0x03)

    @property
    def r(self):
        return self._get_r()

    @r.setter
    def r(self, v):
        self._set_r(<uint8_t>v)

    # ───── reg_num : bits 58-63 (6 b) ──────────────────────────────────────
    cdef inline uint8_t _get_reg_num(self) noexcept nogil:
        return (self._p[7] >> 2) & 0x3F

    cdef inline void _set_reg_num(self, uint8_t v) noexcept nogil:
        self._p[7] = (self._p[7] & 0x03) | ((v & 0x3F) << 2)

    @property
    def reg_num(self):
        return self._get_reg_num()

    @reg_num.setter
    def reg_num(self, v):
        self._set_reg_num(<uint8_t>v)

    # ───── misc helpers ────────────────────────────────────────────────────
    @classmethod
    def get_size(cls):
        return 8

    def __len__(self):
        return 8

    def __bytes__(self):
        return PyBytes_FromStringAndSize(<char*>self._p, 8)

# ───────────────────────────────────────────────────────────────────────────
#    CxlIoCompletionHeader  (8 bytes)
# ───────────────────────────────────────────────────────────────────────────
cdef class CxlIoCompletionHeader:
    __slots__ = ('_p')
    cdef uint8_t* _p

    def __cinit__(self):
        self._p = <uint8_t*>NULL  # NULL until first attach()

    cdef void attach(self, uint8_t* p) noexcept nogil:
        self._p = p

    # ───── cpl_id : bits 0-15 (16 b) ───────────────────────────────────────
    cdef inline uint16_t _get_cpl_id(self) noexcept nogil:
        return <uint16_t>_read_bits(self._p, 0, 16)

    cdef inline void _set_cpl_id(self, uint16_t v) noexcept nogil:
        _write_bits(self._p, 0, 16, v)

    @property
    def cpl_id(self):
        return self._get_cpl_id()

    @cpl_id.setter
    def cpl_id(self, v):
        self._set_cpl_id(<uint16_t>v)

    # ───── byte_count_upper : bits 16-19 (4 b) ─────────────────────────────
    cdef inline uint8_t _get_byte_count_upper(self) noexcept nogil:
        return self._p[2] & 0x0F

    cdef inline void _set_byte_count_upper(self, uint8_t v) noexcept nogil:
        self._p[2] = (self._p[2] & 0xF0) | (v & 0x0F)

    @property
    def byte_count_upper(self):
        return self._get_byte_count_upper()

    @byte_count_upper.setter
    def byte_count_upper(self, v):
        self._set_byte_count_upper(<uint8_t>v)

    # ───── bcm : bit 20 (1 b) ──────────────────────────────────────────────
    cdef inline uint8_t _get_bcm(self) noexcept nogil:
        return (self._p[2] >> 4) & 0x01

    cdef inline void _set_bcm(self, uint8_t v) noexcept nogil:
        self._p[2] = (self._p[2] & 0xEF) | ((v & 0x01) << 4)

    @property
    def bcm(self):
        return self._get_bcm()

    @bcm.setter
    def bcm(self, v):
        self._set_bcm(<uint8_t>v)

    # ───── status : bits 21-23 (3 b) ───────────────────────────────────────
    cdef inline uint8_t _get_status(self) noexcept nogil:
        return (self._p[2] >> 5) & 0x07

    cdef inline void _set_status(self, uint8_t v) noexcept nogil:
        self._p[2] = (self._p[2] & 0x1F) | ((v & 0x07) << 5)

    @property
    def status(self):
        return self._get_status()

    @status.setter
    def status(self, v):
        self._set_status(<uint8_t>v)

    # ───── byte_count_lower : bits 24-31 (8 b) ─────────────────────────────
    cdef inline uint8_t _get_byte_count_lower(self) noexcept nogil:
        return self._p[3]

    cdef inline void _set_byte_count_lower(self, uint8_t v) noexcept nogil:
        self._p[3] = v

    @property
    def byte_count_lower(self):
        return self._get_byte_count_lower()

    @byte_count_lower.setter
    def byte_count_lower(self, v):
        self._set_byte_count_lower(<uint8_t>v)

    # ───── req_id : bits 32-47 (16 b) ──────────────────────────────────────
    cdef inline uint16_t _get_req_id(self) noexcept nogil:
        return <uint16_t>_read_bits(self._p, 32, 16)

    cdef inline void _set_req_id(self, uint16_t v) noexcept nogil:
        _write_bits(self._p, 32, 16, v)

    @property
    def req_id(self):
        return self._get_req_id()

    @req_id.setter
    def req_id(self, v):
        self._set_req_id(<uint16_t>v)

    # ───── tag : bits 48-55 (8 b) ──────────────────────────────────────────
    cdef inline uint8_t _get_tag(self) noexcept nogil:
        return self._p[6]

    cdef inline void _set_tag(self, uint8_t v) noexcept nogil:
        self._p[6] = v

    @property
    def tag(self):
        return self._get_tag()

    @tag.setter
    def tag(self, v):
        self._set_tag(<uint8_t>v)

    # ───── lower_addr : bits 56-62 (7 b) ───────────────────────────────────
    cdef inline uint8_t _get_lower_addr(self) noexcept nogil:
        return self._p[7] & 0x7F

    cdef inline void _set_lower_addr(self, uint8_t v) noexcept nogil:
        self._p[7] = (self._p[7] & 0x80) | (v & 0x7F)

    @property
    def lower_addr(self):
        return self._get_lower_addr()

    @lower_addr.setter
    def lower_addr(self, v):
        self._set_lower_addr(<uint8_t>v)

    # ───── rsvd : bit 63 (1 b) ─────────────────────────────────────────────
    cdef inline uint8_t _get_rsvd(self) noexcept nogil:
        return (self._p[7] >> 7) & 0x01

    cdef inline void _set_rsvd(self, uint8_t v) noexcept nogil:
        self._p[7] = (self._p[7] & 0x7F) | ((v & 0x01) << 7)

    @property
    def rsvd(self):
        return self._get_rsvd()

    @rsvd.setter
    def rsvd(self, v):
        self._set_rsvd(<uint8_t>v)

    # ───── misc helpers ────────────────────────────────────────────────────
    @classmethod
    def get_size(cls):
        return 8

    def __len__(self):
        return 8

    def __bytes__(self):
        return PyBytes_FromStringAndSize(<char*>self._p, 8)

# ───────────────────────────────────────────────────────────────────────────
#    CxlCacheHeader  (2 bytes)
# ───────────────────────────────────────────────────────────────────────────
cdef class CxlCacheHeader:
    __slots__ = ('_p')
    cdef uint8_t* _p

    def __cinit__(self):
        self._p = <uint8_t*>NULL  # NULL until first attach()

    cdef void attach(self, uint8_t* p) noexcept nogil:
        self._p = p

    # ───── port_index : bits 0-7 (8 b) ─────────────────────────────────────
    cdef inline uint8_t _get_port_index(self) noexcept nogil:
        return self._p[0]

    cdef inline void _set_port_index(self, uint8_t v) noexcept nogil:
        self._p[0] = v

    @property
    def port_index(self):
        return self._get_port_index()

    @port_index.setter
    def port_index(self, v):
        self._set_port_index(<uint8_t>v)

    # ───── msg_class : bits 8-15 (8 b) ─────────────────────────────────────
    cdef inline uint8_t _get_msg_class(self) noexcept nogil:
        return self._p[1]

    cdef inline void _set_msg_class(self, uint8_t v) noexcept nogil:
        self._p[1] = v

    @property
    def msg_class(self):
        return self._get_msg_class()

    @msg_class.setter
    def msg_class(self, v):
        self._set_msg_class(<uint8_t>v)

    # ───── misc helpers ────────────────────────────────────────────────────
    @classmethod
    def get_size(cls):
        return 2

    def __len__(self):
        return 2

    def __bytes__(self):
        return PyBytes_FromStringAndSize(<char*>self._p, 2)

# ───────────────────────────────────────────────────────────────────────────
#    CxlCacheD2HReqHeader  (9 bytes)
# ───────────────────────────────────────────────────────────────────────────
cdef class CxlCacheD2HReqHeader:
    __slots__ = ('_p')
    cdef uint8_t* _p

    def __cinit__(self):
        self._p = <uint8_t*>NULL  # NULL until first attach()

    cdef void attach(self, uint8_t* p) noexcept nogil:
        self._p = p

    # ───── valid : bit 0 (1 b) ─────────────────────────────────────────────
    cdef inline uint8_t _get_valid(self) noexcept nogil:
        return self._p[0] & 0x01

    cdef inline void _set_valid(self, uint8_t v) noexcept nogil:
        self._p[0] = (self._p[0] & 0xFE) | (v & 0x01)

    @property
    def valid(self):
        return self._get_valid()

    @valid.setter
    def valid(self, v):
        self._set_valid(<uint8_t>v)

    # ───── cache_opcode : bits 1-5 (5 b) ───────────────────────────────────
    cdef inline uint8_t _get_cache_opcode(self) noexcept nogil:
        return (self._p[0] >> 1) & 0x1F

    cdef inline void _set_cache_opcode(self, uint8_t v) noexcept nogil:
        self._p[0] = (self._p[0] & 0xC1) | ((v & 0x1F) << 1)

    @property
    def cache_opcode(self):
        return self._get_cache_opcode()

    @cache_opcode.setter
    def cache_opcode(self, v):
        self._set_cache_opcode(<uint8_t>v)

    # ───── cqid : bits 6-17 (12 b) ─────────────────────────────────────────
    cdef inline uint16_t _get_cqid(self) noexcept nogil:
        return <uint16_t>_read_bits(self._p, 6, 12)

    cdef inline void _set_cqid(self, uint16_t v) noexcept nogil:
        _write_bits(self._p, 6, 12, v)

    @property
    def cqid(self):
        return self._get_cqid()

    @cqid.setter
    def cqid(self, v):
        self._set_cqid(<uint16_t>v)

    # ───── nt : bit 18 (1 b) ───────────────────────────────────────────────
    cdef inline uint8_t _get_nt(self) noexcept nogil:
        return (self._p[2] >> 2) & 0x01

    cdef inline void _set_nt(self, uint8_t v) noexcept nogil:
        self._p[2] = (self._p[2] & 0xFB) | ((v & 0x01) << 2)

    @property
    def nt(self):
        return self._get_nt()

    @nt.setter
    def nt(self, v):
        self._set_nt(<uint8_t>v)

    # ───── cache_id : bits 19-22 (4 b) ─────────────────────────────────────
    cdef inline uint8_t _get_cache_id(self) noexcept nogil:
        return (self._p[2] >> 3) & 0x0F

    cdef inline void _set_cache_id(self, uint8_t v) noexcept nogil:
        self._p[2] = (self._p[2] & 0x87) | ((v & 0x0F) << 3)

    @property
    def cache_id(self):
        return self._get_cache_id()

    @cache_id.setter
    def cache_id(self, v):
        self._set_cache_id(<uint8_t>v)

    # ───── addr : bits 23-68 (46 b) ────────────────────────────────────────
    cdef inline uint64_t _get_addr(self) noexcept nogil:
        return <uint64_t>_read_bits(self._p, 23, 46)

    cdef inline void _set_addr(self, uint64_t v) noexcept nogil:
        _write_bits(self._p, 23, 46, v)

    @property
    def addr(self):
        return self._get_addr()

    @addr.setter
    def addr(self, v):
        self._set_addr(<uint64_t>v)

    # ───── rsvd : bits 69-71 (3 b) ─────────────────────────────────────────
    cdef inline uint8_t _get_rsvd(self) noexcept nogil:
        return (self._p[8] >> 5) & 0x07

    cdef inline void _set_rsvd(self, uint8_t v) noexcept nogil:
        self._p[8] = (self._p[8] & 0x1F) | ((v & 0x07) << 5)

    @property
    def rsvd(self):
        return self._get_rsvd()

    @rsvd.setter
    def rsvd(self, v):
        self._set_rsvd(<uint8_t>v)

    # ───── misc helpers ────────────────────────────────────────────────────
    @classmethod
    def get_size(cls):
        return 9

    def __len__(self):
        return 9

    def __bytes__(self):
        return PyBytes_FromStringAndSize(<char*>self._p, 9)

# ───────────────────────────────────────────────────────────────────────────
#    CxlCacheD2HRspHeader  (3 bytes)
# ───────────────────────────────────────────────────────────────────────────
cdef class CxlCacheD2HRspHeader:
    __slots__ = ('_p')
    cdef uint8_t* _p

    def __cinit__(self):
        self._p = <uint8_t*>NULL  # NULL until first attach()

    cdef void attach(self, uint8_t* p) noexcept nogil:
        self._p = p

    # ───── valid : bit 0 (1 b) ─────────────────────────────────────────────
    cdef inline uint8_t _get_valid(self) noexcept nogil:
        return self._p[0] & 0x01

    cdef inline void _set_valid(self, uint8_t v) noexcept nogil:
        self._p[0] = (self._p[0] & 0xFE) | (v & 0x01)

    @property
    def valid(self):
        return self._get_valid()

    @valid.setter
    def valid(self, v):
        self._set_valid(<uint8_t>v)

    # ───── cache_opcode : bits 1-5 (5 b) ───────────────────────────────────
    cdef inline uint8_t _get_cache_opcode(self) noexcept nogil:
        return (self._p[0] >> 1) & 0x1F

    cdef inline void _set_cache_opcode(self, uint8_t v) noexcept nogil:
        self._p[0] = (self._p[0] & 0xC1) | ((v & 0x1F) << 1)

    @property
    def cache_opcode(self):
        return self._get_cache_opcode()

    @cache_opcode.setter
    def cache_opcode(self, v):
        self._set_cache_opcode(<uint8_t>v)

    # ───── uqid : bits 6-17 (12 b) ─────────────────────────────────────────
    cdef inline uint16_t _get_uqid(self) noexcept nogil:
        return <uint16_t>_read_bits(self._p, 6, 12)

    cdef inline void _set_uqid(self, uint16_t v) noexcept nogil:
        _write_bits(self._p, 6, 12, v)

    @property
    def uqid(self):
        return self._get_uqid()

    @uqid.setter
    def uqid(self, v):
        self._set_uqid(<uint16_t>v)

    # ───── rsvd : bits 18-23 (6 b) ─────────────────────────────────────────
    cdef inline uint8_t _get_rsvd(self) noexcept nogil:
        return (self._p[2] >> 2) & 0x3F

    cdef inline void _set_rsvd(self, uint8_t v) noexcept nogil:
        self._p[2] = (self._p[2] & 0x03) | ((v & 0x3F) << 2)

    @property
    def rsvd(self):
        return self._get_rsvd()

    @rsvd.setter
    def rsvd(self, v):
        self._set_rsvd(<uint8_t>v)

    # ───── misc helpers ────────────────────────────────────────────────────
    @classmethod
    def get_size(cls):
        return 3

    def __len__(self):
        return 3

    def __bytes__(self):
        return PyBytes_FromStringAndSize(<char*>self._p, 3)

# ───────────────────────────────────────────────────────────────────────────
#    CxlCacheD2HDataHeader  (3 bytes)
# ───────────────────────────────────────────────────────────────────────────
cdef class CxlCacheD2HDataHeader:
    __slots__ = ('_p')
    cdef uint8_t* _p

    def __cinit__(self):
        self._p = <uint8_t*>NULL  # NULL until first attach()

    cdef void attach(self, uint8_t* p) noexcept nogil:
        self._p = p

    # ───── valid : bit 0 (1 b) ─────────────────────────────────────────────
    cdef inline uint8_t _get_valid(self) noexcept nogil:
        return self._p[0] & 0x01

    cdef inline void _set_valid(self, uint8_t v) noexcept nogil:
        self._p[0] = (self._p[0] & 0xFE) | (v & 0x01)

    @property
    def valid(self):
        return self._get_valid()

    @valid.setter
    def valid(self, v):
        self._set_valid(<uint8_t>v)

    # ───── uqid : bits 1-12 (12 b) ─────────────────────────────────────────
    cdef inline uint16_t _get_uqid(self) noexcept nogil:
        return <uint16_t>_read_bits(self._p, 1, 12)

    cdef inline void _set_uqid(self, uint16_t v) noexcept nogil:
        _write_bits(self._p, 1, 12, v)

    @property
    def uqid(self):
        return self._get_uqid()

    @uqid.setter
    def uqid(self, v):
        self._set_uqid(<uint16_t>v)

    # ───── bogus : bit 13 (1 b) ────────────────────────────────────────────
    cdef inline uint8_t _get_bogus(self) noexcept nogil:
        return (self._p[1] >> 5) & 0x01

    cdef inline void _set_bogus(self, uint8_t v) noexcept nogil:
        self._p[1] = (self._p[1] & 0xDF) | ((v & 0x01) << 5)

    @property
    def bogus(self):
        return self._get_bogus()

    @bogus.setter
    def bogus(self, v):
        self._set_bogus(<uint8_t>v)

    # ───── poison : bit 14 (1 b) ───────────────────────────────────────────
    cdef inline uint8_t _get_poison(self) noexcept nogil:
        return (self._p[1] >> 6) & 0x01

    cdef inline void _set_poison(self, uint8_t v) noexcept nogil:
        self._p[1] = (self._p[1] & 0xBF) | ((v & 0x01) << 6)

    @property
    def poison(self):
        return self._get_poison()

    @poison.setter
    def poison(self, v):
        self._set_poison(<uint8_t>v)

    # ───── bep : bit 15 (1 b) ──────────────────────────────────────────────
    cdef inline uint8_t _get_bep(self) noexcept nogil:
        return (self._p[1] >> 7) & 0x01

    cdef inline void _set_bep(self, uint8_t v) noexcept nogil:
        self._p[1] = (self._p[1] & 0x7F) | ((v & 0x01) << 7)

    @property
    def bep(self):
        return self._get_bep()

    @bep.setter
    def bep(self, v):
        self._set_bep(<uint8_t>v)

    # ───── rsvd : bits 16-23 (8 b) ─────────────────────────────────────────
    cdef inline uint8_t _get_rsvd(self) noexcept nogil:
        return self._p[2]

    cdef inline void _set_rsvd(self, uint8_t v) noexcept nogil:
        self._p[2] = v

    @property
    def rsvd(self):
        return self._get_rsvd()

    @rsvd.setter
    def rsvd(self, v):
        self._set_rsvd(<uint8_t>v)

    # ───── misc helpers ────────────────────────────────────────────────────
    @classmethod
    def get_size(cls):
        return 3

    def __len__(self):
        return 3

    def __bytes__(self):
        return PyBytes_FromStringAndSize(<char*>self._p, 3)

# ───────────────────────────────────────────────────────────────────────────
#    CxlCacheH2DReqHeader  (9 bytes)
# ───────────────────────────────────────────────────────────────────────────
cdef class CxlCacheH2DReqHeader:
    __slots__ = ('_p')
    cdef uint8_t* _p

    def __cinit__(self):
        self._p = <uint8_t*>NULL  # NULL until first attach()

    cdef void attach(self, uint8_t* p) noexcept nogil:
        self._p = p

    # ───── valid : bit 0 (1 b) ─────────────────────────────────────────────
    cdef inline uint8_t _get_valid(self) noexcept nogil:
        return self._p[0] & 0x01

    cdef inline void _set_valid(self, uint8_t v) noexcept nogil:
        self._p[0] = (self._p[0] & 0xFE) | (v & 0x01)

    @property
    def valid(self):
        return self._get_valid()

    @valid.setter
    def valid(self, v):
        self._set_valid(<uint8_t>v)

    # ───── cache_opcode : bits 1-3 (3 b) ───────────────────────────────────
    cdef inline uint8_t _get_cache_opcode(self) noexcept nogil:
        return (self._p[0] >> 1) & 0x07

    cdef inline void _set_cache_opcode(self, uint8_t v) noexcept nogil:
        self._p[0] = (self._p[0] & 0xF1) | ((v & 0x07) << 1)

    @property
    def cache_opcode(self):
        return self._get_cache_opcode()

    @cache_opcode.setter
    def cache_opcode(self, v):
        self._set_cache_opcode(<uint8_t>v)

    # ───── addr : bits 4-49 (46 b) ─────────────────────────────────────────
    cdef inline uint64_t _get_addr(self) noexcept nogil:
        return <uint64_t>_read_bits(self._p, 4, 46)

    cdef inline void _set_addr(self, uint64_t v) noexcept nogil:
        _write_bits(self._p, 4, 46, v)

    @property
    def addr(self):
        return self._get_addr()

    @addr.setter
    def addr(self, v):
        self._set_addr(<uint64_t>v)

    # ───── uqid : bits 50-61 (12 b) ────────────────────────────────────────
    cdef inline uint16_t _get_uqid(self) noexcept nogil:
        return <uint16_t>_read_bits(self._p, 50, 12)

    cdef inline void _set_uqid(self, uint16_t v) noexcept nogil:
        _write_bits(self._p, 50, 12, v)

    @property
    def uqid(self):
        return self._get_uqid()

    @uqid.setter
    def uqid(self, v):
        self._set_uqid(<uint16_t>v)

    # ───── cache_id : bits 62-65 (4 b) ─────────────────────────────────────
    cdef inline uint8_t _get_cache_id(self) noexcept nogil:
        return (self._p[7] >> 6) & 0x0F

    cdef inline void _set_cache_id(self, uint8_t v) noexcept nogil:
        self._p[7] = (self._p[7] & 0x3F) | ((v & 0x0F) << 6)

    @property
    def cache_id(self):
        return self._get_cache_id()

    @cache_id.setter
    def cache_id(self, v):
        self._set_cache_id(<uint8_t>v)

    # ───── rsvd : bits 66-71 (6 b) ─────────────────────────────────────────
    cdef inline uint8_t _get_rsvd(self) noexcept nogil:
        return (self._p[8] >> 2) & 0x3F

    cdef inline void _set_rsvd(self, uint8_t v) noexcept nogil:
        self._p[8] = (self._p[8] & 0x03) | ((v & 0x3F) << 2)

    @property
    def rsvd(self):
        return self._get_rsvd()

    @rsvd.setter
    def rsvd(self, v):
        self._set_rsvd(<uint8_t>v)

    # ───── misc helpers ────────────────────────────────────────────────────
    @classmethod
    def get_size(cls):
        return 9

    def __len__(self):
        return 9

    def __bytes__(self):
        return PyBytes_FromStringAndSize(<char*>self._p, 9)

# ───────────────────────────────────────────────────────────────────────────
#    CxlCacheH2DRspHeader  (5 bytes)
# ───────────────────────────────────────────────────────────────────────────
cdef class CxlCacheH2DRspHeader:
    __slots__ = ('_p')
    cdef uint8_t* _p

    def __cinit__(self):
        self._p = <uint8_t*>NULL  # NULL until first attach()

    cdef void attach(self, uint8_t* p) noexcept nogil:
        self._p = p

    # ───── valid : bit 0 (1 b) ─────────────────────────────────────────────
    cdef inline uint8_t _get_valid(self) noexcept nogil:
        return self._p[0] & 0x01

    cdef inline void _set_valid(self, uint8_t v) noexcept nogil:
        self._p[0] = (self._p[0] & 0xFE) | (v & 0x01)

    @property
    def valid(self):
        return self._get_valid()

    @valid.setter
    def valid(self, v):
        self._set_valid(<uint8_t>v)

    # ───── cache_opcode : bits 1-4 (4 b) ───────────────────────────────────
    cdef inline uint8_t _get_cache_opcode(self) noexcept nogil:
        return (self._p[0] >> 1) & 0x0F

    cdef inline void _set_cache_opcode(self, uint8_t v) noexcept nogil:
        self._p[0] = (self._p[0] & 0xE1) | ((v & 0x0F) << 1)

    @property
    def cache_opcode(self):
        return self._get_cache_opcode()

    @cache_opcode.setter
    def cache_opcode(self, v):
        self._set_cache_opcode(<uint8_t>v)

    # ───── rsp_data : bits 5-16 (12 b) ─────────────────────────────────────
    cdef inline uint16_t _get_rsp_data(self) noexcept nogil:
        return <uint16_t>_read_bits(self._p, 5, 12)

    cdef inline void _set_rsp_data(self, uint16_t v) noexcept nogil:
        _write_bits(self._p, 5, 12, v)

    @property
    def rsp_data(self):
        return self._get_rsp_data()

    @rsp_data.setter
    def rsp_data(self, v):
        self._set_rsp_data(<uint16_t>v)

    # ───── rsp_pre : bits 17-18 (2 b) ──────────────────────────────────────
    cdef inline uint8_t _get_rsp_pre(self) noexcept nogil:
        return (self._p[2] >> 1) & 0x03

    cdef inline void _set_rsp_pre(self, uint8_t v) noexcept nogil:
        self._p[2] = (self._p[2] & 0xF9) | ((v & 0x03) << 1)

    @property
    def rsp_pre(self):
        return self._get_rsp_pre()

    @rsp_pre.setter
    def rsp_pre(self, v):
        self._set_rsp_pre(<uint8_t>v)

    # ───── cqid : bits 19-30 (12 b) ────────────────────────────────────────
    cdef inline uint16_t _get_cqid(self) noexcept nogil:
        return <uint16_t>_read_bits(self._p, 19, 12)

    cdef inline void _set_cqid(self, uint16_t v) noexcept nogil:
        _write_bits(self._p, 19, 12, v)

    @property
    def cqid(self):
        return self._get_cqid()

    @cqid.setter
    def cqid(self, v):
        self._set_cqid(<uint16_t>v)

    # ───── cache_id : bits 31-34 (4 b) ─────────────────────────────────────
    cdef inline uint8_t _get_cache_id(self) noexcept nogil:
        return (self._p[3] >> 7) & 0x0F

    cdef inline void _set_cache_id(self, uint8_t v) noexcept nogil:
        self._p[3] = (self._p[3] & 0x7F) | ((v & 0x0F) << 7)

    @property
    def cache_id(self):
        return self._get_cache_id()

    @cache_id.setter
    def cache_id(self, v):
        self._set_cache_id(<uint8_t>v)

    # ───── rsvd : bits 35-39 (5 b) ─────────────────────────────────────────
    cdef inline uint8_t _get_rsvd(self) noexcept nogil:
        return (self._p[4] >> 3) & 0x1F

    cdef inline void _set_rsvd(self, uint8_t v) noexcept nogil:
        self._p[4] = (self._p[4] & 0x07) | ((v & 0x1F) << 3)

    @property
    def rsvd(self):
        return self._get_rsvd()

    @rsvd.setter
    def rsvd(self, v):
        self._set_rsvd(<uint8_t>v)

    # ───── misc helpers ────────────────────────────────────────────────────
    @classmethod
    def get_size(cls):
        return 5

    def __len__(self):
        return 5

    def __bytes__(self):
        return PyBytes_FromStringAndSize(<char*>self._p, 5)

# ───────────────────────────────────────────────────────────────────────────
#    CxlCacheH2DDataHeader  (3 bytes)
# ───────────────────────────────────────────────────────────────────────────
cdef class CxlCacheH2DDataHeader:
    __slots__ = ('_p')
    cdef uint8_t* _p

    def __cinit__(self):
        self._p = <uint8_t*>NULL  # NULL until first attach()

    cdef void attach(self, uint8_t* p) noexcept nogil:
        self._p = p

    # ───── valid : bit 0 (1 b) ─────────────────────────────────────────────
    cdef inline uint8_t _get_valid(self) noexcept nogil:
        return self._p[0] & 0x01

    cdef inline void _set_valid(self, uint8_t v) noexcept nogil:
        self._p[0] = (self._p[0] & 0xFE) | (v & 0x01)

    @property
    def valid(self):
        return self._get_valid()

    @valid.setter
    def valid(self, v):
        self._set_valid(<uint8_t>v)

    # ───── cqid : bits 1-12 (12 b) ─────────────────────────────────────────
    cdef inline uint16_t _get_cqid(self) noexcept nogil:
        return <uint16_t>_read_bits(self._p, 1, 12)

    cdef inline void _set_cqid(self, uint16_t v) noexcept nogil:
        _write_bits(self._p, 1, 12, v)

    @property
    def cqid(self):
        return self._get_cqid()

    @cqid.setter
    def cqid(self, v):
        self._set_cqid(<uint16_t>v)

    # ───── poison : bit 13 (1 b) ───────────────────────────────────────────
    cdef inline uint8_t _get_poison(self) noexcept nogil:
        return (self._p[1] >> 5) & 0x01

    cdef inline void _set_poison(self, uint8_t v) noexcept nogil:
        self._p[1] = (self._p[1] & 0xDF) | ((v & 0x01) << 5)

    @property
    def poison(self):
        return self._get_poison()

    @poison.setter
    def poison(self, v):
        self._set_poison(<uint8_t>v)

    # ───── go_err : bit 14 (1 b) ───────────────────────────────────────────
    cdef inline uint8_t _get_go_err(self) noexcept nogil:
        return (self._p[1] >> 6) & 0x01

    cdef inline void _set_go_err(self, uint8_t v) noexcept nogil:
        self._p[1] = (self._p[1] & 0xBF) | ((v & 0x01) << 6)

    @property
    def go_err(self):
        return self._get_go_err()

    @go_err.setter
    def go_err(self, v):
        self._set_go_err(<uint8_t>v)

    # ───── cache_id : bits 15-18 (4 b) ─────────────────────────────────────
    cdef inline uint8_t _get_cache_id(self) noexcept nogil:
        return (self._p[1] >> 7) & 0x0F

    cdef inline void _set_cache_id(self, uint8_t v) noexcept nogil:
        self._p[1] = (self._p[1] & 0x7F) | ((v & 0x0F) << 7)

    @property
    def cache_id(self):
        return self._get_cache_id()

    @cache_id.setter
    def cache_id(self, v):
        self._set_cache_id(<uint8_t>v)

    # ───── rsvd : bits 19-23 (5 b) ─────────────────────────────────────────
    cdef inline uint8_t _get_rsvd(self) noexcept nogil:
        return (self._p[2] >> 3) & 0x1F

    cdef inline void _set_rsvd(self, uint8_t v) noexcept nogil:
        self._p[2] = (self._p[2] & 0x07) | ((v & 0x1F) << 3)

    @property
    def rsvd(self):
        return self._get_rsvd()

    @rsvd.setter
    def rsvd(self, v):
        self._set_rsvd(<uint8_t>v)

    # ───── misc helpers ────────────────────────────────────────────────────
    @classmethod
    def get_size(cls):
        return 3

    def __len__(self):
        return 3

    def __bytes__(self):
        return PyBytes_FromStringAndSize(<char*>self._p, 3)

# ───────────────────────────────────────────────────────────────────────────
#    CxlMemHeader  (2 bytes)
# ───────────────────────────────────────────────────────────────────────────
cdef class CxlMemHeader:
    __slots__ = ('_p')
    cdef uint8_t* _p

    def __cinit__(self):
        self._p = <uint8_t*>NULL  # NULL until first attach()

    cdef void attach(self, uint8_t* p) noexcept nogil:
        self._p = p

    # ───── port_index : bits 0-7 (8 b) ─────────────────────────────────────
    cdef inline uint8_t _get_port_index(self) noexcept nogil:
        return self._p[0]

    cdef inline void _set_port_index(self, uint8_t v) noexcept nogil:
        self._p[0] = v

    @property
    def port_index(self):
        return self._get_port_index()

    @port_index.setter
    def port_index(self, v):
        self._set_port_index(<uint8_t>v)

    # ───── msg_class : bits 8-15 (8 b) ─────────────────────────────────────
    cdef inline uint8_t _get_msg_class(self) noexcept nogil:
        return self._p[1]

    cdef inline void _set_msg_class(self, uint8_t v) noexcept nogil:
        self._p[1] = v

    @property
    def msg_class(self):
        return self._get_msg_class()

    @msg_class.setter
    def msg_class(self, v):
        self._set_msg_class(<uint8_t>v)

    # ───── misc helpers ────────────────────────────────────────────────────
    @classmethod
    def get_size(cls):
        return 2

    def __len__(self):
        return 2

    def __bytes__(self):
        return PyBytes_FromStringAndSize(<char*>self._p, 2)

# ───────────────────────────────────────────────────────────────────────────
#    CxlMemM2SReqHeader  (13 bytes)
# ───────────────────────────────────────────────────────────────────────────
cdef class CxlMemM2SReqHeader:
    __slots__ = ('_p')
    cdef uint8_t* _p

    def __cinit__(self):
        self._p = <uint8_t*>NULL  # NULL until first attach()

    cdef void attach(self, uint8_t* p) noexcept nogil:
        self._p = p

    # ───── valid : bit 0 (1 b) ─────────────────────────────────────────────
    cdef inline uint8_t _get_valid(self) noexcept nogil:
        return self._p[0] & 0x01

    cdef inline void _set_valid(self, uint8_t v) noexcept nogil:
        self._p[0] = (self._p[0] & 0xFE) | (v & 0x01)

    @property
    def valid(self):
        return self._get_valid()

    @valid.setter
    def valid(self, v):
        self._set_valid(<uint8_t>v)

    # ───── mem_opcode : bits 1-4 (4 b) ─────────────────────────────────────
    cdef inline uint8_t _get_mem_opcode(self) noexcept nogil:
        return (self._p[0] >> 1) & 0x0F

    cdef inline void _set_mem_opcode(self, uint8_t v) noexcept nogil:
        self._p[0] = (self._p[0] & 0xE1) | ((v & 0x0F) << 1)

    @property
    def mem_opcode(self):
        return self._get_mem_opcode()

    @mem_opcode.setter
    def mem_opcode(self, v):
        self._set_mem_opcode(<uint8_t>v)

    # ───── snp_type : bits 5-7 (3 b) ───────────────────────────────────────
    cdef inline uint8_t _get_snp_type(self) noexcept nogil:
        return (self._p[0] >> 5) & 0x07

    cdef inline void _set_snp_type(self, uint8_t v) noexcept nogil:
        self._p[0] = (self._p[0] & 0x1F) | ((v & 0x07) << 5)

    @property
    def snp_type(self):
        return self._get_snp_type()

    @snp_type.setter
    def snp_type(self, v):
        self._set_snp_type(<uint8_t>v)

    # ───── meta_field : bits 8-9 (2 b) ─────────────────────────────────────
    cdef inline uint8_t _get_meta_field(self) noexcept nogil:
        return self._p[1] & 0x03

    cdef inline void _set_meta_field(self, uint8_t v) noexcept nogil:
        self._p[1] = (self._p[1] & 0xFC) | (v & 0x03)

    @property
    def meta_field(self):
        return self._get_meta_field()

    @meta_field.setter
    def meta_field(self, v):
        self._set_meta_field(<uint8_t>v)

    # ───── meta_value : bits 10-11 (2 b) ───────────────────────────────────
    cdef inline uint8_t _get_meta_value(self) noexcept nogil:
        return (self._p[1] >> 2) & 0x03

    cdef inline void _set_meta_value(self, uint8_t v) noexcept nogil:
        self._p[1] = (self._p[1] & 0xF3) | ((v & 0x03) << 2)

    @property
    def meta_value(self):
        return self._get_meta_value()

    @meta_value.setter
    def meta_value(self, v):
        self._set_meta_value(<uint8_t>v)

    # ───── tag : bits 12-27 (16 b) ─────────────────────────────────────────
    cdef inline uint16_t _get_tag(self) noexcept nogil:
        return <uint16_t>_read_bits(self._p, 12, 16)

    cdef inline void _set_tag(self, uint16_t v) noexcept nogil:
        _write_bits(self._p, 12, 16, v)

    @property
    def tag(self):
        return self._get_tag()

    @tag.setter
    def tag(self, v):
        self._set_tag(<uint16_t>v)

    # ───── addr : bits 28-73 (46 b) ────────────────────────────────────────
    cdef inline uint64_t _get_addr(self) noexcept nogil:
        return <uint64_t>_read_bits(self._p, 28, 46)

    cdef inline void _set_addr(self, uint64_t v) noexcept nogil:
        _write_bits(self._p, 28, 46, v)

    @property
    def addr(self):
        return self._get_addr()

    @addr.setter
    def addr(self, v):
        self._set_addr(<uint64_t>v)

    # ───── ld_id : bits 74-77 (4 b) ────────────────────────────────────────
    cdef inline uint8_t _get_ld_id(self) noexcept nogil:
        return (self._p[9] >> 2) & 0x0F

    cdef inline void _set_ld_id(self, uint8_t v) noexcept nogil:
        self._p[9] = (self._p[9] & 0xC3) | ((v & 0x0F) << 2)

    @property
    def ld_id(self):
        return self._get_ld_id()

    @ld_id.setter
    def ld_id(self, v):
        self._set_ld_id(<uint8_t>v)

    # ───── rsvd : bits 78-97 (20 b) ────────────────────────────────────────
    cdef inline uint32_t _get_rsvd(self) noexcept nogil:
        return <uint32_t>_read_bits(self._p, 78, 20)

    cdef inline void _set_rsvd(self, uint32_t v) noexcept nogil:
        _write_bits(self._p, 78, 20, v)

    @property
    def rsvd(self):
        return self._get_rsvd()

    @rsvd.setter
    def rsvd(self, v):
        self._set_rsvd(<uint32_t>v)

    # ───── tc : bits 98-99 (2 b) ───────────────────────────────────────────
    cdef inline uint8_t _get_tc(self) noexcept nogil:
        return (self._p[12] >> 2) & 0x03

    cdef inline void _set_tc(self, uint8_t v) noexcept nogil:
        self._p[12] = (self._p[12] & 0xF3) | ((v & 0x03) << 2)

    @property
    def tc(self):
        return self._get_tc()

    @tc.setter
    def tc(self, v):
        self._set_tc(<uint8_t>v)

    # ───── padding : bits 100-103 (4 b) ────────────────────────────────────
    cdef inline uint8_t _get_padding(self) noexcept nogil:
        return (self._p[12] >> 4) & 0x0F

    cdef inline void _set_padding(self, uint8_t v) noexcept nogil:
        self._p[12] = (self._p[12] & 0x0F) | ((v & 0x0F) << 4)

    @property
    def padding(self):
        return self._get_padding()

    @padding.setter
    def padding(self, v):
        self._set_padding(<uint8_t>v)

    # ───── misc helpers ────────────────────────────────────────────────────
    @classmethod
    def get_size(cls):
        return 13

    def __len__(self):
        return 13

    def __bytes__(self):
        return PyBytes_FromStringAndSize(<char*>self._p, 13)

# ───────────────────────────────────────────────────────────────────────────
#    CxlMemM2SRwDHeader  (13 bytes)
# ───────────────────────────────────────────────────────────────────────────
cdef class CxlMemM2SRwDHeader:
    __slots__ = ('_p')
    cdef uint8_t* _p

    def __cinit__(self):
        self._p = <uint8_t*>NULL  # NULL until first attach()

    cdef void attach(self, uint8_t* p) noexcept nogil:
        self._p = p

    # ───── valid : bit 0 (1 b) ─────────────────────────────────────────────
    cdef inline uint8_t _get_valid(self) noexcept nogil:
        return self._p[0] & 0x01

    cdef inline void _set_valid(self, uint8_t v) noexcept nogil:
        self._p[0] = (self._p[0] & 0xFE) | (v & 0x01)

    @property
    def valid(self):
        return self._get_valid()

    @valid.setter
    def valid(self, v):
        self._set_valid(<uint8_t>v)

    # ───── mem_opcode : bits 1-4 (4 b) ─────────────────────────────────────
    cdef inline uint8_t _get_mem_opcode(self) noexcept nogil:
        return (self._p[0] >> 1) & 0x0F

    cdef inline void _set_mem_opcode(self, uint8_t v) noexcept nogil:
        self._p[0] = (self._p[0] & 0xE1) | ((v & 0x0F) << 1)

    @property
    def mem_opcode(self):
        return self._get_mem_opcode()

    @mem_opcode.setter
    def mem_opcode(self, v):
        self._set_mem_opcode(<uint8_t>v)

    # ───── snp_type : bits 5-7 (3 b) ───────────────────────────────────────
    cdef inline uint8_t _get_snp_type(self) noexcept nogil:
        return (self._p[0] >> 5) & 0x07

    cdef inline void _set_snp_type(self, uint8_t v) noexcept nogil:
        self._p[0] = (self._p[0] & 0x1F) | ((v & 0x07) << 5)

    @property
    def snp_type(self):
        return self._get_snp_type()

    @snp_type.setter
    def snp_type(self, v):
        self._set_snp_type(<uint8_t>v)

    # ───── meta_field : bits 8-9 (2 b) ─────────────────────────────────────
    cdef inline uint8_t _get_meta_field(self) noexcept nogil:
        return self._p[1] & 0x03

    cdef inline void _set_meta_field(self, uint8_t v) noexcept nogil:
        self._p[1] = (self._p[1] & 0xFC) | (v & 0x03)

    @property
    def meta_field(self):
        return self._get_meta_field()

    @meta_field.setter
    def meta_field(self, v):
        self._set_meta_field(<uint8_t>v)

    # ───── meta_value : bits 10-11 (2 b) ───────────────────────────────────
    cdef inline uint8_t _get_meta_value(self) noexcept nogil:
        return (self._p[1] >> 2) & 0x03

    cdef inline void _set_meta_value(self, uint8_t v) noexcept nogil:
        self._p[1] = (self._p[1] & 0xF3) | ((v & 0x03) << 2)

    @property
    def meta_value(self):
        return self._get_meta_value()

    @meta_value.setter
    def meta_value(self, v):
        self._set_meta_value(<uint8_t>v)

    # ───── tag : bits 12-27 (16 b) ─────────────────────────────────────────
    cdef inline uint16_t _get_tag(self) noexcept nogil:
        return <uint16_t>_read_bits(self._p, 12, 16)

    cdef inline void _set_tag(self, uint16_t v) noexcept nogil:
        _write_bits(self._p, 12, 16, v)

    @property
    def tag(self):
        return self._get_tag()

    @tag.setter
    def tag(self, v):
        self._set_tag(<uint16_t>v)

    # ───── addr : bits 28-73 (46 b) ────────────────────────────────────────
    cdef inline uint64_t _get_addr(self) noexcept nogil:
        return <uint64_t>_read_bits(self._p, 28, 46)

    cdef inline void _set_addr(self, uint64_t v) noexcept nogil:
        _write_bits(self._p, 28, 46, v)

    @property
    def addr(self):
        return self._get_addr()

    @addr.setter
    def addr(self, v):
        self._set_addr(<uint64_t>v)

    # ───── poison : bit 74 (1 b) ───────────────────────────────────────────
    cdef inline uint8_t _get_poison(self) noexcept nogil:
        return (self._p[9] >> 2) & 0x01

    cdef inline void _set_poison(self, uint8_t v) noexcept nogil:
        self._p[9] = (self._p[9] & 0xFB) | ((v & 0x01) << 2)

    @property
    def poison(self):
        return self._get_poison()

    @poison.setter
    def poison(self, v):
        self._set_poison(<uint8_t>v)

    # ───── bep : bit 75 (1 b) ──────────────────────────────────────────────
    cdef inline uint8_t _get_bep(self) noexcept nogil:
        return (self._p[9] >> 3) & 0x01

    cdef inline void _set_bep(self, uint8_t v) noexcept nogil:
        self._p[9] = (self._p[9] & 0xF7) | ((v & 0x01) << 3)

    @property
    def bep(self):
        return self._get_bep()

    @bep.setter
    def bep(self, v):
        self._set_bep(<uint8_t>v)

    # ───── ld_id : bits 76-79 (4 b) ────────────────────────────────────────
    cdef inline uint8_t _get_ld_id(self) noexcept nogil:
        return (self._p[9] >> 4) & 0x0F

    cdef inline void _set_ld_id(self, uint8_t v) noexcept nogil:
        self._p[9] = (self._p[9] & 0x0F) | ((v & 0x0F) << 4)

    @property
    def ld_id(self):
        return self._get_ld_id()

    @ld_id.setter
    def ld_id(self, v):
        self._set_ld_id(<uint8_t>v)

    # ───── rsvd : bits 80-101 (22 b) ───────────────────────────────────────
    cdef inline uint32_t _get_rsvd(self) noexcept nogil:
        return <uint32_t>_read_bits(self._p, 80, 22)

    cdef inline void _set_rsvd(self, uint32_t v) noexcept nogil:
        _write_bits(self._p, 80, 22, v)

    @property
    def rsvd(self):
        return self._get_rsvd()

    @rsvd.setter
    def rsvd(self, v):
        self._set_rsvd(<uint32_t>v)

    # ───── tc : bits 102-103 (2 b) ─────────────────────────────────────────
    cdef inline uint8_t _get_tc(self) noexcept nogil:
        return (self._p[12] >> 6) & 0x03

    cdef inline void _set_tc(self, uint8_t v) noexcept nogil:
        self._p[12] = (self._p[12] & 0x3F) | ((v & 0x03) << 6)

    @property
    def tc(self):
        return self._get_tc()

    @tc.setter
    def tc(self, v):
        self._set_tc(<uint8_t>v)

    # ───── misc helpers ────────────────────────────────────────────────────
    @classmethod
    def get_size(cls):
        return 13

    def __len__(self):
        return 13

    def __bytes__(self):
        return PyBytes_FromStringAndSize(<char*>self._p, 13)

# ───────────────────────────────────────────────────────────────────────────
#    CxlMemM2SBIRspHeader  (5 bytes)
# ───────────────────────────────────────────────────────────────────────────
cdef class CxlMemM2SBIRspHeader:
    __slots__ = ('_p')
    cdef uint8_t* _p

    def __cinit__(self):
        self._p = <uint8_t*>NULL  # NULL until first attach()

    cdef void attach(self, uint8_t* p) noexcept nogil:
        self._p = p

    # ───── valid : bit 0 (1 b) ─────────────────────────────────────────────
    cdef inline uint8_t _get_valid(self) noexcept nogil:
        return self._p[0] & 0x01

    cdef inline void _set_valid(self, uint8_t v) noexcept nogil:
        self._p[0] = (self._p[0] & 0xFE) | (v & 0x01)

    @property
    def valid(self):
        return self._get_valid()

    @valid.setter
    def valid(self, v):
        self._set_valid(<uint8_t>v)

    # ───── opcode : bits 1-4 (4 b) ─────────────────────────────────────────
    cdef inline uint8_t _get_opcode(self) noexcept nogil:
        return (self._p[0] >> 1) & 0x0F

    cdef inline void _set_opcode(self, uint8_t v) noexcept nogil:
        self._p[0] = (self._p[0] & 0xE1) | ((v & 0x0F) << 1)

    @property
    def opcode(self):
        return self._get_opcode()

    @opcode.setter
    def opcode(self, v):
        self._set_opcode(<uint8_t>v)

    # ───── bi_id : bits 5-16 (12 b) ────────────────────────────────────────
    cdef inline uint16_t _get_bi_id(self) noexcept nogil:
        return <uint16_t>_read_bits(self._p, 5, 12)

    cdef inline void _set_bi_id(self, uint16_t v) noexcept nogil:
        _write_bits(self._p, 5, 12, v)

    @property
    def bi_id(self):
        return self._get_bi_id()

    @bi_id.setter
    def bi_id(self, v):
        self._set_bi_id(<uint16_t>v)

    # ───── bi_tag : bits 17-28 (12 b) ──────────────────────────────────────
    cdef inline uint16_t _get_bi_tag(self) noexcept nogil:
        return <uint16_t>_read_bits(self._p, 17, 12)

    cdef inline void _set_bi_tag(self, uint16_t v) noexcept nogil:
        _write_bits(self._p, 17, 12, v)

    @property
    def bi_tag(self):
        return self._get_bi_tag()

    @bi_tag.setter
    def bi_tag(self, v):
        self._set_bi_tag(<uint16_t>v)

    # ───── low_addr : bits 29-30 (2 b) ─────────────────────────────────────
    cdef inline uint8_t _get_low_addr(self) noexcept nogil:
        return (self._p[3] >> 5) & 0x03

    cdef inline void _set_low_addr(self, uint8_t v) noexcept nogil:
        self._p[3] = (self._p[3] & 0x9F) | ((v & 0x03) << 5)

    @property
    def low_addr(self):
        return self._get_low_addr()

    @low_addr.setter
    def low_addr(self, v):
        self._set_low_addr(<uint8_t>v)

    # ───── rsvd : bits 31-39 (9 b) ─────────────────────────────────────────
    cdef inline uint16_t _get_rsvd(self) noexcept nogil:
        return <uint16_t>_read_bits(self._p, 31, 9)

    cdef inline void _set_rsvd(self, uint16_t v) noexcept nogil:
        _write_bits(self._p, 31, 9, v)

    @property
    def rsvd(self):
        return self._get_rsvd()

    @rsvd.setter
    def rsvd(self, v):
        self._set_rsvd(<uint16_t>v)

    # ───── misc helpers ────────────────────────────────────────────────────
    @classmethod
    def get_size(cls):
        return 5

    def __len__(self):
        return 5

    def __bytes__(self):
        return PyBytes_FromStringAndSize(<char*>self._p, 5)

# ───────────────────────────────────────────────────────────────────────────
#    CxlMemS2MBISnpHeader  (10 bytes)
# ───────────────────────────────────────────────────────────────────────────
cdef class CxlMemS2MBISnpHeader:
    __slots__ = ('_p')
    cdef uint8_t* _p

    def __cinit__(self):
        self._p = <uint8_t*>NULL  # NULL until first attach()

    cdef void attach(self, uint8_t* p) noexcept nogil:
        self._p = p

    # ───── valid : bit 0 (1 b) ─────────────────────────────────────────────
    cdef inline uint8_t _get_valid(self) noexcept nogil:
        return self._p[0] & 0x01

    cdef inline void _set_valid(self, uint8_t v) noexcept nogil:
        self._p[0] = (self._p[0] & 0xFE) | (v & 0x01)

    @property
    def valid(self):
        return self._get_valid()

    @valid.setter
    def valid(self, v):
        self._set_valid(<uint8_t>v)

    # ───── opcode : bits 1-4 (4 b) ─────────────────────────────────────────
    cdef inline uint8_t _get_opcode(self) noexcept nogil:
        return (self._p[0] >> 1) & 0x0F

    cdef inline void _set_opcode(self, uint8_t v) noexcept nogil:
        self._p[0] = (self._p[0] & 0xE1) | ((v & 0x0F) << 1)

    @property
    def opcode(self):
        return self._get_opcode()

    @opcode.setter
    def opcode(self, v):
        self._set_opcode(<uint8_t>v)

    # ───── bi_id : bits 5-16 (12 b) ────────────────────────────────────────
    cdef inline uint16_t _get_bi_id(self) noexcept nogil:
        return <uint16_t>_read_bits(self._p, 5, 12)

    cdef inline void _set_bi_id(self, uint16_t v) noexcept nogil:
        _write_bits(self._p, 5, 12, v)

    @property
    def bi_id(self):
        return self._get_bi_id()

    @bi_id.setter
    def bi_id(self, v):
        self._set_bi_id(<uint16_t>v)

    # ───── bi_tag : bits 17-28 (12 b) ──────────────────────────────────────
    cdef inline uint16_t _get_bi_tag(self) noexcept nogil:
        return <uint16_t>_read_bits(self._p, 17, 12)

    cdef inline void _set_bi_tag(self, uint16_t v) noexcept nogil:
        _write_bits(self._p, 17, 12, v)

    @property
    def bi_tag(self):
        return self._get_bi_tag()

    @bi_tag.setter
    def bi_tag(self, v):
        self._set_bi_tag(<uint16_t>v)

    # ───── addr : bits 29-74 (46 b) ────────────────────────────────────────
    cdef inline uint64_t _get_addr(self) noexcept nogil:
        return <uint64_t>_read_bits(self._p, 29, 46)

    cdef inline void _set_addr(self, uint64_t v) noexcept nogil:
        _write_bits(self._p, 29, 46, v)

    @property
    def addr(self):
        return self._get_addr()

    @addr.setter
    def addr(self, v):
        self._set_addr(<uint64_t>v)

    # ───── rsvd : bits 75-79 (5 b) ─────────────────────────────────────────
    cdef inline uint8_t _get_rsvd(self) noexcept nogil:
        return (self._p[9] >> 3) & 0x1F

    cdef inline void _set_rsvd(self, uint8_t v) noexcept nogil:
        self._p[9] = (self._p[9] & 0x07) | ((v & 0x1F) << 3)

    @property
    def rsvd(self):
        return self._get_rsvd()

    @rsvd.setter
    def rsvd(self, v):
        self._set_rsvd(<uint8_t>v)

    # ───── misc helpers ────────────────────────────────────────────────────
    @classmethod
    def get_size(cls):
        return 10

    def __len__(self):
        return 10

    def __bytes__(self):
        return PyBytes_FromStringAndSize(<char*>self._p, 10)

# ───────────────────────────────────────────────────────────────────────────
#    CxlMemS2MNDRHeader  (5 bytes)
# ───────────────────────────────────────────────────────────────────────────
cdef class CxlMemS2MNDRHeader:
    __slots__ = ('_p')
    cdef uint8_t* _p

    def __cinit__(self):
        self._p = <uint8_t*>NULL  # NULL until first attach()

    cdef void attach(self, uint8_t* p) noexcept nogil:
        self._p = p

    # ───── valid : bit 0 (1 b) ─────────────────────────────────────────────
    cdef inline uint8_t _get_valid(self) noexcept nogil:
        return self._p[0] & 0x01

    cdef inline void _set_valid(self, uint8_t v) noexcept nogil:
        self._p[0] = (self._p[0] & 0xFE) | (v & 0x01)

    @property
    def valid(self):
        return self._get_valid()

    @valid.setter
    def valid(self, v):
        self._set_valid(<uint8_t>v)

    # ───── opcode : bits 1-3 (3 b) ─────────────────────────────────────────
    cdef inline uint8_t _get_opcode(self) noexcept nogil:
        return (self._p[0] >> 1) & 0x07

    cdef inline void _set_opcode(self, uint8_t v) noexcept nogil:
        self._p[0] = (self._p[0] & 0xF1) | ((v & 0x07) << 1)

    @property
    def opcode(self):
        return self._get_opcode()

    @opcode.setter
    def opcode(self, v):
        self._set_opcode(<uint8_t>v)

    # ───── meta_field : bits 4-5 (2 b) ─────────────────────────────────────
    cdef inline uint8_t _get_meta_field(self) noexcept nogil:
        return (self._p[0] >> 4) & 0x03

    cdef inline void _set_meta_field(self, uint8_t v) noexcept nogil:
        self._p[0] = (self._p[0] & 0xCF) | ((v & 0x03) << 4)

    @property
    def meta_field(self):
        return self._get_meta_field()

    @meta_field.setter
    def meta_field(self, v):
        self._set_meta_field(<uint8_t>v)

    # ───── meta_value : bits 6-7 (2 b) ─────────────────────────────────────
    cdef inline uint8_t _get_meta_value(self) noexcept nogil:
        return (self._p[0] >> 6) & 0x03

    cdef inline void _set_meta_value(self, uint8_t v) noexcept nogil:
        self._p[0] = (self._p[0] & 0x3F) | ((v & 0x03) << 6)

    @property
    def meta_value(self):
        return self._get_meta_value()

    @meta_value.setter
    def meta_value(self, v):
        self._set_meta_value(<uint8_t>v)

    # ───── tag : bits 8-23 (16 b) ──────────────────────────────────────────
    cdef inline uint16_t _get_tag(self) noexcept nogil:
        return <uint16_t>_read_bits(self._p, 8, 16)

    cdef inline void _set_tag(self, uint16_t v) noexcept nogil:
        _write_bits(self._p, 8, 16, v)

    @property
    def tag(self):
        return self._get_tag()

    @tag.setter
    def tag(self, v):
        self._set_tag(<uint16_t>v)

    # ───── ld_id : bits 24-27 (4 b) ────────────────────────────────────────
    cdef inline uint8_t _get_ld_id(self) noexcept nogil:
        return self._p[3] & 0x0F

    cdef inline void _set_ld_id(self, uint8_t v) noexcept nogil:
        self._p[3] = (self._p[3] & 0xF0) | (v & 0x0F)

    @property
    def ld_id(self):
        return self._get_ld_id()

    @ld_id.setter
    def ld_id(self, v):
        self._set_ld_id(<uint8_t>v)

    # ───── dev_load : bits 28-29 (2 b) ─────────────────────────────────────
    cdef inline uint8_t _get_dev_load(self) noexcept nogil:
        return (self._p[3] >> 4) & 0x03

    cdef inline void _set_dev_load(self, uint8_t v) noexcept nogil:
        self._p[3] = (self._p[3] & 0xCF) | ((v & 0x03) << 4)

    @property
    def dev_load(self):
        return self._get_dev_load()

    @dev_load.setter
    def dev_load(self, v):
        self._set_dev_load(<uint8_t>v)

    # ───── rsvd : bits 30-39 (10 b) ────────────────────────────────────────
    cdef inline uint16_t _get_rsvd(self) noexcept nogil:
        return <uint16_t>_read_bits(self._p, 30, 10)

    cdef inline void _set_rsvd(self, uint16_t v) noexcept nogil:
        _write_bits(self._p, 30, 10, v)

    @property
    def rsvd(self):
        return self._get_rsvd()

    @rsvd.setter
    def rsvd(self, v):
        self._set_rsvd(<uint16_t>v)

    # ───── misc helpers ────────────────────────────────────────────────────
    @classmethod
    def get_size(cls):
        return 5

    def __len__(self):
        return 5

    def __bytes__(self):
        return PyBytes_FromStringAndSize(<char*>self._p, 5)

# ───────────────────────────────────────────────────────────────────────────
#    CxlMemS2MDRSHeader  (5 bytes)
# ───────────────────────────────────────────────────────────────────────────
cdef class CxlMemS2MDRSHeader:
    __slots__ = ('_p')
    cdef uint8_t* _p

    def __cinit__(self):
        self._p = <uint8_t*>NULL  # NULL until first attach()

    cdef void attach(self, uint8_t* p) noexcept nogil:
        self._p = p

    # ───── valid : bit 0 (1 b) ─────────────────────────────────────────────
    cdef inline uint8_t _get_valid(self) noexcept nogil:
        return self._p[0] & 0x01

    cdef inline void _set_valid(self, uint8_t v) noexcept nogil:
        self._p[0] = (self._p[0] & 0xFE) | (v & 0x01)

    @property
    def valid(self):
        return self._get_valid()

    @valid.setter
    def valid(self, v):
        self._set_valid(<uint8_t>v)

    # ───── opcode : bits 1-3 (3 b) ─────────────────────────────────────────
    cdef inline uint8_t _get_opcode(self) noexcept nogil:
        return (self._p[0] >> 1) & 0x07

    cdef inline void _set_opcode(self, uint8_t v) noexcept nogil:
        self._p[0] = (self._p[0] & 0xF1) | ((v & 0x07) << 1)

    @property
    def opcode(self):
        return self._get_opcode()

    @opcode.setter
    def opcode(self, v):
        self._set_opcode(<uint8_t>v)

    # ───── meta_field : bits 4-5 (2 b) ─────────────────────────────────────
    cdef inline uint8_t _get_meta_field(self) noexcept nogil:
        return (self._p[0] >> 4) & 0x03

    cdef inline void _set_meta_field(self, uint8_t v) noexcept nogil:
        self._p[0] = (self._p[0] & 0xCF) | ((v & 0x03) << 4)

    @property
    def meta_field(self):
        return self._get_meta_field()

    @meta_field.setter
    def meta_field(self, v):
        self._set_meta_field(<uint8_t>v)

    # ───── meta_value : bits 6-7 (2 b) ─────────────────────────────────────
    cdef inline uint8_t _get_meta_value(self) noexcept nogil:
        return (self._p[0] >> 6) & 0x03

    cdef inline void _set_meta_value(self, uint8_t v) noexcept nogil:
        self._p[0] = (self._p[0] & 0x3F) | ((v & 0x03) << 6)

    @property
    def meta_value(self):
        return self._get_meta_value()

    @meta_value.setter
    def meta_value(self, v):
        self._set_meta_value(<uint8_t>v)

    # ───── tag : bits 8-23 (16 b) ──────────────────────────────────────────
    cdef inline uint16_t _get_tag(self) noexcept nogil:
        return <uint16_t>_read_bits(self._p, 8, 16)

    cdef inline void _set_tag(self, uint16_t v) noexcept nogil:
        _write_bits(self._p, 8, 16, v)

    @property
    def tag(self):
        return self._get_tag()

    @tag.setter
    def tag(self, v):
        self._set_tag(<uint16_t>v)

    # ───── poison : bit 24 (1 b) ───────────────────────────────────────────
    cdef inline uint8_t _get_poison(self) noexcept nogil:
        return self._p[3] & 0x01

    cdef inline void _set_poison(self, uint8_t v) noexcept nogil:
        self._p[3] = (self._p[3] & 0xFE) | (v & 0x01)

    @property
    def poison(self):
        return self._get_poison()

    @poison.setter
    def poison(self, v):
        self._set_poison(<uint8_t>v)

    # ───── ld_id : bits 25-28 (4 b) ────────────────────────────────────────
    cdef inline uint8_t _get_ld_id(self) noexcept nogil:
        return (self._p[3] >> 1) & 0x0F

    cdef inline void _set_ld_id(self, uint8_t v) noexcept nogil:
        self._p[3] = (self._p[3] & 0xE1) | ((v & 0x0F) << 1)

    @property
    def ld_id(self):
        return self._get_ld_id()

    @ld_id.setter
    def ld_id(self, v):
        self._set_ld_id(<uint8_t>v)

    # ───── dev_load : bits 29-30 (2 b) ─────────────────────────────────────
    cdef inline uint8_t _get_dev_load(self) noexcept nogil:
        return (self._p[3] >> 5) & 0x03

    cdef inline void _set_dev_load(self, uint8_t v) noexcept nogil:
        self._p[3] = (self._p[3] & 0x9F) | ((v & 0x03) << 5)

    @property
    def dev_load(self):
        return self._get_dev_load()

    @dev_load.setter
    def dev_load(self, v):
        self._set_dev_load(<uint8_t>v)

    # ───── rsvd : bits 31-39 (9 b) ─────────────────────────────────────────
    cdef inline uint16_t _get_rsvd(self) noexcept nogil:
        return <uint16_t>_read_bits(self._p, 31, 9)

    cdef inline void _set_rsvd(self, uint16_t v) noexcept nogil:
        _write_bits(self._p, 31, 9, v)

    @property
    def rsvd(self):
        return self._get_rsvd()

    @rsvd.setter
    def rsvd(self, v):
        self._set_rsvd(<uint16_t>v)

    # ───── misc helpers ────────────────────────────────────────────────────
    @classmethod
    def get_size(cls):
        return 5

    def __len__(self):
        return 5

    def __bytes__(self):
        return PyBytes_FromStringAndSize(<char*>self._p, 5)

# ───────────────────────────────────────────────────────────────────────────
#    CciHeader  (2 bytes)
# ───────────────────────────────────────────────────────────────────────────
cdef class CciHeader:
    __slots__ = ('_p')
    cdef uint8_t* _p

    def __cinit__(self):
        self._p = <uint8_t*>NULL  # NULL until first attach()

    cdef void attach(self, uint8_t* p) noexcept nogil:
        self._p = p

    # ───── port_index : bits 0-7 (8 b) ─────────────────────────────────────
    cdef inline uint8_t _get_port_index(self) noexcept nogil:
        return self._p[0]

    cdef inline void _set_port_index(self, uint8_t v) noexcept nogil:
        self._p[0] = v

    @property
    def port_index(self):
        return self._get_port_index()

    @port_index.setter
    def port_index(self, v):
        self._set_port_index(<uint8_t>v)

    # ───── msg_class : bits 8-15 (8 b) ─────────────────────────────────────
    cdef inline uint8_t _get_msg_class(self) noexcept nogil:
        return self._p[1]

    cdef inline void _set_msg_class(self, uint8_t v) noexcept nogil:
        self._p[1] = v

    @property
    def msg_class(self):
        return self._get_msg_class()

    @msg_class.setter
    def msg_class(self, v):
        self._set_msg_class(<uint8_t>v)

    # ───── misc helpers ────────────────────────────────────────────────────
    @classmethod
    def get_size(cls):
        return 2

    def __len__(self):
        return 2

    def __bytes__(self):
        return PyBytes_FromStringAndSize(<char*>self._p, 2)

# ───────────────────────────────────────────────────────────────────────────
#    CciMessageHeader  (12 bytes)
# ───────────────────────────────────────────────────────────────────────────
cdef class CciMessageHeader:
    __slots__ = ('_p')
    cdef uint8_t* _p

    def __cinit__(self):
        self._p = <uint8_t*>NULL  # NULL until first attach()

    cdef void attach(self, uint8_t* p) noexcept nogil:
        self._p = p

    # ───── message_category : bits 0-3 (4 b) ───────────────────────────────
    cdef inline uint8_t _get_message_category(self) noexcept nogil:
        return self._p[0] & 0x0F

    cdef inline void _set_message_category(self, uint8_t v) noexcept nogil:
        self._p[0] = (self._p[0] & 0xF0) | (v & 0x0F)

    @property
    def message_category(self):
        return self._get_message_category()

    @message_category.setter
    def message_category(self, v):
        self._set_message_category(<uint8_t>v)

    # ───── reserved0 : bits 4-7 (4 b) ──────────────────────────────────────
    cdef inline uint8_t _get_reserved0(self) noexcept nogil:
        return (self._p[0] >> 4) & 0x0F

    cdef inline void _set_reserved0(self, uint8_t v) noexcept nogil:
        self._p[0] = (self._p[0] & 0x0F) | ((v & 0x0F) << 4)

    @property
    def reserved0(self):
        return self._get_reserved0()

    @reserved0.setter
    def reserved0(self, v):
        self._set_reserved0(<uint8_t>v)

    # ───── message_tag : bits 8-15 (8 b) ───────────────────────────────────
    cdef inline uint8_t _get_message_tag(self) noexcept nogil:
        return self._p[1]

    cdef inline void _set_message_tag(self, uint8_t v) noexcept nogil:
        self._p[1] = v

    @property
    def message_tag(self):
        return self._get_message_tag()

    @message_tag.setter
    def message_tag(self, v):
        self._set_message_tag(<uint8_t>v)

    # ───── reserved1 : bits 16-23 (8 b) ────────────────────────────────────
    cdef inline uint8_t _get_reserved1(self) noexcept nogil:
        return self._p[2]

    cdef inline void _set_reserved1(self, uint8_t v) noexcept nogil:
        self._p[2] = v

    @property
    def reserved1(self):
        return self._get_reserved1()

    @reserved1.setter
    def reserved1(self, v):
        self._set_reserved1(<uint8_t>v)

    # ───── command_opcode : bits 24-39 (16 b) ──────────────────────────────
    cdef inline uint16_t _get_command_opcode(self) noexcept nogil:
        return <uint16_t>_read_bits(self._p, 24, 16)

    cdef inline void _set_command_opcode(self, uint16_t v) noexcept nogil:
        _write_bits(self._p, 24, 16, v)

    @property
    def command_opcode(self):
        return self._get_command_opcode()

    @command_opcode.setter
    def command_opcode(self, v):
        self._set_command_opcode(<uint16_t>v)

    # ───── message_payload_length_low : bits 40-55 (16 b) ──────────────────
    cdef inline uint16_t _get_message_payload_length_low(self) noexcept nogil:
        return <uint16_t>_read_bits(self._p, 40, 16)

    cdef inline void _set_message_payload_length_low(self, uint16_t v) noexcept nogil:
        _write_bits(self._p, 40, 16, v)

    @property
    def message_payload_length_low(self):
        return self._get_message_payload_length_low()

    @message_payload_length_low.setter
    def message_payload_length_low(self, v):
        self._set_message_payload_length_low(<uint16_t>v)

    # ───── message_payload_length_high : bits 56-60 (5 b) ──────────────────
    cdef inline uint8_t _get_message_payload_length_high(self) noexcept nogil:
        return self._p[7] & 0x1F

    cdef inline void _set_message_payload_length_high(self, uint8_t v) noexcept nogil:
        self._p[7] = (self._p[7] & 0xE0) | (v & 0x1F)

    @property
    def message_payload_length_high(self):
        return self._get_message_payload_length_high()

    @message_payload_length_high.setter
    def message_payload_length_high(self, v):
        self._set_message_payload_length_high(<uint8_t>v)

    # ───── reserved2 : bits 61-62 (2 b) ────────────────────────────────────
    cdef inline uint8_t _get_reserved2(self) noexcept nogil:
        return (self._p[7] >> 5) & 0x03

    cdef inline void _set_reserved2(self, uint8_t v) noexcept nogil:
        self._p[7] = (self._p[7] & 0x9F) | ((v & 0x03) << 5)

    @property
    def reserved2(self):
        return self._get_reserved2()

    @reserved2.setter
    def reserved2(self, v):
        self._set_reserved2(<uint8_t>v)

    # ───── background_operation : bit 63 (1 b) ─────────────────────────────
    cdef inline uint8_t _get_background_operation(self) noexcept nogil:
        return (self._p[7] >> 7) & 0x01

    cdef inline void _set_background_operation(self, uint8_t v) noexcept nogil:
        self._p[7] = (self._p[7] & 0x7F) | ((v & 0x01) << 7)

    @property
    def background_operation(self):
        return self._get_background_operation()

    @background_operation.setter
    def background_operation(self, v):
        self._set_background_operation(<uint8_t>v)

    # ───── return_code : bits 64-79 (16 b) ─────────────────────────────────
    cdef inline uint16_t _get_return_code(self) noexcept nogil:
        return <uint16_t>_read_bits(self._p, 64, 16)

    cdef inline void _set_return_code(self, uint16_t v) noexcept nogil:
        _write_bits(self._p, 64, 16, v)

    @property
    def return_code(self):
        return self._get_return_code()

    @return_code.setter
    def return_code(self, v):
        self._set_return_code(<uint16_t>v)

    # ───── vendor_specific_extended_status : bits 80-95 (16 b) ─────────────
    cdef inline uint16_t _get_vendor_specific_extended_status(self) noexcept nogil:
        return <uint16_t>_read_bits(self._p, 80, 16)

    cdef inline void _set_vendor_specific_extended_status(self, uint16_t v) noexcept nogil:
        _write_bits(self._p, 80, 16, v)

    @property
    def vendor_specific_extended_status(self):
        return self._get_vendor_specific_extended_status()

    @vendor_specific_extended_status.setter
    def vendor_specific_extended_status(self, v):
        self._set_vendor_specific_extended_status(<uint16_t>v)

    # ───── misc helpers ────────────────────────────────────────────────────
    @classmethod
    def get_size(cls):
        return 12

    def __len__(self):
        return 12

    def __bytes__(self):
        return PyBytes_FromStringAndSize(<char*>self._p, 12)

cdef PoolStruct __GenBasePacket_pool

cdef class _GenBasePacket:
    # class member vars
    cdef SystemHeader _system_header
    cdef unsigned char _buf[MAX_PACKET_SIZE]
    cdef int _data_length

    #────────────────── Life-cycle management ──────────────────
    cdef void _release(self):
        pool_push(&__GenBasePacket_pool, <PyObject*> self)

    cdef inline void _relocate(self) noexcept nogil:
        cdef unsigned char* base = &self._buf[0]
        self._system_header.attach(base + 0)

    #─────────────────────── Builder ───────────────────────
    def __cinit__(self, payload=None):
        if not hasattr(self, '_data_length'):
            # first time only: allocate sub-headers
            self._data_length = 0
            self._system_header = SystemHeader()
            self._relocate()
            Py_INCREF(self)

        if payload is not None:
            src = <const unsigned char*> payload
            dst = &self._buf[0]
            n = len(payload)
            if n > MAX_PACKET_SIZE:
                raise ValueError("packet too large")
            memcpy(dst, src, n)
            self._data_length = n - 2

    #────────────────── Python Interface ──────────────────
    cpdef set_data(self, data):
        src = <const unsigned char*> data
        dst = &self._buf[2]
        n = len(data)
        if 2 + n > MAX_PACKET_SIZE:
            raise ValueError("packet too large")
        memcpy(dst, src, n)
        self._data_length = n

    cpdef get_data(self):
        return PyBytes_FromStringAndSize(<char*>&self._buf[2], self._data_length)

    cpdef int get_payload_offset(self):
       return 2

    cpdef int get_byte_offset(self, object other):
        cdef uint8_t* base_ptr  = &self._buf[0]
        cdef uint8_t* other_ptr = NULL
        if isinstance(other, SystemHeader):
            other_ptr = (<SystemHeader> other)._p
        else:
            raise TypeError(f"unsupported header type: {type(other)}")
        return <int>(other_ptr - base_ptr)

    cpdef void set_bytes(self, int offset, object data):
        cdef const unsigned char[::1] view = data
        cdef int i
        for i in range(view.shape[0]):
            self._buf[offset + i] = view[i]

    cpdef void write_bits(self, int start_bit, int width, unsigned long long value):
        _write_bits(&self._buf[0], start_bit, width, value)

    cpdef unsigned long long read_bits(self, int start_bit, int width):
        return _read_bits(&self._buf[0], start_bit, width)

    cpdef get_bytes(self, int start, int length):
        return PyBytes_FromStringAndSize(<char*>&self._buf[start], length)

    #──────────────────── Header accessors ────────────────────
    @property
    def system_header(self):
        return self._system_header

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._release()

    def __del__(self):
        self._release()

    def __len__(self):
        return 2 + self._data_length

    def __bytes__(self):
        return PyBytes_FromStringAndSize(<char *> self._buf, 2 + self._data_length)

cdef PoolStruct __GenBaseSidebandPacket_pool

cdef class _GenBaseSidebandPacket:
    # class member vars
    cdef SystemHeader _system_header
    cdef SidebandHeader _sideband_header
    cdef unsigned char _buf[MAX_PACKET_SIZE]
    cdef int _data_length

    #────────────────── Life-cycle management ──────────────────
    cdef void _release(self):
        pool_push(&__GenBaseSidebandPacket_pool, <PyObject*> self)

    cdef inline void _relocate(self) noexcept nogil:
        cdef unsigned char* base = &self._buf[0]
        self._system_header.attach(base + 0)
        self._sideband_header.attach(base + 2)

    #─────────────────────── Builder ───────────────────────
    def __cinit__(self, payload=None):
        if not hasattr(self, '_data_length'):
            # first time only: allocate sub-headers
            self._data_length = 0
            self._system_header = SystemHeader()
            self._sideband_header = SidebandHeader()
            self._relocate()
            Py_INCREF(self)

        if payload is not None:
            src = <const unsigned char*> payload
            dst = &self._buf[0]
            n = len(payload)
            if n > MAX_PACKET_SIZE:
                raise ValueError("packet too large")
            memcpy(dst, src, n)
            self._data_length = n - 3

    #────────────────── Python Interface ──────────────────
    cpdef set_data(self, data):
        src = <const unsigned char*> data
        dst = &self._buf[3]
        n = len(data)
        if 3 + n > MAX_PACKET_SIZE:
            raise ValueError("packet too large")
        memcpy(dst, src, n)
        self._data_length = n

    cpdef get_data(self):
        return PyBytes_FromStringAndSize(<char*>&self._buf[3], self._data_length)

    cpdef int get_payload_offset(self):
       return 3

    cpdef int get_byte_offset(self, object other):
        cdef uint8_t* base_ptr  = &self._buf[0]
        cdef uint8_t* other_ptr = NULL
        if isinstance(other, SystemHeader):
            other_ptr = (<SystemHeader> other)._p
        elif isinstance(other, SidebandHeader):
            other_ptr = (<SidebandHeader> other)._p
        else:
            raise TypeError(f"unsupported header type: {type(other)}")
        return <int>(other_ptr - base_ptr)

    cpdef void set_bytes(self, int offset, object data):
        cdef const unsigned char[::1] view = data
        cdef int i
        for i in range(view.shape[0]):
            self._buf[offset + i] = view[i]

    cpdef void write_bits(self, int start_bit, int width, unsigned long long value):
        _write_bits(&self._buf[0], start_bit, width, value)

    cpdef unsigned long long read_bits(self, int start_bit, int width):
        return _read_bits(&self._buf[0], start_bit, width)

    cpdef get_bytes(self, int start, int length):
        return PyBytes_FromStringAndSize(<char*>&self._buf[start], length)

    #──────────────────── Header accessors ────────────────────
    @property
    def system_header(self):
        return self._system_header

    @property
    def sideband_header(self):
        return self._sideband_header

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._release()

    def __del__(self):
        self._release()

    def __len__(self):
        return 3 + self._data_length

    def __bytes__(self):
        return PyBytes_FromStringAndSize(<char *> self._buf, 3 + self._data_length)

cdef PoolStruct __GenSidebandConnectionRequestPacket_pool

cdef class _GenSidebandConnectionRequestPacket:
    # class member vars
    cdef SystemHeader _system_header
    cdef SidebandHeader _sideband_header
    cdef unsigned char _buf[MAX_PACKET_SIZE]
    cdef int _data_length

    #────────────────── Life-cycle management ──────────────────
    cdef void _release(self):
        pool_push(&__GenSidebandConnectionRequestPacket_pool, <PyObject*> self)

    cdef inline void _relocate(self) noexcept nogil:
        cdef unsigned char* base = &self._buf[0]
        self._system_header.attach(base + 0)
        self._sideband_header.attach(base + 2)

    #─────────────────────── Builder ───────────────────────
    def __cinit__(self, payload=None):
        if not hasattr(self, '_data_length'):
            # first time only: allocate sub-headers
            self._data_length = 0
            self._system_header = SystemHeader()
            self._sideband_header = SidebandHeader()
            self._relocate()
            Py_INCREF(self)

        if payload is not None:
            src = <const unsigned char*> payload
            dst = &self._buf[0]
            n = len(payload)
            if n > MAX_PACKET_SIZE:
                raise ValueError("packet too large")
            memcpy(dst, src, n)
            self._data_length = n - 3

    #────────────────── Python Interface ──────────────────
    cpdef set_data(self, data):
        src = <const unsigned char*> data
        dst = &self._buf[3]
        n = len(data)
        if 3 + n > MAX_PACKET_SIZE:
            raise ValueError("packet too large")
        memcpy(dst, src, n)
        self._data_length = n

    cpdef get_data(self):
        return PyBytes_FromStringAndSize(<char*>&self._buf[3], self._data_length)

    cpdef int get_payload_offset(self):
       return 3

    cpdef int get_byte_offset(self, object other):
        cdef uint8_t* base_ptr  = &self._buf[0]
        cdef uint8_t* other_ptr = NULL
        if isinstance(other, SystemHeader):
            other_ptr = (<SystemHeader> other)._p
        elif isinstance(other, SidebandHeader):
            other_ptr = (<SidebandHeader> other)._p
        else:
            raise TypeError(f"unsupported header type: {type(other)}")
        return <int>(other_ptr - base_ptr)

    cpdef void set_bytes(self, int offset, object data):
        cdef const unsigned char[::1] view = data
        cdef int i
        for i in range(view.shape[0]):
            self._buf[offset + i] = view[i]

    cpdef void write_bits(self, int start_bit, int width, unsigned long long value):
        _write_bits(&self._buf[0], start_bit, width, value)

    cpdef unsigned long long read_bits(self, int start_bit, int width):
        return _read_bits(&self._buf[0], start_bit, width)

    cpdef get_bytes(self, int start, int length):
        return PyBytes_FromStringAndSize(<char*>&self._buf[start], length)

    #──────────────────── Header accessors ────────────────────
    @property
    def system_header(self):
        return self._system_header

    @property
    def sideband_header(self):
        return self._sideband_header

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._release()

    def __del__(self):
        self._release()

    def __len__(self):
        return 3 + self._data_length

    def __bytes__(self):
        return PyBytes_FromStringAndSize(<char *> self._buf, 3 + self._data_length)

cdef PoolStruct __GenCxlIoBasePacket_pool

cdef class _GenCxlIoBasePacket:
    # class member vars
    cdef SystemHeader _system_header
    cdef TlpPrefix _tlp_prefix
    cdef CxlIoHeader _cxl_io_header
    cdef unsigned char _buf[MAX_PACKET_SIZE]
    cdef int _data_length

    #────────────────── Life-cycle management ──────────────────
    cdef void _release(self):
        pool_push(&__GenCxlIoBasePacket_pool, <PyObject*> self)

    cdef inline void _relocate(self) noexcept nogil:
        cdef unsigned char* base = &self._buf[0]
        self._system_header.attach(base + 0)
        self._tlp_prefix.attach(base + 2)
        self._cxl_io_header.attach(base + 6)

    #─────────────────────── Builder ───────────────────────
    def __cinit__(self, payload=None):
        if not hasattr(self, '_data_length'):
            # first time only: allocate sub-headers
            self._data_length = 0
            self._system_header = SystemHeader()
            self._tlp_prefix = TlpPrefix()
            self._cxl_io_header = CxlIoHeader()
            self._relocate()
            Py_INCREF(self)

        if payload is not None:
            src = <const unsigned char*> payload
            dst = &self._buf[0]
            n = len(payload)
            if n > MAX_PACKET_SIZE:
                raise ValueError("packet too large")
            memcpy(dst, src, n)
            self._data_length = n - 10

    #────────────────── Python Interface ──────────────────
    cpdef set_data(self, data):
        src = <const unsigned char*> data
        dst = &self._buf[10]
        n = len(data)
        if 10 + n > MAX_PACKET_SIZE:
            raise ValueError("packet too large")
        memcpy(dst, src, n)
        self._data_length = n

    cpdef get_data(self):
        return PyBytes_FromStringAndSize(<char*>&self._buf[10], self._data_length)

    cpdef int get_payload_offset(self):
       return 10

    cpdef int get_byte_offset(self, object other):
        cdef uint8_t* base_ptr  = &self._buf[0]
        cdef uint8_t* other_ptr = NULL
        if isinstance(other, SystemHeader):
            other_ptr = (<SystemHeader> other)._p
        elif isinstance(other, TlpPrefix):
            other_ptr = (<TlpPrefix> other)._p
        elif isinstance(other, CxlIoHeader):
            other_ptr = (<CxlIoHeader> other)._p
        else:
            raise TypeError(f"unsupported header type: {type(other)}")
        return <int>(other_ptr - base_ptr)

    cpdef void set_bytes(self, int offset, object data):
        cdef const unsigned char[::1] view = data
        cdef int i
        for i in range(view.shape[0]):
            self._buf[offset + i] = view[i]

    cpdef void write_bits(self, int start_bit, int width, unsigned long long value):
        _write_bits(&self._buf[0], start_bit, width, value)

    cpdef unsigned long long read_bits(self, int start_bit, int width):
        return _read_bits(&self._buf[0], start_bit, width)

    cpdef get_bytes(self, int start, int length):
        return PyBytes_FromStringAndSize(<char*>&self._buf[start], length)

    #──────────────────── Header accessors ────────────────────
    @property
    def system_header(self):
        return self._system_header

    @property
    def tlp_prefix(self):
        return self._tlp_prefix

    @property
    def cxl_io_header(self):
        return self._cxl_io_header

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._release()

    def __del__(self):
        self._release()

    def __len__(self):
        return 10 + self._data_length

    def __bytes__(self):
        return PyBytes_FromStringAndSize(<char *> self._buf, 10 + self._data_length)

cdef PoolStruct __GenCxlIoMemRdPacket_pool

cdef class _GenCxlIoMemRdPacket:
    # class member vars
    cdef SystemHeader _system_header
    cdef TlpPrefix _tlp_prefix
    cdef CxlIoHeader _cxl_io_header
    cdef CxlIoMReqHeader _mreq_header
    cdef unsigned char _buf[MAX_PACKET_SIZE]
    cdef int _data_length

    #────────────────── Life-cycle management ──────────────────
    cdef void _release(self):
        pool_push(&__GenCxlIoMemRdPacket_pool, <PyObject*> self)

    cdef inline void _relocate(self) noexcept nogil:
        cdef unsigned char* base = &self._buf[0]
        self._system_header.attach(base + 0)
        self._tlp_prefix.attach(base + 2)
        self._cxl_io_header.attach(base + 6)
        self._mreq_header.attach(base + 10)

    #─────────────────────── Builder ───────────────────────
    def __cinit__(self, payload=None):
        if not hasattr(self, '_data_length'):
            # first time only: allocate sub-headers
            self._data_length = 0
            self._system_header = SystemHeader()
            self._tlp_prefix = TlpPrefix()
            self._cxl_io_header = CxlIoHeader()
            self._mreq_header = CxlIoMReqHeader()
            self._relocate()
            Py_INCREF(self)

        if payload is not None:
            src = <const unsigned char*> payload
            dst = &self._buf[0]
            n = len(payload)
            if n > MAX_PACKET_SIZE:
                raise ValueError("packet too large")
            memcpy(dst, src, n)
            self._data_length = n - 22

    cdef inline void _build(
        self,
        int system_header__payload_type,
        int tlp_prefix__ld_id,
        int cxl_io_header__fmt_type,
        int cxl_io_header__length_upper,
        int cxl_io_header__length_lower,
        int mreq_header__req_id,
        int mreq_header__tag,
        int mreq_header__first_dw_be,
        int mreq_header__last_dw_be,
        unsigned long long mreq_header__addr_upper,
        int mreq_header__addr_lower,
        const unsigned char* data_src,
        Py_ssize_t data_length
    ) noexcept nogil:
        cdef unsigned char* dst

        memset(&self._buf[0], 0, MAX_PACKET_SIZE)
        self._system_header._set_payload_type(system_header__payload_type)
        self._tlp_prefix._set_ld_id(tlp_prefix__ld_id)
        self._cxl_io_header._set_fmt_type(cxl_io_header__fmt_type)
        self._cxl_io_header._set_length_upper(cxl_io_header__length_upper)
        self._cxl_io_header._set_length_lower(cxl_io_header__length_lower)
        self._mreq_header._set_req_id(mreq_header__req_id)
        self._mreq_header._set_tag(mreq_header__tag)
        self._mreq_header._set_first_dw_be(mreq_header__first_dw_be)
        self._mreq_header._set_last_dw_be(mreq_header__last_dw_be)
        self._mreq_header._set_addr_upper(mreq_header__addr_upper)
        self._mreq_header._set_addr_lower(mreq_header__addr_lower)
        if data_src:
            dst = &self._buf[22]
            if data_length > MAX_PACKET_SIZE - 22:
                raise ValueError("data too large")
            memcpy(dst, data_src, data_length)
            self._data_length = data_length
        self._system_header._set_payload_length(22 + data_length)

    #────────────────── Python Interface ──────────────────
    @classmethod
    def create(
        cls,
        system_header__payload_type,
        tlp_prefix__ld_id,
        cxl_io_header__fmt_type,
        cxl_io_header__length_upper,
        cxl_io_header__length_lower,
        mreq_header__req_id,
        mreq_header__tag,
        mreq_header__first_dw_be,
        mreq_header__last_dw_be,
        mreq_header__addr_upper,
        mreq_header__addr_lower,
        data: bytes | None = None,
    ):
        cdef PyObject *tmp
        cdef _GenCxlIoMemRdPacket pkt
        cdef Py_ssize_t data_length
        cdef const unsigned char* ptr

        if data:
            data_length = len(data)
            ptr = data
        else:
            data_length = 0
            ptr = NULL

        tmp = pool_pop(&__GenCxlIoMemRdPacket_pool)
        if tmp == NULL:
            pkt = cls()
        else:
            pkt = <_GenCxlIoMemRdPacket> tmp

        pkt._relocate()
        pkt._build(
            system_header__payload_type,
            tlp_prefix__ld_id,
            cxl_io_header__fmt_type,
            cxl_io_header__length_upper,
            cxl_io_header__length_lower,
            mreq_header__req_id,
            mreq_header__tag,
            mreq_header__first_dw_be,
            mreq_header__last_dw_be,
            mreq_header__addr_upper,
            mreq_header__addr_lower, 
            ptr,
            data_length,
        )
        return pkt

    def assign(
        self,
        system_header__payload_type,
        tlp_prefix__ld_id,
        cxl_io_header__fmt_type,
        cxl_io_header__length_upper,
        cxl_io_header__length_lower,
        mreq_header__req_id,
        mreq_header__tag,
        mreq_header__first_dw_be,
        mreq_header__last_dw_be,
        mreq_header__addr_upper,
        mreq_header__addr_lower,
        data: bytes | None = None,
    ):
        cdef Py_ssize_t data_length
        cdef const unsigned char* ptr

        if data:
            data_length = len(data)
            ptr = data
        else:
            data_length = 0
            ptr = NULL

        self._relocate()
        self._build(
            system_header__payload_type,
            tlp_prefix__ld_id,
            cxl_io_header__fmt_type,
            cxl_io_header__length_upper,
            cxl_io_header__length_lower,
            mreq_header__req_id,
            mreq_header__tag,
            mreq_header__first_dw_be,
            mreq_header__last_dw_be,
            mreq_header__addr_upper,
            mreq_header__addr_lower, 
            ptr,
            data_length,
        )

    cpdef set_data(self, data):
        src = <const unsigned char*> data
        dst = &self._buf[22]
        n = len(data)
        if 22 + n > MAX_PACKET_SIZE:
            raise ValueError("packet too large")
        memcpy(dst, src, n)
        self._data_length = n

    cpdef get_data(self):
        return PyBytes_FromStringAndSize(<char*>&self._buf[22], self._data_length)

    cpdef int get_payload_offset(self):
       return 22

    cpdef int get_byte_offset(self, object other):
        cdef uint8_t* base_ptr  = &self._buf[0]
        cdef uint8_t* other_ptr = NULL
        if isinstance(other, SystemHeader):
            other_ptr = (<SystemHeader> other)._p
        elif isinstance(other, TlpPrefix):
            other_ptr = (<TlpPrefix> other)._p
        elif isinstance(other, CxlIoHeader):
            other_ptr = (<CxlIoHeader> other)._p
        elif isinstance(other, CxlIoMReqHeader):
            other_ptr = (<CxlIoMReqHeader> other)._p
        else:
            raise TypeError(f"unsupported header type: {type(other)}")
        return <int>(other_ptr - base_ptr)

    cpdef void set_bytes(self, int offset, object data):
        cdef const unsigned char[::1] view = data
        cdef int i
        for i in range(view.shape[0]):
            self._buf[offset + i] = view[i]

    cpdef void write_bits(self, int start_bit, int width, unsigned long long value):
        _write_bits(&self._buf[0], start_bit, width, value)

    cpdef unsigned long long read_bits(self, int start_bit, int width):
        return _read_bits(&self._buf[0], start_bit, width)

    cpdef get_bytes(self, int start, int length):
        return PyBytes_FromStringAndSize(<char*>&self._buf[start], length)

    #──────────────────── Header accessors ────────────────────
    @property
    def system_header(self):
        return self._system_header

    @property
    def tlp_prefix(self):
        return self._tlp_prefix

    @property
    def cxl_io_header(self):
        return self._cxl_io_header

    @property
    def mreq_header(self):
        return self._mreq_header

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._release()

    def __del__(self):
        self._release()

    def __len__(self):
        return 22 + self._data_length

    def __bytes__(self):
        return PyBytes_FromStringAndSize(<char *> self._buf, 22 + self._data_length)

cdef PoolStruct __GenCxlIoMemWrPacket_pool

cdef class _GenCxlIoMemWrPacket:
    # class member vars
    cdef SystemHeader _system_header
    cdef TlpPrefix _tlp_prefix
    cdef CxlIoHeader _cxl_io_header
    cdef CxlIoMReqHeader _mreq_header
    cdef unsigned char _buf[MAX_PACKET_SIZE]
    cdef int _data_length

    #────────────────── Life-cycle management ──────────────────
    cdef void _release(self):
        pool_push(&__GenCxlIoMemWrPacket_pool, <PyObject*> self)

    cdef inline void _relocate(self) noexcept nogil:
        cdef unsigned char* base = &self._buf[0]
        self._system_header.attach(base + 0)
        self._tlp_prefix.attach(base + 2)
        self._cxl_io_header.attach(base + 6)
        self._mreq_header.attach(base + 10)

    #─────────────────────── Builder ───────────────────────
    def __cinit__(self, payload=None):
        if not hasattr(self, '_data_length'):
            # first time only: allocate sub-headers
            self._data_length = 0
            self._system_header = SystemHeader()
            self._tlp_prefix = TlpPrefix()
            self._cxl_io_header = CxlIoHeader()
            self._mreq_header = CxlIoMReqHeader()
            self._relocate()
            Py_INCREF(self)

        if payload is not None:
            src = <const unsigned char*> payload
            dst = &self._buf[0]
            n = len(payload)
            if n > MAX_PACKET_SIZE:
                raise ValueError("packet too large")
            memcpy(dst, src, n)
            self._data_length = n - 22

    cdef inline void _build(
        self,
        int system_header__payload_type,
        int tlp_prefix__ld_id,
        int cxl_io_header__fmt_type,
        int cxl_io_header__length_upper,
        int cxl_io_header__length_lower,
        int mreq_header__req_id,
        int mreq_header__tag,
        int mreq_header__first_dw_be,
        int mreq_header__last_dw_be,
        unsigned long long mreq_header__addr_upper,
        int mreq_header__addr_lower,
        const unsigned char* data_src,
        Py_ssize_t data_length
    ) noexcept nogil:
        cdef unsigned char* dst

        memset(&self._buf[0], 0, MAX_PACKET_SIZE)
        self._system_header._set_payload_type(system_header__payload_type)
        self._tlp_prefix._set_ld_id(tlp_prefix__ld_id)
        self._cxl_io_header._set_fmt_type(cxl_io_header__fmt_type)
        self._cxl_io_header._set_length_upper(cxl_io_header__length_upper)
        self._cxl_io_header._set_length_lower(cxl_io_header__length_lower)
        self._mreq_header._set_req_id(mreq_header__req_id)
        self._mreq_header._set_tag(mreq_header__tag)
        self._mreq_header._set_first_dw_be(mreq_header__first_dw_be)
        self._mreq_header._set_last_dw_be(mreq_header__last_dw_be)
        self._mreq_header._set_addr_upper(mreq_header__addr_upper)
        self._mreq_header._set_addr_lower(mreq_header__addr_lower)
        if data_src:
            dst = &self._buf[22]
            if data_length > MAX_PACKET_SIZE - 22:
                raise ValueError("data too large")
            memcpy(dst, data_src, data_length)
            self._data_length = data_length
        self._system_header._set_payload_length(22 + data_length)

    #────────────────── Python Interface ──────────────────
    @classmethod
    def create(
        cls,
        system_header__payload_type,
        tlp_prefix__ld_id,
        cxl_io_header__fmt_type,
        cxl_io_header__length_upper,
        cxl_io_header__length_lower,
        mreq_header__req_id,
        mreq_header__tag,
        mreq_header__first_dw_be,
        mreq_header__last_dw_be,
        mreq_header__addr_upper,
        mreq_header__addr_lower,
        data: bytes | None = None,
    ):
        cdef PyObject *tmp
        cdef _GenCxlIoMemWrPacket pkt
        cdef Py_ssize_t data_length
        cdef const unsigned char* ptr

        if data:
            data_length = len(data)
            ptr = data
        else:
            data_length = 0
            ptr = NULL

        tmp = pool_pop(&__GenCxlIoMemWrPacket_pool)
        if tmp == NULL:
            pkt = cls()
        else:
            pkt = <_GenCxlIoMemWrPacket> tmp

        pkt._relocate()
        pkt._build(
            system_header__payload_type,
            tlp_prefix__ld_id,
            cxl_io_header__fmt_type,
            cxl_io_header__length_upper,
            cxl_io_header__length_lower,
            mreq_header__req_id,
            mreq_header__tag,
            mreq_header__first_dw_be,
            mreq_header__last_dw_be,
            mreq_header__addr_upper,
            mreq_header__addr_lower, 
            ptr,
            data_length,
        )
        return pkt

    def assign(
        self,
        system_header__payload_type,
        tlp_prefix__ld_id,
        cxl_io_header__fmt_type,
        cxl_io_header__length_upper,
        cxl_io_header__length_lower,
        mreq_header__req_id,
        mreq_header__tag,
        mreq_header__first_dw_be,
        mreq_header__last_dw_be,
        mreq_header__addr_upper,
        mreq_header__addr_lower,
        data: bytes | None = None,
    ):
        cdef Py_ssize_t data_length
        cdef const unsigned char* ptr

        if data:
            data_length = len(data)
            ptr = data
        else:
            data_length = 0
            ptr = NULL

        self._relocate()
        self._build(
            system_header__payload_type,
            tlp_prefix__ld_id,
            cxl_io_header__fmt_type,
            cxl_io_header__length_upper,
            cxl_io_header__length_lower,
            mreq_header__req_id,
            mreq_header__tag,
            mreq_header__first_dw_be,
            mreq_header__last_dw_be,
            mreq_header__addr_upper,
            mreq_header__addr_lower, 
            ptr,
            data_length,
        )

    cpdef set_data(self, data):
        src = <const unsigned char*> data
        dst = &self._buf[22]
        n = len(data)
        if 22 + n > MAX_PACKET_SIZE:
            raise ValueError("packet too large")
        memcpy(dst, src, n)
        self._data_length = n

    cpdef get_data(self):
        return PyBytes_FromStringAndSize(<char*>&self._buf[22], self._data_length)

    cpdef int get_payload_offset(self):
       return 22

    cpdef int get_byte_offset(self, object other):
        cdef uint8_t* base_ptr  = &self._buf[0]
        cdef uint8_t* other_ptr = NULL
        if isinstance(other, SystemHeader):
            other_ptr = (<SystemHeader> other)._p
        elif isinstance(other, TlpPrefix):
            other_ptr = (<TlpPrefix> other)._p
        elif isinstance(other, CxlIoHeader):
            other_ptr = (<CxlIoHeader> other)._p
        elif isinstance(other, CxlIoMReqHeader):
            other_ptr = (<CxlIoMReqHeader> other)._p
        else:
            raise TypeError(f"unsupported header type: {type(other)}")
        return <int>(other_ptr - base_ptr)

    cpdef void set_bytes(self, int offset, object data):
        cdef const unsigned char[::1] view = data
        cdef int i
        for i in range(view.shape[0]):
            self._buf[offset + i] = view[i]

    cpdef void write_bits(self, int start_bit, int width, unsigned long long value):
        _write_bits(&self._buf[0], start_bit, width, value)

    cpdef unsigned long long read_bits(self, int start_bit, int width):
        return _read_bits(&self._buf[0], start_bit, width)

    cpdef get_bytes(self, int start, int length):
        return PyBytes_FromStringAndSize(<char*>&self._buf[start], length)

    #──────────────────── Header accessors ────────────────────
    @property
    def system_header(self):
        return self._system_header

    @property
    def tlp_prefix(self):
        return self._tlp_prefix

    @property
    def cxl_io_header(self):
        return self._cxl_io_header

    @property
    def mreq_header(self):
        return self._mreq_header

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._release()

    def __del__(self):
        self._release()

    def __len__(self):
        return 22 + self._data_length

    def __bytes__(self):
        return PyBytes_FromStringAndSize(<char *> self._buf, 22 + self._data_length)

cdef PoolStruct __GenCxlIoCfgRdPacket_pool

cdef class _GenCxlIoCfgRdPacket:
    # class member vars
    cdef SystemHeader _system_header
    cdef TlpPrefix _tlp_prefix
    cdef CxlIoHeader _cxl_io_header
    cdef CxlIoCfgReqHeader _cfg_req_header
    cdef unsigned char _buf[MAX_PACKET_SIZE]
    cdef int _data_length

    #────────────────── Life-cycle management ──────────────────
    cdef void _release(self):
        pool_push(&__GenCxlIoCfgRdPacket_pool, <PyObject*> self)

    cdef inline void _relocate(self) noexcept nogil:
        cdef unsigned char* base = &self._buf[0]
        self._system_header.attach(base + 0)
        self._tlp_prefix.attach(base + 2)
        self._cxl_io_header.attach(base + 6)
        self._cfg_req_header.attach(base + 10)

    #─────────────────────── Builder ───────────────────────
    def __cinit__(self, payload=None):
        if not hasattr(self, '_data_length'):
            # first time only: allocate sub-headers
            self._data_length = 0
            self._system_header = SystemHeader()
            self._tlp_prefix = TlpPrefix()
            self._cxl_io_header = CxlIoHeader()
            self._cfg_req_header = CxlIoCfgReqHeader()
            self._relocate()
            Py_INCREF(self)

        if payload is not None:
            src = <const unsigned char*> payload
            dst = &self._buf[0]
            n = len(payload)
            if n > MAX_PACKET_SIZE:
                raise ValueError("packet too large")
            memcpy(dst, src, n)
            self._data_length = n - 18

    cdef inline void _build(
        self,
        int system_header__payload_type,
        int tlp_prefix__ld_id,
        int cxl_io_header__fmt_type,
        int cxl_io_header__length_upper,
        int cxl_io_header__length_lower,
        int cfg_req_header__req_id,
        int cfg_req_header__tag,
        int cfg_req_header__first_dw_be,
        int cfg_req_header__last_dw_be,
        int cfg_req_header__dest_id,
        int cfg_req_header__ext_reg_num,
        int cfg_req_header__reg_num,
        const unsigned char* data_src,
        Py_ssize_t data_length
    ) noexcept nogil:
        cdef unsigned char* dst

        memset(&self._buf[0], 0, MAX_PACKET_SIZE)
        self._system_header._set_payload_type(system_header__payload_type)
        self._tlp_prefix._set_ld_id(tlp_prefix__ld_id)
        self._cxl_io_header._set_fmt_type(cxl_io_header__fmt_type)
        self._cxl_io_header._set_length_upper(cxl_io_header__length_upper)
        self._cxl_io_header._set_length_lower(cxl_io_header__length_lower)
        self._cfg_req_header._set_req_id(cfg_req_header__req_id)
        self._cfg_req_header._set_tag(cfg_req_header__tag)
        self._cfg_req_header._set_first_dw_be(cfg_req_header__first_dw_be)
        self._cfg_req_header._set_last_dw_be(cfg_req_header__last_dw_be)
        self._cfg_req_header._set_dest_id(cfg_req_header__dest_id)
        self._cfg_req_header._set_ext_reg_num(cfg_req_header__ext_reg_num)
        self._cfg_req_header._set_reg_num(cfg_req_header__reg_num)
        if data_src:
            dst = &self._buf[18]
            if data_length > MAX_PACKET_SIZE - 18:
                raise ValueError("data too large")
            memcpy(dst, data_src, data_length)
            self._data_length = data_length
        self._system_header._set_payload_length(18 + data_length)

    #────────────────── Python Interface ──────────────────
    @classmethod
    def create(
        cls,
        system_header__payload_type,
        tlp_prefix__ld_id,
        cxl_io_header__fmt_type,
        cxl_io_header__length_upper,
        cxl_io_header__length_lower,
        cfg_req_header__req_id,
        cfg_req_header__tag,
        cfg_req_header__first_dw_be,
        cfg_req_header__last_dw_be,
        cfg_req_header__dest_id,
        cfg_req_header__ext_reg_num,
        cfg_req_header__reg_num,
        data: bytes | None = None,
    ):
        cdef PyObject *tmp
        cdef _GenCxlIoCfgRdPacket pkt
        cdef Py_ssize_t data_length
        cdef const unsigned char* ptr

        if data:
            data_length = len(data)
            ptr = data
        else:
            data_length = 0
            ptr = NULL

        tmp = pool_pop(&__GenCxlIoCfgRdPacket_pool)
        if tmp == NULL:
            pkt = cls()
        else:
            pkt = <_GenCxlIoCfgRdPacket> tmp

        pkt._relocate()
        pkt._build(
            system_header__payload_type,
            tlp_prefix__ld_id,
            cxl_io_header__fmt_type,
            cxl_io_header__length_upper,
            cxl_io_header__length_lower,
            cfg_req_header__req_id,
            cfg_req_header__tag,
            cfg_req_header__first_dw_be,
            cfg_req_header__last_dw_be,
            cfg_req_header__dest_id,
            cfg_req_header__ext_reg_num,
            cfg_req_header__reg_num, 
            ptr,
            data_length,
        )
        return pkt

    def assign(
        self,
        system_header__payload_type,
        tlp_prefix__ld_id,
        cxl_io_header__fmt_type,
        cxl_io_header__length_upper,
        cxl_io_header__length_lower,
        cfg_req_header__req_id,
        cfg_req_header__tag,
        cfg_req_header__first_dw_be,
        cfg_req_header__last_dw_be,
        cfg_req_header__dest_id,
        cfg_req_header__ext_reg_num,
        cfg_req_header__reg_num,
        data: bytes | None = None,
    ):
        cdef Py_ssize_t data_length
        cdef const unsigned char* ptr

        if data:
            data_length = len(data)
            ptr = data
        else:
            data_length = 0
            ptr = NULL

        self._relocate()
        self._build(
            system_header__payload_type,
            tlp_prefix__ld_id,
            cxl_io_header__fmt_type,
            cxl_io_header__length_upper,
            cxl_io_header__length_lower,
            cfg_req_header__req_id,
            cfg_req_header__tag,
            cfg_req_header__first_dw_be,
            cfg_req_header__last_dw_be,
            cfg_req_header__dest_id,
            cfg_req_header__ext_reg_num,
            cfg_req_header__reg_num, 
            ptr,
            data_length,
        )

    cpdef set_data(self, data):
        src = <const unsigned char*> data
        dst = &self._buf[18]
        n = len(data)
        if 18 + n > MAX_PACKET_SIZE:
            raise ValueError("packet too large")
        memcpy(dst, src, n)
        self._data_length = n

    cpdef get_data(self):
        return PyBytes_FromStringAndSize(<char*>&self._buf[18], self._data_length)

    cpdef int get_payload_offset(self):
       return 18

    cpdef int get_byte_offset(self, object other):
        cdef uint8_t* base_ptr  = &self._buf[0]
        cdef uint8_t* other_ptr = NULL
        if isinstance(other, SystemHeader):
            other_ptr = (<SystemHeader> other)._p
        elif isinstance(other, TlpPrefix):
            other_ptr = (<TlpPrefix> other)._p
        elif isinstance(other, CxlIoHeader):
            other_ptr = (<CxlIoHeader> other)._p
        elif isinstance(other, CxlIoCfgReqHeader):
            other_ptr = (<CxlIoCfgReqHeader> other)._p
        else:
            raise TypeError(f"unsupported header type: {type(other)}")
        return <int>(other_ptr - base_ptr)

    cpdef void set_bytes(self, int offset, object data):
        cdef const unsigned char[::1] view = data
        cdef int i
        for i in range(view.shape[0]):
            self._buf[offset + i] = view[i]

    cpdef void write_bits(self, int start_bit, int width, unsigned long long value):
        _write_bits(&self._buf[0], start_bit, width, value)

    cpdef unsigned long long read_bits(self, int start_bit, int width):
        return _read_bits(&self._buf[0], start_bit, width)

    cpdef get_bytes(self, int start, int length):
        return PyBytes_FromStringAndSize(<char*>&self._buf[start], length)

    #──────────────────── Header accessors ────────────────────
    @property
    def system_header(self):
        return self._system_header

    @property
    def tlp_prefix(self):
        return self._tlp_prefix

    @property
    def cxl_io_header(self):
        return self._cxl_io_header

    @property
    def cfg_req_header(self):
        return self._cfg_req_header

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._release()

    def __del__(self):
        self._release()

    def __len__(self):
        return 18 + self._data_length

    def __bytes__(self):
        return PyBytes_FromStringAndSize(<char *> self._buf, 18 + self._data_length)

cdef PoolStruct __GenCxlIoCfgWrPacket_pool

cdef class _GenCxlIoCfgWrPacket:
    # class member vars
    cdef SystemHeader _system_header
    cdef TlpPrefix _tlp_prefix
    cdef CxlIoHeader _cxl_io_header
    cdef CxlIoCfgReqHeader _cfg_req_header
    cdef unsigned char _buf[MAX_PACKET_SIZE]
    cdef int _data_length

    #────────────────── Life-cycle management ──────────────────
    cdef void _release(self):
        pool_push(&__GenCxlIoCfgWrPacket_pool, <PyObject*> self)

    cdef inline void _relocate(self) noexcept nogil:
        cdef unsigned char* base = &self._buf[0]
        self._system_header.attach(base + 0)
        self._tlp_prefix.attach(base + 2)
        self._cxl_io_header.attach(base + 6)
        self._cfg_req_header.attach(base + 10)

    #─────────────────────── Builder ───────────────────────
    def __cinit__(self, payload=None):
        if not hasattr(self, '_data_length'):
            # first time only: allocate sub-headers
            self._data_length = 0
            self._system_header = SystemHeader()
            self._tlp_prefix = TlpPrefix()
            self._cxl_io_header = CxlIoHeader()
            self._cfg_req_header = CxlIoCfgReqHeader()
            self._relocate()
            Py_INCREF(self)

        if payload is not None:
            src = <const unsigned char*> payload
            dst = &self._buf[0]
            n = len(payload)
            if n > MAX_PACKET_SIZE:
                raise ValueError("packet too large")
            memcpy(dst, src, n)
            self._data_length = n - 18

    cdef inline void _build(
        self,
        int system_header__payload_type,
        int tlp_prefix__ld_id,
        int cxl_io_header__fmt_type,
        int cxl_io_header__length_upper,
        int cxl_io_header__length_lower,
        int cfg_req_header__req_id,
        int cfg_req_header__tag,
        int cfg_req_header__first_dw_be,
        int cfg_req_header__last_dw_be,
        int cfg_req_header__dest_id,
        int cfg_req_header__ext_reg_num,
        int cfg_req_header__reg_num,
        const unsigned char* data_src,
        Py_ssize_t data_length
    ) noexcept nogil:
        cdef unsigned char* dst

        memset(&self._buf[0], 0, MAX_PACKET_SIZE)
        self._system_header._set_payload_type(system_header__payload_type)
        self._tlp_prefix._set_ld_id(tlp_prefix__ld_id)
        self._cxl_io_header._set_fmt_type(cxl_io_header__fmt_type)
        self._cxl_io_header._set_length_upper(cxl_io_header__length_upper)
        self._cxl_io_header._set_length_lower(cxl_io_header__length_lower)
        self._cfg_req_header._set_req_id(cfg_req_header__req_id)
        self._cfg_req_header._set_tag(cfg_req_header__tag)
        self._cfg_req_header._set_first_dw_be(cfg_req_header__first_dw_be)
        self._cfg_req_header._set_last_dw_be(cfg_req_header__last_dw_be)
        self._cfg_req_header._set_dest_id(cfg_req_header__dest_id)
        self._cfg_req_header._set_ext_reg_num(cfg_req_header__ext_reg_num)
        self._cfg_req_header._set_reg_num(cfg_req_header__reg_num)
        if data_src:
            dst = &self._buf[18]
            if data_length > MAX_PACKET_SIZE - 18:
                raise ValueError("data too large")
            memcpy(dst, data_src, data_length)
            self._data_length = data_length
        self._system_header._set_payload_length(18 + data_length)

    #────────────────── Python Interface ──────────────────
    @classmethod
    def create(
        cls,
        system_header__payload_type,
        tlp_prefix__ld_id,
        cxl_io_header__fmt_type,
        cxl_io_header__length_upper,
        cxl_io_header__length_lower,
        cfg_req_header__req_id,
        cfg_req_header__tag,
        cfg_req_header__first_dw_be,
        cfg_req_header__last_dw_be,
        cfg_req_header__dest_id,
        cfg_req_header__ext_reg_num,
        cfg_req_header__reg_num,
        data: bytes | None = None,
    ):
        cdef PyObject *tmp
        cdef _GenCxlIoCfgWrPacket pkt
        cdef Py_ssize_t data_length
        cdef const unsigned char* ptr

        if data:
            data_length = len(data)
            ptr = data
        else:
            data_length = 0
            ptr = NULL

        tmp = pool_pop(&__GenCxlIoCfgWrPacket_pool)
        if tmp == NULL:
            pkt = cls()
        else:
            pkt = <_GenCxlIoCfgWrPacket> tmp

        pkt._relocate()
        pkt._build(
            system_header__payload_type,
            tlp_prefix__ld_id,
            cxl_io_header__fmt_type,
            cxl_io_header__length_upper,
            cxl_io_header__length_lower,
            cfg_req_header__req_id,
            cfg_req_header__tag,
            cfg_req_header__first_dw_be,
            cfg_req_header__last_dw_be,
            cfg_req_header__dest_id,
            cfg_req_header__ext_reg_num,
            cfg_req_header__reg_num, 
            ptr,
            data_length,
        )
        return pkt

    def assign(
        self,
        system_header__payload_type,
        tlp_prefix__ld_id,
        cxl_io_header__fmt_type,
        cxl_io_header__length_upper,
        cxl_io_header__length_lower,
        cfg_req_header__req_id,
        cfg_req_header__tag,
        cfg_req_header__first_dw_be,
        cfg_req_header__last_dw_be,
        cfg_req_header__dest_id,
        cfg_req_header__ext_reg_num,
        cfg_req_header__reg_num,
        data: bytes | None = None,
    ):
        cdef Py_ssize_t data_length
        cdef const unsigned char* ptr

        if data:
            data_length = len(data)
            ptr = data
        else:
            data_length = 0
            ptr = NULL

        self._relocate()
        self._build(
            system_header__payload_type,
            tlp_prefix__ld_id,
            cxl_io_header__fmt_type,
            cxl_io_header__length_upper,
            cxl_io_header__length_lower,
            cfg_req_header__req_id,
            cfg_req_header__tag,
            cfg_req_header__first_dw_be,
            cfg_req_header__last_dw_be,
            cfg_req_header__dest_id,
            cfg_req_header__ext_reg_num,
            cfg_req_header__reg_num, 
            ptr,
            data_length,
        )

    cpdef set_data(self, data):
        src = <const unsigned char*> data
        dst = &self._buf[18]
        n = len(data)
        if 18 + n > MAX_PACKET_SIZE:
            raise ValueError("packet too large")
        memcpy(dst, src, n)
        self._data_length = n

    cpdef get_data(self):
        return PyBytes_FromStringAndSize(<char*>&self._buf[18], self._data_length)

    cpdef int get_payload_offset(self):
       return 18

    cpdef int get_byte_offset(self, object other):
        cdef uint8_t* base_ptr  = &self._buf[0]
        cdef uint8_t* other_ptr = NULL
        if isinstance(other, SystemHeader):
            other_ptr = (<SystemHeader> other)._p
        elif isinstance(other, TlpPrefix):
            other_ptr = (<TlpPrefix> other)._p
        elif isinstance(other, CxlIoHeader):
            other_ptr = (<CxlIoHeader> other)._p
        elif isinstance(other, CxlIoCfgReqHeader):
            other_ptr = (<CxlIoCfgReqHeader> other)._p
        else:
            raise TypeError(f"unsupported header type: {type(other)}")
        return <int>(other_ptr - base_ptr)

    cpdef void set_bytes(self, int offset, object data):
        cdef const unsigned char[::1] view = data
        cdef int i
        for i in range(view.shape[0]):
            self._buf[offset + i] = view[i]

    cpdef void write_bits(self, int start_bit, int width, unsigned long long value):
        _write_bits(&self._buf[0], start_bit, width, value)

    cpdef unsigned long long read_bits(self, int start_bit, int width):
        return _read_bits(&self._buf[0], start_bit, width)

    cpdef get_bytes(self, int start, int length):
        return PyBytes_FromStringAndSize(<char*>&self._buf[start], length)

    #──────────────────── Header accessors ────────────────────
    @property
    def system_header(self):
        return self._system_header

    @property
    def tlp_prefix(self):
        return self._tlp_prefix

    @property
    def cxl_io_header(self):
        return self._cxl_io_header

    @property
    def cfg_req_header(self):
        return self._cfg_req_header

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._release()

    def __del__(self):
        self._release()

    def __len__(self):
        return 18 + self._data_length

    def __bytes__(self):
        return PyBytes_FromStringAndSize(<char *> self._buf, 18 + self._data_length)

cdef PoolStruct __GenCxlIoCompletionPacket_pool

cdef class _GenCxlIoCompletionPacket:
    # class member vars
    cdef SystemHeader _system_header
    cdef TlpPrefix _tlp_prefix
    cdef CxlIoHeader _cxl_io_header
    cdef CxlIoCompletionHeader _cpl_header
    cdef unsigned char _buf[MAX_PACKET_SIZE]
    cdef int _data_length

    #────────────────── Life-cycle management ──────────────────
    cdef void _release(self):
        pool_push(&__GenCxlIoCompletionPacket_pool, <PyObject*> self)

    cdef inline void _relocate(self) noexcept nogil:
        cdef unsigned char* base = &self._buf[0]
        self._system_header.attach(base + 0)
        self._tlp_prefix.attach(base + 2)
        self._cxl_io_header.attach(base + 6)
        self._cpl_header.attach(base + 10)

    #─────────────────────── Builder ───────────────────────
    def __cinit__(self, payload=None):
        if not hasattr(self, '_data_length'):
            # first time only: allocate sub-headers
            self._data_length = 0
            self._system_header = SystemHeader()
            self._tlp_prefix = TlpPrefix()
            self._cxl_io_header = CxlIoHeader()
            self._cpl_header = CxlIoCompletionHeader()
            self._relocate()
            Py_INCREF(self)

        if payload is not None:
            src = <const unsigned char*> payload
            dst = &self._buf[0]
            n = len(payload)
            if n > MAX_PACKET_SIZE:
                raise ValueError("packet too large")
            memcpy(dst, src, n)
            self._data_length = n - 18

    cdef inline void _build(
        self,
        int system_header__payload_type,
        int tlp_prefix__ld_id,
        int cxl_io_header__fmt_type,
        int cxl_io_header__length_upper,
        int cxl_io_header__length_lower,
        int cpl_header__cpl_id,
        int cpl_header__status,
        int cpl_header__byte_count_upper,
        int cpl_header__byte_count_lower,
        int cpl_header__req_id,
        int cpl_header__tag,
        const unsigned char* data_src,
        Py_ssize_t data_length
    ) noexcept nogil:
        cdef unsigned char* dst

        memset(&self._buf[0], 0, MAX_PACKET_SIZE)
        self._system_header._set_payload_type(system_header__payload_type)
        self._tlp_prefix._set_ld_id(tlp_prefix__ld_id)
        self._cxl_io_header._set_fmt_type(cxl_io_header__fmt_type)
        self._cxl_io_header._set_length_upper(cxl_io_header__length_upper)
        self._cxl_io_header._set_length_lower(cxl_io_header__length_lower)
        self._cpl_header._set_cpl_id(cpl_header__cpl_id)
        self._cpl_header._set_status(cpl_header__status)
        self._cpl_header._set_byte_count_upper(cpl_header__byte_count_upper)
        self._cpl_header._set_byte_count_lower(cpl_header__byte_count_lower)
        self._cpl_header._set_req_id(cpl_header__req_id)
        self._cpl_header._set_tag(cpl_header__tag)
        if data_src:
            dst = &self._buf[18]
            if data_length > MAX_PACKET_SIZE - 18:
                raise ValueError("data too large")
            memcpy(dst, data_src, data_length)
            self._data_length = data_length
        self._system_header._set_payload_length(18 + data_length)

    #────────────────── Python Interface ──────────────────
    @classmethod
    def create(
        cls,
        system_header__payload_type,
        tlp_prefix__ld_id,
        cxl_io_header__fmt_type,
        cxl_io_header__length_upper,
        cxl_io_header__length_lower,
        cpl_header__cpl_id,
        cpl_header__status,
        cpl_header__byte_count_upper,
        cpl_header__byte_count_lower,
        cpl_header__req_id,
        cpl_header__tag,
        data: bytes | None = None,
    ):
        cdef PyObject *tmp
        cdef _GenCxlIoCompletionPacket pkt
        cdef Py_ssize_t data_length
        cdef const unsigned char* ptr

        if data:
            data_length = len(data)
            ptr = data
        else:
            data_length = 0
            ptr = NULL

        tmp = pool_pop(&__GenCxlIoCompletionPacket_pool)
        if tmp == NULL:
            pkt = cls()
        else:
            pkt = <_GenCxlIoCompletionPacket> tmp

        pkt._relocate()
        pkt._build(
            system_header__payload_type,
            tlp_prefix__ld_id,
            cxl_io_header__fmt_type,
            cxl_io_header__length_upper,
            cxl_io_header__length_lower,
            cpl_header__cpl_id,
            cpl_header__status,
            cpl_header__byte_count_upper,
            cpl_header__byte_count_lower,
            cpl_header__req_id,
            cpl_header__tag, 
            ptr,
            data_length,
        )
        return pkt

    def assign(
        self,
        system_header__payload_type,
        tlp_prefix__ld_id,
        cxl_io_header__fmt_type,
        cxl_io_header__length_upper,
        cxl_io_header__length_lower,
        cpl_header__cpl_id,
        cpl_header__status,
        cpl_header__byte_count_upper,
        cpl_header__byte_count_lower,
        cpl_header__req_id,
        cpl_header__tag,
        data: bytes | None = None,
    ):
        cdef Py_ssize_t data_length
        cdef const unsigned char* ptr

        if data:
            data_length = len(data)
            ptr = data
        else:
            data_length = 0
            ptr = NULL

        self._relocate()
        self._build(
            system_header__payload_type,
            tlp_prefix__ld_id,
            cxl_io_header__fmt_type,
            cxl_io_header__length_upper,
            cxl_io_header__length_lower,
            cpl_header__cpl_id,
            cpl_header__status,
            cpl_header__byte_count_upper,
            cpl_header__byte_count_lower,
            cpl_header__req_id,
            cpl_header__tag, 
            ptr,
            data_length,
        )

    cpdef set_data(self, data):
        src = <const unsigned char*> data
        dst = &self._buf[18]
        n = len(data)
        if 18 + n > MAX_PACKET_SIZE:
            raise ValueError("packet too large")
        memcpy(dst, src, n)
        self._data_length = n

    cpdef get_data(self):
        return PyBytes_FromStringAndSize(<char*>&self._buf[18], self._data_length)

    cpdef int get_payload_offset(self):
       return 18

    cpdef int get_byte_offset(self, object other):
        cdef uint8_t* base_ptr  = &self._buf[0]
        cdef uint8_t* other_ptr = NULL
        if isinstance(other, SystemHeader):
            other_ptr = (<SystemHeader> other)._p
        elif isinstance(other, TlpPrefix):
            other_ptr = (<TlpPrefix> other)._p
        elif isinstance(other, CxlIoHeader):
            other_ptr = (<CxlIoHeader> other)._p
        elif isinstance(other, CxlIoCompletionHeader):
            other_ptr = (<CxlIoCompletionHeader> other)._p
        else:
            raise TypeError(f"unsupported header type: {type(other)}")
        return <int>(other_ptr - base_ptr)

    cpdef void set_bytes(self, int offset, object data):
        cdef const unsigned char[::1] view = data
        cdef int i
        for i in range(view.shape[0]):
            self._buf[offset + i] = view[i]

    cpdef void write_bits(self, int start_bit, int width, unsigned long long value):
        _write_bits(&self._buf[0], start_bit, width, value)

    cpdef unsigned long long read_bits(self, int start_bit, int width):
        return _read_bits(&self._buf[0], start_bit, width)

    cpdef get_bytes(self, int start, int length):
        return PyBytes_FromStringAndSize(<char*>&self._buf[start], length)

    #──────────────────── Header accessors ────────────────────
    @property
    def system_header(self):
        return self._system_header

    @property
    def tlp_prefix(self):
        return self._tlp_prefix

    @property
    def cxl_io_header(self):
        return self._cxl_io_header

    @property
    def cpl_header(self):
        return self._cpl_header

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._release()

    def __del__(self):
        self._release()

    def __len__(self):
        return 18 + self._data_length

    def __bytes__(self):
        return PyBytes_FromStringAndSize(<char *> self._buf, 18 + self._data_length)

cdef PoolStruct __GenCxlCacheBasePacket_pool

cdef class _GenCxlCacheBasePacket:
    # class member vars
    cdef SystemHeader _system_header
    cdef CxlCacheHeader _cxl_cache_header
    cdef unsigned char _buf[MAX_PACKET_SIZE]
    cdef int _data_length

    #────────────────── Life-cycle management ──────────────────
    cdef void _release(self):
        pool_push(&__GenCxlCacheBasePacket_pool, <PyObject*> self)

    cdef inline void _relocate(self) noexcept nogil:
        cdef unsigned char* base = &self._buf[0]
        self._system_header.attach(base + 0)
        self._cxl_cache_header.attach(base + 2)

    #─────────────────────── Builder ───────────────────────
    def __cinit__(self, payload=None):
        if not hasattr(self, '_data_length'):
            # first time only: allocate sub-headers
            self._data_length = 0
            self._system_header = SystemHeader()
            self._cxl_cache_header = CxlCacheHeader()
            self._relocate()
            Py_INCREF(self)

        if payload is not None:
            src = <const unsigned char*> payload
            dst = &self._buf[0]
            n = len(payload)
            if n > MAX_PACKET_SIZE:
                raise ValueError("packet too large")
            memcpy(dst, src, n)
            self._data_length = n - 4

    #────────────────── Python Interface ──────────────────
    cpdef set_data(self, data):
        src = <const unsigned char*> data
        dst = &self._buf[4]
        n = len(data)
        if 4 + n > MAX_PACKET_SIZE:
            raise ValueError("packet too large")
        memcpy(dst, src, n)
        self._data_length = n

    cpdef get_data(self):
        return PyBytes_FromStringAndSize(<char*>&self._buf[4], self._data_length)

    cpdef int get_payload_offset(self):
       return 4

    cpdef int get_byte_offset(self, object other):
        cdef uint8_t* base_ptr  = &self._buf[0]
        cdef uint8_t* other_ptr = NULL
        if isinstance(other, SystemHeader):
            other_ptr = (<SystemHeader> other)._p
        elif isinstance(other, CxlCacheHeader):
            other_ptr = (<CxlCacheHeader> other)._p
        else:
            raise TypeError(f"unsupported header type: {type(other)}")
        return <int>(other_ptr - base_ptr)

    cpdef void set_bytes(self, int offset, object data):
        cdef const unsigned char[::1] view = data
        cdef int i
        for i in range(view.shape[0]):
            self._buf[offset + i] = view[i]

    cpdef void write_bits(self, int start_bit, int width, unsigned long long value):
        _write_bits(&self._buf[0], start_bit, width, value)

    cpdef unsigned long long read_bits(self, int start_bit, int width):
        return _read_bits(&self._buf[0], start_bit, width)

    cpdef get_bytes(self, int start, int length):
        return PyBytes_FromStringAndSize(<char*>&self._buf[start], length)

    #──────────────────── Header accessors ────────────────────
    @property
    def system_header(self):
        return self._system_header

    @property
    def cxl_cache_header(self):
        return self._cxl_cache_header

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._release()

    def __del__(self):
        self._release()

    def __len__(self):
        return 4 + self._data_length

    def __bytes__(self):
        return PyBytes_FromStringAndSize(<char *> self._buf, 4 + self._data_length)

cdef PoolStruct __GenCxlCacheD2HReqPacket_pool

cdef class _GenCxlCacheD2HReqPacket:
    # class member vars
    cdef SystemHeader _system_header
    cdef CxlCacheHeader _cxl_cache_header
    cdef CxlCacheD2HReqHeader _d2hreq_header
    cdef unsigned char _buf[MAX_PACKET_SIZE]
    cdef int _data_length

    #────────────────── Life-cycle management ──────────────────
    cdef void _release(self):
        pool_push(&__GenCxlCacheD2HReqPacket_pool, <PyObject*> self)

    cdef inline void _relocate(self) noexcept nogil:
        cdef unsigned char* base = &self._buf[0]
        self._system_header.attach(base + 0)
        self._cxl_cache_header.attach(base + 2)
        self._d2hreq_header.attach(base + 4)

    #─────────────────────── Builder ───────────────────────
    def __cinit__(self, payload=None):
        if not hasattr(self, '_data_length'):
            # first time only: allocate sub-headers
            self._data_length = 0
            self._system_header = SystemHeader()
            self._cxl_cache_header = CxlCacheHeader()
            self._d2hreq_header = CxlCacheD2HReqHeader()
            self._relocate()
            Py_INCREF(self)

        if payload is not None:
            src = <const unsigned char*> payload
            dst = &self._buf[0]
            n = len(payload)
            if n > MAX_PACKET_SIZE:
                raise ValueError("packet too large")
            memcpy(dst, src, n)
            self._data_length = n - 13

    cdef inline void _build(
        self,
        int system_header__payload_type,
        int cxl_cache_header__msg_class,
        int d2hreq_header__valid,
        int d2hreq_header__cache_opcode,
        int d2hreq_header__cqid,
        int d2hreq_header__cache_id,
        unsigned long long d2hreq_header__addr,
        const unsigned char* data_src,
        Py_ssize_t data_length
    ) noexcept nogil:
        cdef unsigned char* dst

        memset(&self._buf[0], 0, MAX_PACKET_SIZE)
        self._system_header._set_payload_type(system_header__payload_type)
        self._cxl_cache_header._set_msg_class(cxl_cache_header__msg_class)
        self._d2hreq_header._set_valid(d2hreq_header__valid)
        self._d2hreq_header._set_cache_opcode(d2hreq_header__cache_opcode)
        self._d2hreq_header._set_cqid(d2hreq_header__cqid)
        self._d2hreq_header._set_cache_id(d2hreq_header__cache_id)
        self._d2hreq_header._set_addr(d2hreq_header__addr)
        if data_src:
            dst = &self._buf[13]
            if data_length > MAX_PACKET_SIZE - 13:
                raise ValueError("data too large")
            memcpy(dst, data_src, data_length)
            self._data_length = data_length
        self._system_header._set_payload_length(13 + data_length)

    #────────────────── Python Interface ──────────────────
    @classmethod
    def create(
        cls,
        system_header__payload_type,
        cxl_cache_header__msg_class,
        d2hreq_header__valid,
        d2hreq_header__cache_opcode,
        d2hreq_header__cqid,
        d2hreq_header__cache_id,
        d2hreq_header__addr,
        data: bytes | None = None,
    ):
        cdef PyObject *tmp
        cdef _GenCxlCacheD2HReqPacket pkt
        cdef Py_ssize_t data_length
        cdef const unsigned char* ptr

        if data:
            data_length = len(data)
            ptr = data
        else:
            data_length = 0
            ptr = NULL

        tmp = pool_pop(&__GenCxlCacheD2HReqPacket_pool)
        if tmp == NULL:
            pkt = cls()
        else:
            pkt = <_GenCxlCacheD2HReqPacket> tmp

        pkt._relocate()
        pkt._build(
            system_header__payload_type,
            cxl_cache_header__msg_class,
            d2hreq_header__valid,
            d2hreq_header__cache_opcode,
            d2hreq_header__cqid,
            d2hreq_header__cache_id,
            d2hreq_header__addr, 
            ptr,
            data_length,
        )
        return pkt

    def assign(
        self,
        system_header__payload_type,
        cxl_cache_header__msg_class,
        d2hreq_header__valid,
        d2hreq_header__cache_opcode,
        d2hreq_header__cqid,
        d2hreq_header__cache_id,
        d2hreq_header__addr,
        data: bytes | None = None,
    ):
        cdef Py_ssize_t data_length
        cdef const unsigned char* ptr

        if data:
            data_length = len(data)
            ptr = data
        else:
            data_length = 0
            ptr = NULL

        self._relocate()
        self._build(
            system_header__payload_type,
            cxl_cache_header__msg_class,
            d2hreq_header__valid,
            d2hreq_header__cache_opcode,
            d2hreq_header__cqid,
            d2hreq_header__cache_id,
            d2hreq_header__addr, 
            ptr,
            data_length,
        )

    cpdef set_data(self, data):
        src = <const unsigned char*> data
        dst = &self._buf[13]
        n = len(data)
        if 13 + n > MAX_PACKET_SIZE:
            raise ValueError("packet too large")
        memcpy(dst, src, n)
        self._data_length = n

    cpdef get_data(self):
        return PyBytes_FromStringAndSize(<char*>&self._buf[13], self._data_length)

    cpdef int get_payload_offset(self):
       return 13

    cpdef int get_byte_offset(self, object other):
        cdef uint8_t* base_ptr  = &self._buf[0]
        cdef uint8_t* other_ptr = NULL
        if isinstance(other, SystemHeader):
            other_ptr = (<SystemHeader> other)._p
        elif isinstance(other, CxlCacheHeader):
            other_ptr = (<CxlCacheHeader> other)._p
        elif isinstance(other, CxlCacheD2HReqHeader):
            other_ptr = (<CxlCacheD2HReqHeader> other)._p
        else:
            raise TypeError(f"unsupported header type: {type(other)}")
        return <int>(other_ptr - base_ptr)

    cpdef void set_bytes(self, int offset, object data):
        cdef const unsigned char[::1] view = data
        cdef int i
        for i in range(view.shape[0]):
            self._buf[offset + i] = view[i]

    cpdef void write_bits(self, int start_bit, int width, unsigned long long value):
        _write_bits(&self._buf[0], start_bit, width, value)

    cpdef unsigned long long read_bits(self, int start_bit, int width):
        return _read_bits(&self._buf[0], start_bit, width)

    cpdef get_bytes(self, int start, int length):
        return PyBytes_FromStringAndSize(<char*>&self._buf[start], length)

    #──────────────────── Header accessors ────────────────────
    @property
    def system_header(self):
        return self._system_header

    @property
    def cxl_cache_header(self):
        return self._cxl_cache_header

    @property
    def d2hreq_header(self):
        return self._d2hreq_header

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._release()

    def __del__(self):
        self._release()

    def __len__(self):
        return 13 + self._data_length

    def __bytes__(self):
        return PyBytes_FromStringAndSize(<char *> self._buf, 13 + self._data_length)

cdef PoolStruct __GenCxlCacheD2HRspPacket_pool

cdef class _GenCxlCacheD2HRspPacket:
    # class member vars
    cdef SystemHeader _system_header
    cdef CxlCacheHeader _cxl_cache_header
    cdef CxlCacheD2HRspHeader _d2hrsp_header
    cdef unsigned char _buf[MAX_PACKET_SIZE]
    cdef int _data_length

    #────────────────── Life-cycle management ──────────────────
    cdef void _release(self):
        pool_push(&__GenCxlCacheD2HRspPacket_pool, <PyObject*> self)

    cdef inline void _relocate(self) noexcept nogil:
        cdef unsigned char* base = &self._buf[0]
        self._system_header.attach(base + 0)
        self._cxl_cache_header.attach(base + 2)
        self._d2hrsp_header.attach(base + 4)

    #─────────────────────── Builder ───────────────────────
    def __cinit__(self, payload=None):
        if not hasattr(self, '_data_length'):
            # first time only: allocate sub-headers
            self._data_length = 0
            self._system_header = SystemHeader()
            self._cxl_cache_header = CxlCacheHeader()
            self._d2hrsp_header = CxlCacheD2HRspHeader()
            self._relocate()
            Py_INCREF(self)

        if payload is not None:
            src = <const unsigned char*> payload
            dst = &self._buf[0]
            n = len(payload)
            if n > MAX_PACKET_SIZE:
                raise ValueError("packet too large")
            memcpy(dst, src, n)
            self._data_length = n - 7

    cdef inline void _build(
        self,
        int system_header__payload_type,
        int cxl_cache_header__msg_class,
        int d2hrsp_header__valid,
        int d2hrsp_header__uqid,
        int d2hrsp_header__cache_opcode,
        const unsigned char* data_src,
        Py_ssize_t data_length
    ) noexcept nogil:
        cdef unsigned char* dst

        memset(&self._buf[0], 0, MAX_PACKET_SIZE)
        self._system_header._set_payload_type(system_header__payload_type)
        self._cxl_cache_header._set_msg_class(cxl_cache_header__msg_class)
        self._d2hrsp_header._set_valid(d2hrsp_header__valid)
        self._d2hrsp_header._set_uqid(d2hrsp_header__uqid)
        self._d2hrsp_header._set_cache_opcode(d2hrsp_header__cache_opcode)
        if data_src:
            dst = &self._buf[7]
            if data_length > MAX_PACKET_SIZE - 7:
                raise ValueError("data too large")
            memcpy(dst, data_src, data_length)
            self._data_length = data_length
        self._system_header._set_payload_length(7 + data_length)

    #────────────────── Python Interface ──────────────────
    @classmethod
    def create(
        cls,
        system_header__payload_type,
        cxl_cache_header__msg_class,
        d2hrsp_header__valid,
        d2hrsp_header__uqid,
        d2hrsp_header__cache_opcode,
        data: bytes | None = None,
    ):
        cdef PyObject *tmp
        cdef _GenCxlCacheD2HRspPacket pkt
        cdef Py_ssize_t data_length
        cdef const unsigned char* ptr

        if data:
            data_length = len(data)
            ptr = data
        else:
            data_length = 0
            ptr = NULL

        tmp = pool_pop(&__GenCxlCacheD2HRspPacket_pool)
        if tmp == NULL:
            pkt = cls()
        else:
            pkt = <_GenCxlCacheD2HRspPacket> tmp

        pkt._relocate()
        pkt._build(
            system_header__payload_type,
            cxl_cache_header__msg_class,
            d2hrsp_header__valid,
            d2hrsp_header__uqid,
            d2hrsp_header__cache_opcode, 
            ptr,
            data_length,
        )
        return pkt

    def assign(
        self,
        system_header__payload_type,
        cxl_cache_header__msg_class,
        d2hrsp_header__valid,
        d2hrsp_header__uqid,
        d2hrsp_header__cache_opcode,
        data: bytes | None = None,
    ):
        cdef Py_ssize_t data_length
        cdef const unsigned char* ptr

        if data:
            data_length = len(data)
            ptr = data
        else:
            data_length = 0
            ptr = NULL

        self._relocate()
        self._build(
            system_header__payload_type,
            cxl_cache_header__msg_class,
            d2hrsp_header__valid,
            d2hrsp_header__uqid,
            d2hrsp_header__cache_opcode, 
            ptr,
            data_length,
        )

    cpdef set_data(self, data):
        src = <const unsigned char*> data
        dst = &self._buf[7]
        n = len(data)
        if 7 + n > MAX_PACKET_SIZE:
            raise ValueError("packet too large")
        memcpy(dst, src, n)
        self._data_length = n

    cpdef get_data(self):
        return PyBytes_FromStringAndSize(<char*>&self._buf[7], self._data_length)

    cpdef int get_payload_offset(self):
       return 7

    cpdef int get_byte_offset(self, object other):
        cdef uint8_t* base_ptr  = &self._buf[0]
        cdef uint8_t* other_ptr = NULL
        if isinstance(other, SystemHeader):
            other_ptr = (<SystemHeader> other)._p
        elif isinstance(other, CxlCacheHeader):
            other_ptr = (<CxlCacheHeader> other)._p
        elif isinstance(other, CxlCacheD2HRspHeader):
            other_ptr = (<CxlCacheD2HRspHeader> other)._p
        else:
            raise TypeError(f"unsupported header type: {type(other)}")
        return <int>(other_ptr - base_ptr)

    cpdef void set_bytes(self, int offset, object data):
        cdef const unsigned char[::1] view = data
        cdef int i
        for i in range(view.shape[0]):
            self._buf[offset + i] = view[i]

    cpdef void write_bits(self, int start_bit, int width, unsigned long long value):
        _write_bits(&self._buf[0], start_bit, width, value)

    cpdef unsigned long long read_bits(self, int start_bit, int width):
        return _read_bits(&self._buf[0], start_bit, width)

    cpdef get_bytes(self, int start, int length):
        return PyBytes_FromStringAndSize(<char*>&self._buf[start], length)

    #──────────────────── Header accessors ────────────────────
    @property
    def system_header(self):
        return self._system_header

    @property
    def cxl_cache_header(self):
        return self._cxl_cache_header

    @property
    def d2hrsp_header(self):
        return self._d2hrsp_header

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._release()

    def __del__(self):
        self._release()

    def __len__(self):
        return 7 + self._data_length

    def __bytes__(self):
        return PyBytes_FromStringAndSize(<char *> self._buf, 7 + self._data_length)

cdef PoolStruct __GenCxlCacheD2HDataPacket_pool

cdef class _GenCxlCacheD2HDataPacket:
    # class member vars
    cdef SystemHeader _system_header
    cdef CxlCacheHeader _cxl_cache_header
    cdef CxlCacheD2HDataHeader _d2hdata_header
    cdef unsigned char _buf[MAX_PACKET_SIZE]
    cdef int _data_length

    #────────────────── Life-cycle management ──────────────────
    cdef void _release(self):
        pool_push(&__GenCxlCacheD2HDataPacket_pool, <PyObject*> self)

    cdef inline void _relocate(self) noexcept nogil:
        cdef unsigned char* base = &self._buf[0]
        self._system_header.attach(base + 0)
        self._cxl_cache_header.attach(base + 2)
        self._d2hdata_header.attach(base + 4)

    #─────────────────────── Builder ───────────────────────
    def __cinit__(self, payload=None):
        if not hasattr(self, '_data_length'):
            # first time only: allocate sub-headers
            self._data_length = 0
            self._system_header = SystemHeader()
            self._cxl_cache_header = CxlCacheHeader()
            self._d2hdata_header = CxlCacheD2HDataHeader()
            self._relocate()
            Py_INCREF(self)

        if payload is not None:
            src = <const unsigned char*> payload
            dst = &self._buf[0]
            n = len(payload)
            if n > MAX_PACKET_SIZE:
                raise ValueError("packet too large")
            memcpy(dst, src, n)
            self._data_length = n - 7

    cdef inline void _build(
        self,
        int system_header__payload_type,
        int cxl_cache_header__msg_class,
        int d2hdata_header__valid,
        int d2hdata_header__uqid,
        int d2hdata_header__poison,
        const unsigned char* data_src,
        Py_ssize_t data_length
    ) noexcept nogil:
        cdef unsigned char* dst

        memset(&self._buf[0], 0, MAX_PACKET_SIZE)
        self._system_header._set_payload_type(system_header__payload_type)
        self._cxl_cache_header._set_msg_class(cxl_cache_header__msg_class)
        self._d2hdata_header._set_valid(d2hdata_header__valid)
        self._d2hdata_header._set_uqid(d2hdata_header__uqid)
        self._d2hdata_header._set_poison(d2hdata_header__poison)
        if data_src:
            dst = &self._buf[7]
            if data_length > MAX_PACKET_SIZE - 7:
                raise ValueError("data too large")
            memcpy(dst, data_src, data_length)
            self._data_length = data_length
        self._system_header._set_payload_length(7 + data_length)

    #────────────────── Python Interface ──────────────────
    @classmethod
    def create(
        cls,
        system_header__payload_type,
        cxl_cache_header__msg_class,
        d2hdata_header__valid,
        d2hdata_header__uqid,
        d2hdata_header__poison,
        data: bytes | None = None,
    ):
        cdef PyObject *tmp
        cdef _GenCxlCacheD2HDataPacket pkt
        cdef Py_ssize_t data_length
        cdef const unsigned char* ptr

        if data:
            data_length = len(data)
            ptr = data
        else:
            data_length = 0
            ptr = NULL

        tmp = pool_pop(&__GenCxlCacheD2HDataPacket_pool)
        if tmp == NULL:
            pkt = cls()
        else:
            pkt = <_GenCxlCacheD2HDataPacket> tmp

        pkt._relocate()
        pkt._build(
            system_header__payload_type,
            cxl_cache_header__msg_class,
            d2hdata_header__valid,
            d2hdata_header__uqid,
            d2hdata_header__poison, 
            ptr,
            data_length,
        )
        return pkt

    def assign(
        self,
        system_header__payload_type,
        cxl_cache_header__msg_class,
        d2hdata_header__valid,
        d2hdata_header__uqid,
        d2hdata_header__poison,
        data: bytes | None = None,
    ):
        cdef Py_ssize_t data_length
        cdef const unsigned char* ptr

        if data:
            data_length = len(data)
            ptr = data
        else:
            data_length = 0
            ptr = NULL

        self._relocate()
        self._build(
            system_header__payload_type,
            cxl_cache_header__msg_class,
            d2hdata_header__valid,
            d2hdata_header__uqid,
            d2hdata_header__poison, 
            ptr,
            data_length,
        )

    cpdef set_data(self, data):
        src = <const unsigned char*> data
        dst = &self._buf[7]
        n = len(data)
        if 7 + n > MAX_PACKET_SIZE:
            raise ValueError("packet too large")
        memcpy(dst, src, n)
        self._data_length = n

    cpdef get_data(self):
        return PyBytes_FromStringAndSize(<char*>&self._buf[7], self._data_length)

    cpdef int get_payload_offset(self):
       return 7

    cpdef int get_byte_offset(self, object other):
        cdef uint8_t* base_ptr  = &self._buf[0]
        cdef uint8_t* other_ptr = NULL
        if isinstance(other, SystemHeader):
            other_ptr = (<SystemHeader> other)._p
        elif isinstance(other, CxlCacheHeader):
            other_ptr = (<CxlCacheHeader> other)._p
        elif isinstance(other, CxlCacheD2HDataHeader):
            other_ptr = (<CxlCacheD2HDataHeader> other)._p
        else:
            raise TypeError(f"unsupported header type: {type(other)}")
        return <int>(other_ptr - base_ptr)

    cpdef void set_bytes(self, int offset, object data):
        cdef const unsigned char[::1] view = data
        cdef int i
        for i in range(view.shape[0]):
            self._buf[offset + i] = view[i]

    cpdef void write_bits(self, int start_bit, int width, unsigned long long value):
        _write_bits(&self._buf[0], start_bit, width, value)

    cpdef unsigned long long read_bits(self, int start_bit, int width):
        return _read_bits(&self._buf[0], start_bit, width)

    cpdef get_bytes(self, int start, int length):
        return PyBytes_FromStringAndSize(<char*>&self._buf[start], length)

    #──────────────────── Header accessors ────────────────────
    @property
    def system_header(self):
        return self._system_header

    @property
    def cxl_cache_header(self):
        return self._cxl_cache_header

    @property
    def d2hdata_header(self):
        return self._d2hdata_header

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._release()

    def __del__(self):
        self._release()

    def __len__(self):
        return 7 + self._data_length

    def __bytes__(self):
        return PyBytes_FromStringAndSize(<char *> self._buf, 7 + self._data_length)

cdef PoolStruct __GenCxlCacheH2DReqPacket_pool

cdef class _GenCxlCacheH2DReqPacket:
    # class member vars
    cdef SystemHeader _system_header
    cdef CxlCacheHeader _cxl_cache_header
    cdef CxlCacheH2DReqHeader _h2dreq_header
    cdef unsigned char _buf[MAX_PACKET_SIZE]
    cdef int _data_length

    #────────────────── Life-cycle management ──────────────────
    cdef void _release(self):
        pool_push(&__GenCxlCacheH2DReqPacket_pool, <PyObject*> self)

    cdef inline void _relocate(self) noexcept nogil:
        cdef unsigned char* base = &self._buf[0]
        self._system_header.attach(base + 0)
        self._cxl_cache_header.attach(base + 2)
        self._h2dreq_header.attach(base + 4)

    #─────────────────────── Builder ───────────────────────
    def __cinit__(self, payload=None):
        if not hasattr(self, '_data_length'):
            # first time only: allocate sub-headers
            self._data_length = 0
            self._system_header = SystemHeader()
            self._cxl_cache_header = CxlCacheHeader()
            self._h2dreq_header = CxlCacheH2DReqHeader()
            self._relocate()
            Py_INCREF(self)

        if payload is not None:
            src = <const unsigned char*> payload
            dst = &self._buf[0]
            n = len(payload)
            if n > MAX_PACKET_SIZE:
                raise ValueError("packet too large")
            memcpy(dst, src, n)
            self._data_length = n - 13

    cdef inline void _build(
        self,
        int system_header__payload_type,
        int cxl_cache_header__msg_class,
        int h2dreq_header__valid,
        int h2dreq_header__cache_opcode,
        int h2dreq_header__cache_id,
        unsigned long long h2dreq_header__addr,
        const unsigned char* data_src,
        Py_ssize_t data_length
    ) noexcept nogil:
        cdef unsigned char* dst

        memset(&self._buf[0], 0, MAX_PACKET_SIZE)
        self._system_header._set_payload_type(system_header__payload_type)
        self._cxl_cache_header._set_msg_class(cxl_cache_header__msg_class)
        self._h2dreq_header._set_valid(h2dreq_header__valid)
        self._h2dreq_header._set_cache_opcode(h2dreq_header__cache_opcode)
        self._h2dreq_header._set_cache_id(h2dreq_header__cache_id)
        self._h2dreq_header._set_addr(h2dreq_header__addr)
        if data_src:
            dst = &self._buf[13]
            if data_length > MAX_PACKET_SIZE - 13:
                raise ValueError("data too large")
            memcpy(dst, data_src, data_length)
            self._data_length = data_length
        self._system_header._set_payload_length(13 + data_length)

    #────────────────── Python Interface ──────────────────
    @classmethod
    def create(
        cls,
        system_header__payload_type,
        cxl_cache_header__msg_class,
        h2dreq_header__valid,
        h2dreq_header__cache_opcode,
        h2dreq_header__cache_id,
        h2dreq_header__addr,
        data: bytes | None = None,
    ):
        cdef PyObject *tmp
        cdef _GenCxlCacheH2DReqPacket pkt
        cdef Py_ssize_t data_length
        cdef const unsigned char* ptr

        if data:
            data_length = len(data)
            ptr = data
        else:
            data_length = 0
            ptr = NULL

        tmp = pool_pop(&__GenCxlCacheH2DReqPacket_pool)
        if tmp == NULL:
            pkt = cls()
        else:
            pkt = <_GenCxlCacheH2DReqPacket> tmp

        pkt._relocate()
        pkt._build(
            system_header__payload_type,
            cxl_cache_header__msg_class,
            h2dreq_header__valid,
            h2dreq_header__cache_opcode,
            h2dreq_header__cache_id,
            h2dreq_header__addr, 
            ptr,
            data_length,
        )
        return pkt

    def assign(
        self,
        system_header__payload_type,
        cxl_cache_header__msg_class,
        h2dreq_header__valid,
        h2dreq_header__cache_opcode,
        h2dreq_header__cache_id,
        h2dreq_header__addr,
        data: bytes | None = None,
    ):
        cdef Py_ssize_t data_length
        cdef const unsigned char* ptr

        if data:
            data_length = len(data)
            ptr = data
        else:
            data_length = 0
            ptr = NULL

        self._relocate()
        self._build(
            system_header__payload_type,
            cxl_cache_header__msg_class,
            h2dreq_header__valid,
            h2dreq_header__cache_opcode,
            h2dreq_header__cache_id,
            h2dreq_header__addr, 
            ptr,
            data_length,
        )

    cpdef set_data(self, data):
        src = <const unsigned char*> data
        dst = &self._buf[13]
        n = len(data)
        if 13 + n > MAX_PACKET_SIZE:
            raise ValueError("packet too large")
        memcpy(dst, src, n)
        self._data_length = n

    cpdef get_data(self):
        return PyBytes_FromStringAndSize(<char*>&self._buf[13], self._data_length)

    cpdef int get_payload_offset(self):
       return 13

    cpdef int get_byte_offset(self, object other):
        cdef uint8_t* base_ptr  = &self._buf[0]
        cdef uint8_t* other_ptr = NULL
        if isinstance(other, SystemHeader):
            other_ptr = (<SystemHeader> other)._p
        elif isinstance(other, CxlCacheHeader):
            other_ptr = (<CxlCacheHeader> other)._p
        elif isinstance(other, CxlCacheH2DReqHeader):
            other_ptr = (<CxlCacheH2DReqHeader> other)._p
        else:
            raise TypeError(f"unsupported header type: {type(other)}")
        return <int>(other_ptr - base_ptr)

    cpdef void set_bytes(self, int offset, object data):
        cdef const unsigned char[::1] view = data
        cdef int i
        for i in range(view.shape[0]):
            self._buf[offset + i] = view[i]

    cpdef void write_bits(self, int start_bit, int width, unsigned long long value):
        _write_bits(&self._buf[0], start_bit, width, value)

    cpdef unsigned long long read_bits(self, int start_bit, int width):
        return _read_bits(&self._buf[0], start_bit, width)

    cpdef get_bytes(self, int start, int length):
        return PyBytes_FromStringAndSize(<char*>&self._buf[start], length)

    #──────────────────── Header accessors ────────────────────
    @property
    def system_header(self):
        return self._system_header

    @property
    def cxl_cache_header(self):
        return self._cxl_cache_header

    @property
    def h2dreq_header(self):
        return self._h2dreq_header

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._release()

    def __del__(self):
        self._release()

    def __len__(self):
        return 13 + self._data_length

    def __bytes__(self):
        return PyBytes_FromStringAndSize(<char *> self._buf, 13 + self._data_length)

cdef PoolStruct __GenCxlCacheH2DRspPacket_pool

cdef class _GenCxlCacheH2DRspPacket:
    # class member vars
    cdef SystemHeader _system_header
    cdef CxlCacheHeader _cxl_cache_header
    cdef CxlCacheH2DRspHeader _h2drsp_header
    cdef unsigned char _buf[MAX_PACKET_SIZE]
    cdef int _data_length

    #────────────────── Life-cycle management ──────────────────
    cdef void _release(self):
        pool_push(&__GenCxlCacheH2DRspPacket_pool, <PyObject*> self)

    cdef inline void _relocate(self) noexcept nogil:
        cdef unsigned char* base = &self._buf[0]
        self._system_header.attach(base + 0)
        self._cxl_cache_header.attach(base + 2)
        self._h2drsp_header.attach(base + 4)

    #─────────────────────── Builder ───────────────────────
    def __cinit__(self, payload=None):
        if not hasattr(self, '_data_length'):
            # first time only: allocate sub-headers
            self._data_length = 0
            self._system_header = SystemHeader()
            self._cxl_cache_header = CxlCacheHeader()
            self._h2drsp_header = CxlCacheH2DRspHeader()
            self._relocate()
            Py_INCREF(self)

        if payload is not None:
            src = <const unsigned char*> payload
            dst = &self._buf[0]
            n = len(payload)
            if n > MAX_PACKET_SIZE:
                raise ValueError("packet too large")
            memcpy(dst, src, n)
            self._data_length = n - 9

    cdef inline void _build(
        self,
        int system_header__payload_type,
        int cxl_cache_header__msg_class,
        int h2drsp_header__valid,
        int h2drsp_header__cache_opcode,
        int h2drsp_header__cache_id,
        int h2drsp_header__rsp_data,
        int h2drsp_header__cqid,
        const unsigned char* data_src,
        Py_ssize_t data_length
    ) noexcept nogil:
        cdef unsigned char* dst

        memset(&self._buf[0], 0, MAX_PACKET_SIZE)
        self._system_header._set_payload_type(system_header__payload_type)
        self._cxl_cache_header._set_msg_class(cxl_cache_header__msg_class)
        self._h2drsp_header._set_valid(h2drsp_header__valid)
        self._h2drsp_header._set_cache_opcode(h2drsp_header__cache_opcode)
        self._h2drsp_header._set_cache_id(h2drsp_header__cache_id)
        self._h2drsp_header._set_rsp_data(h2drsp_header__rsp_data)
        self._h2drsp_header._set_cqid(h2drsp_header__cqid)
        if data_src:
            dst = &self._buf[9]
            if data_length > MAX_PACKET_SIZE - 9:
                raise ValueError("data too large")
            memcpy(dst, data_src, data_length)
            self._data_length = data_length
        self._system_header._set_payload_length(9 + data_length)

    #────────────────── Python Interface ──────────────────
    @classmethod
    def create(
        cls,
        system_header__payload_type,
        cxl_cache_header__msg_class,
        h2drsp_header__valid,
        h2drsp_header__cache_opcode,
        h2drsp_header__cache_id,
        h2drsp_header__rsp_data,
        h2drsp_header__cqid,
        data: bytes | None = None,
    ):
        cdef PyObject *tmp
        cdef _GenCxlCacheH2DRspPacket pkt
        cdef Py_ssize_t data_length
        cdef const unsigned char* ptr

        if data:
            data_length = len(data)
            ptr = data
        else:
            data_length = 0
            ptr = NULL

        tmp = pool_pop(&__GenCxlCacheH2DRspPacket_pool)
        if tmp == NULL:
            pkt = cls()
        else:
            pkt = <_GenCxlCacheH2DRspPacket> tmp

        pkt._relocate()
        pkt._build(
            system_header__payload_type,
            cxl_cache_header__msg_class,
            h2drsp_header__valid,
            h2drsp_header__cache_opcode,
            h2drsp_header__cache_id,
            h2drsp_header__rsp_data,
            h2drsp_header__cqid, 
            ptr,
            data_length,
        )
        return pkt

    def assign(
        self,
        system_header__payload_type,
        cxl_cache_header__msg_class,
        h2drsp_header__valid,
        h2drsp_header__cache_opcode,
        h2drsp_header__cache_id,
        h2drsp_header__rsp_data,
        h2drsp_header__cqid,
        data: bytes | None = None,
    ):
        cdef Py_ssize_t data_length
        cdef const unsigned char* ptr

        if data:
            data_length = len(data)
            ptr = data
        else:
            data_length = 0
            ptr = NULL

        self._relocate()
        self._build(
            system_header__payload_type,
            cxl_cache_header__msg_class,
            h2drsp_header__valid,
            h2drsp_header__cache_opcode,
            h2drsp_header__cache_id,
            h2drsp_header__rsp_data,
            h2drsp_header__cqid, 
            ptr,
            data_length,
        )

    cpdef set_data(self, data):
        src = <const unsigned char*> data
        dst = &self._buf[9]
        n = len(data)
        if 9 + n > MAX_PACKET_SIZE:
            raise ValueError("packet too large")
        memcpy(dst, src, n)
        self._data_length = n

    cpdef get_data(self):
        return PyBytes_FromStringAndSize(<char*>&self._buf[9], self._data_length)

    cpdef int get_payload_offset(self):
       return 9

    cpdef int get_byte_offset(self, object other):
        cdef uint8_t* base_ptr  = &self._buf[0]
        cdef uint8_t* other_ptr = NULL
        if isinstance(other, SystemHeader):
            other_ptr = (<SystemHeader> other)._p
        elif isinstance(other, CxlCacheHeader):
            other_ptr = (<CxlCacheHeader> other)._p
        elif isinstance(other, CxlCacheH2DRspHeader):
            other_ptr = (<CxlCacheH2DRspHeader> other)._p
        else:
            raise TypeError(f"unsupported header type: {type(other)}")
        return <int>(other_ptr - base_ptr)

    cpdef void set_bytes(self, int offset, object data):
        cdef const unsigned char[::1] view = data
        cdef int i
        for i in range(view.shape[0]):
            self._buf[offset + i] = view[i]

    cpdef void write_bits(self, int start_bit, int width, unsigned long long value):
        _write_bits(&self._buf[0], start_bit, width, value)

    cpdef unsigned long long read_bits(self, int start_bit, int width):
        return _read_bits(&self._buf[0], start_bit, width)

    cpdef get_bytes(self, int start, int length):
        return PyBytes_FromStringAndSize(<char*>&self._buf[start], length)

    #──────────────────── Header accessors ────────────────────
    @property
    def system_header(self):
        return self._system_header

    @property
    def cxl_cache_header(self):
        return self._cxl_cache_header

    @property
    def h2drsp_header(self):
        return self._h2drsp_header

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._release()

    def __del__(self):
        self._release()

    def __len__(self):
        return 9 + self._data_length

    def __bytes__(self):
        return PyBytes_FromStringAndSize(<char *> self._buf, 9 + self._data_length)

cdef PoolStruct __GenCxlCacheH2DDataPacket_pool

cdef class _GenCxlCacheH2DDataPacket:
    # class member vars
    cdef SystemHeader _system_header
    cdef CxlCacheHeader _cxl_cache_header
    cdef CxlCacheH2DDataHeader _h2ddata_header
    cdef unsigned char _buf[MAX_PACKET_SIZE]
    cdef int _data_length

    #────────────────── Life-cycle management ──────────────────
    cdef void _release(self):
        pool_push(&__GenCxlCacheH2DDataPacket_pool, <PyObject*> self)

    cdef inline void _relocate(self) noexcept nogil:
        cdef unsigned char* base = &self._buf[0]
        self._system_header.attach(base + 0)
        self._cxl_cache_header.attach(base + 2)
        self._h2ddata_header.attach(base + 4)

    #─────────────────────── Builder ───────────────────────
    def __cinit__(self, payload=None):
        if not hasattr(self, '_data_length'):
            # first time only: allocate sub-headers
            self._data_length = 0
            self._system_header = SystemHeader()
            self._cxl_cache_header = CxlCacheHeader()
            self._h2ddata_header = CxlCacheH2DDataHeader()
            self._relocate()
            Py_INCREF(self)

        if payload is not None:
            src = <const unsigned char*> payload
            dst = &self._buf[0]
            n = len(payload)
            if n > MAX_PACKET_SIZE:
                raise ValueError("packet too large")
            memcpy(dst, src, n)
            self._data_length = n - 7

    cdef inline void _build(
        self,
        int system_header__payload_type,
        int cxl_cache_header__msg_class,
        int h2ddata_header__valid,
        int h2ddata_header__cache_id,
        int h2ddata_header__cqid,
        const unsigned char* data_src,
        Py_ssize_t data_length
    ) noexcept nogil:
        cdef unsigned char* dst

        memset(&self._buf[0], 0, MAX_PACKET_SIZE)
        self._system_header._set_payload_type(system_header__payload_type)
        self._cxl_cache_header._set_msg_class(cxl_cache_header__msg_class)
        self._h2ddata_header._set_valid(h2ddata_header__valid)
        self._h2ddata_header._set_cache_id(h2ddata_header__cache_id)
        self._h2ddata_header._set_cqid(h2ddata_header__cqid)
        if data_src:
            dst = &self._buf[7]
            if data_length > MAX_PACKET_SIZE - 7:
                raise ValueError("data too large")
            memcpy(dst, data_src, data_length)
            self._data_length = data_length
        self._system_header._set_payload_length(7 + data_length)

    #────────────────── Python Interface ──────────────────
    @classmethod
    def create(
        cls,
        system_header__payload_type,
        cxl_cache_header__msg_class,
        h2ddata_header__valid,
        h2ddata_header__cache_id,
        h2ddata_header__cqid,
        data: bytes | None = None,
    ):
        cdef PyObject *tmp
        cdef _GenCxlCacheH2DDataPacket pkt
        cdef Py_ssize_t data_length
        cdef const unsigned char* ptr

        if data:
            data_length = len(data)
            ptr = data
        else:
            data_length = 0
            ptr = NULL

        tmp = pool_pop(&__GenCxlCacheH2DDataPacket_pool)
        if tmp == NULL:
            pkt = cls()
        else:
            pkt = <_GenCxlCacheH2DDataPacket> tmp

        pkt._relocate()
        pkt._build(
            system_header__payload_type,
            cxl_cache_header__msg_class,
            h2ddata_header__valid,
            h2ddata_header__cache_id,
            h2ddata_header__cqid, 
            ptr,
            data_length,
        )
        return pkt

    def assign(
        self,
        system_header__payload_type,
        cxl_cache_header__msg_class,
        h2ddata_header__valid,
        h2ddata_header__cache_id,
        h2ddata_header__cqid,
        data: bytes | None = None,
    ):
        cdef Py_ssize_t data_length
        cdef const unsigned char* ptr

        if data:
            data_length = len(data)
            ptr = data
        else:
            data_length = 0
            ptr = NULL

        self._relocate()
        self._build(
            system_header__payload_type,
            cxl_cache_header__msg_class,
            h2ddata_header__valid,
            h2ddata_header__cache_id,
            h2ddata_header__cqid, 
            ptr,
            data_length,
        )

    cpdef set_data(self, data):
        src = <const unsigned char*> data
        dst = &self._buf[7]
        n = len(data)
        if 7 + n > MAX_PACKET_SIZE:
            raise ValueError("packet too large")
        memcpy(dst, src, n)
        self._data_length = n

    cpdef get_data(self):
        return PyBytes_FromStringAndSize(<char*>&self._buf[7], self._data_length)

    cpdef int get_payload_offset(self):
       return 7

    cpdef int get_byte_offset(self, object other):
        cdef uint8_t* base_ptr  = &self._buf[0]
        cdef uint8_t* other_ptr = NULL
        if isinstance(other, SystemHeader):
            other_ptr = (<SystemHeader> other)._p
        elif isinstance(other, CxlCacheHeader):
            other_ptr = (<CxlCacheHeader> other)._p
        elif isinstance(other, CxlCacheH2DDataHeader):
            other_ptr = (<CxlCacheH2DDataHeader> other)._p
        else:
            raise TypeError(f"unsupported header type: {type(other)}")
        return <int>(other_ptr - base_ptr)

    cpdef void set_bytes(self, int offset, object data):
        cdef const unsigned char[::1] view = data
        cdef int i
        for i in range(view.shape[0]):
            self._buf[offset + i] = view[i]

    cpdef void write_bits(self, int start_bit, int width, unsigned long long value):
        _write_bits(&self._buf[0], start_bit, width, value)

    cpdef unsigned long long read_bits(self, int start_bit, int width):
        return _read_bits(&self._buf[0], start_bit, width)

    cpdef get_bytes(self, int start, int length):
        return PyBytes_FromStringAndSize(<char*>&self._buf[start], length)

    #──────────────────── Header accessors ────────────────────
    @property
    def system_header(self):
        return self._system_header

    @property
    def cxl_cache_header(self):
        return self._cxl_cache_header

    @property
    def h2ddata_header(self):
        return self._h2ddata_header

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._release()

    def __del__(self):
        self._release()

    def __len__(self):
        return 7 + self._data_length

    def __bytes__(self):
        return PyBytes_FromStringAndSize(<char *> self._buf, 7 + self._data_length)

cdef PoolStruct __GenCxlMemBasePacket_pool

cdef class _GenCxlMemBasePacket:
    # class member vars
    cdef SystemHeader _system_header
    cdef CxlMemHeader _cxl_mem_header
    cdef unsigned char _buf[MAX_PACKET_SIZE]
    cdef int _data_length

    #────────────────── Life-cycle management ──────────────────
    cdef void _release(self):
        pool_push(&__GenCxlMemBasePacket_pool, <PyObject*> self)

    cdef inline void _relocate(self) noexcept nogil:
        cdef unsigned char* base = &self._buf[0]
        self._system_header.attach(base + 0)
        self._cxl_mem_header.attach(base + 2)

    #─────────────────────── Builder ───────────────────────
    def __cinit__(self, payload=None):
        if not hasattr(self, '_data_length'):
            # first time only: allocate sub-headers
            self._data_length = 0
            self._system_header = SystemHeader()
            self._cxl_mem_header = CxlMemHeader()
            self._relocate()
            Py_INCREF(self)

        if payload is not None:
            src = <const unsigned char*> payload
            dst = &self._buf[0]
            n = len(payload)
            if n > MAX_PACKET_SIZE:
                raise ValueError("packet too large")
            memcpy(dst, src, n)
            self._data_length = n - 4

    #────────────────── Python Interface ──────────────────
    cpdef set_data(self, data):
        src = <const unsigned char*> data
        dst = &self._buf[4]
        n = len(data)
        if 4 + n > MAX_PACKET_SIZE:
            raise ValueError("packet too large")
        memcpy(dst, src, n)
        self._data_length = n

    cpdef get_data(self):
        return PyBytes_FromStringAndSize(<char*>&self._buf[4], self._data_length)

    cpdef int get_payload_offset(self):
       return 4

    cpdef int get_byte_offset(self, object other):
        cdef uint8_t* base_ptr  = &self._buf[0]
        cdef uint8_t* other_ptr = NULL
        if isinstance(other, SystemHeader):
            other_ptr = (<SystemHeader> other)._p
        elif isinstance(other, CxlMemHeader):
            other_ptr = (<CxlMemHeader> other)._p
        else:
            raise TypeError(f"unsupported header type: {type(other)}")
        return <int>(other_ptr - base_ptr)

    cpdef void set_bytes(self, int offset, object data):
        cdef const unsigned char[::1] view = data
        cdef int i
        for i in range(view.shape[0]):
            self._buf[offset + i] = view[i]

    cpdef void write_bits(self, int start_bit, int width, unsigned long long value):
        _write_bits(&self._buf[0], start_bit, width, value)

    cpdef unsigned long long read_bits(self, int start_bit, int width):
        return _read_bits(&self._buf[0], start_bit, width)

    cpdef get_bytes(self, int start, int length):
        return PyBytes_FromStringAndSize(<char*>&self._buf[start], length)

    #──────────────────── Header accessors ────────────────────
    @property
    def system_header(self):
        return self._system_header

    @property
    def cxl_mem_header(self):
        return self._cxl_mem_header

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._release()

    def __del__(self):
        self._release()

    def __len__(self):
        return 4 + self._data_length

    def __bytes__(self):
        return PyBytes_FromStringAndSize(<char *> self._buf, 4 + self._data_length)

cdef PoolStruct __GenCxlMemM2SReqPacket_pool

cdef class _GenCxlMemM2SReqPacket:
    # class member vars
    cdef SystemHeader _system_header
    cdef CxlMemHeader _cxl_mem_header
    cdef CxlMemM2SReqHeader _m2sreq_header
    cdef unsigned char _buf[MAX_PACKET_SIZE]
    cdef int _data_length

    #────────────────── Life-cycle management ──────────────────
    cdef void _release(self):
        pool_push(&__GenCxlMemM2SReqPacket_pool, <PyObject*> self)

    cdef inline void _relocate(self) noexcept nogil:
        cdef unsigned char* base = &self._buf[0]
        self._system_header.attach(base + 0)
        self._cxl_mem_header.attach(base + 2)
        self._m2sreq_header.attach(base + 4)

    #─────────────────────── Builder ───────────────────────
    def __cinit__(self, payload=None):
        if not hasattr(self, '_data_length'):
            # first time only: allocate sub-headers
            self._data_length = 0
            self._system_header = SystemHeader()
            self._cxl_mem_header = CxlMemHeader()
            self._m2sreq_header = CxlMemM2SReqHeader()
            self._relocate()
            Py_INCREF(self)

        if payload is not None:
            src = <const unsigned char*> payload
            dst = &self._buf[0]
            n = len(payload)
            if n > MAX_PACKET_SIZE:
                raise ValueError("packet too large")
            memcpy(dst, src, n)
            self._data_length = n - 17

    cdef inline void _build(
        self,
        int system_header__payload_type,
        int cxl_mem_header__msg_class,
        int m2sreq_header__valid,
        int m2sreq_header__mem_opcode,
        int m2sreq_header__meta_field,
        int m2sreq_header__meta_value,
        int m2sreq_header__snp_type,
        int m2sreq_header__ld_id,
        unsigned long long m2sreq_header__addr,
        const unsigned char* data_src,
        Py_ssize_t data_length
    ) noexcept nogil:
        cdef unsigned char* dst

        memset(&self._buf[0], 0, MAX_PACKET_SIZE)
        self._system_header._set_payload_type(system_header__payload_type)
        self._cxl_mem_header._set_msg_class(cxl_mem_header__msg_class)
        self._m2sreq_header._set_valid(m2sreq_header__valid)
        self._m2sreq_header._set_mem_opcode(m2sreq_header__mem_opcode)
        self._m2sreq_header._set_meta_field(m2sreq_header__meta_field)
        self._m2sreq_header._set_meta_value(m2sreq_header__meta_value)
        self._m2sreq_header._set_snp_type(m2sreq_header__snp_type)
        self._m2sreq_header._set_ld_id(m2sreq_header__ld_id)
        self._m2sreq_header._set_addr(m2sreq_header__addr)
        if data_src:
            dst = &self._buf[17]
            if data_length > MAX_PACKET_SIZE - 17:
                raise ValueError("data too large")
            memcpy(dst, data_src, data_length)
            self._data_length = data_length
        self._system_header._set_payload_length(17 + data_length)

    #────────────────── Python Interface ──────────────────
    @classmethod
    def create(
        cls,
        system_header__payload_type,
        cxl_mem_header__msg_class,
        m2sreq_header__valid,
        m2sreq_header__mem_opcode,
        m2sreq_header__meta_field,
        m2sreq_header__meta_value,
        m2sreq_header__snp_type,
        m2sreq_header__ld_id,
        m2sreq_header__addr,
        data: bytes | None = None,
    ):
        cdef PyObject *tmp
        cdef _GenCxlMemM2SReqPacket pkt
        cdef Py_ssize_t data_length
        cdef const unsigned char* ptr

        if data:
            data_length = len(data)
            ptr = data
        else:
            data_length = 0
            ptr = NULL

        tmp = pool_pop(&__GenCxlMemM2SReqPacket_pool)
        if tmp == NULL:
            pkt = cls()
        else:
            pkt = <_GenCxlMemM2SReqPacket> tmp

        pkt._relocate()
        pkt._build(
            system_header__payload_type,
            cxl_mem_header__msg_class,
            m2sreq_header__valid,
            m2sreq_header__mem_opcode,
            m2sreq_header__meta_field,
            m2sreq_header__meta_value,
            m2sreq_header__snp_type,
            m2sreq_header__ld_id,
            m2sreq_header__addr, 
            ptr,
            data_length,
        )
        return pkt

    def assign(
        self,
        system_header__payload_type,
        cxl_mem_header__msg_class,
        m2sreq_header__valid,
        m2sreq_header__mem_opcode,
        m2sreq_header__meta_field,
        m2sreq_header__meta_value,
        m2sreq_header__snp_type,
        m2sreq_header__ld_id,
        m2sreq_header__addr,
        data: bytes | None = None,
    ):
        cdef Py_ssize_t data_length
        cdef const unsigned char* ptr

        if data:
            data_length = len(data)
            ptr = data
        else:
            data_length = 0
            ptr = NULL

        self._relocate()
        self._build(
            system_header__payload_type,
            cxl_mem_header__msg_class,
            m2sreq_header__valid,
            m2sreq_header__mem_opcode,
            m2sreq_header__meta_field,
            m2sreq_header__meta_value,
            m2sreq_header__snp_type,
            m2sreq_header__ld_id,
            m2sreq_header__addr, 
            ptr,
            data_length,
        )

    cpdef set_data(self, data):
        src = <const unsigned char*> data
        dst = &self._buf[17]
        n = len(data)
        if 17 + n > MAX_PACKET_SIZE:
            raise ValueError("packet too large")
        memcpy(dst, src, n)
        self._data_length = n

    cpdef get_data(self):
        return PyBytes_FromStringAndSize(<char*>&self._buf[17], self._data_length)

    cpdef int get_payload_offset(self):
       return 17

    cpdef int get_byte_offset(self, object other):
        cdef uint8_t* base_ptr  = &self._buf[0]
        cdef uint8_t* other_ptr = NULL
        if isinstance(other, SystemHeader):
            other_ptr = (<SystemHeader> other)._p
        elif isinstance(other, CxlMemHeader):
            other_ptr = (<CxlMemHeader> other)._p
        elif isinstance(other, CxlMemM2SReqHeader):
            other_ptr = (<CxlMemM2SReqHeader> other)._p
        else:
            raise TypeError(f"unsupported header type: {type(other)}")
        return <int>(other_ptr - base_ptr)

    cpdef void set_bytes(self, int offset, object data):
        cdef const unsigned char[::1] view = data
        cdef int i
        for i in range(view.shape[0]):
            self._buf[offset + i] = view[i]

    cpdef void write_bits(self, int start_bit, int width, unsigned long long value):
        _write_bits(&self._buf[0], start_bit, width, value)

    cpdef unsigned long long read_bits(self, int start_bit, int width):
        return _read_bits(&self._buf[0], start_bit, width)

    cpdef get_bytes(self, int start, int length):
        return PyBytes_FromStringAndSize(<char*>&self._buf[start], length)

    #──────────────────── Header accessors ────────────────────
    @property
    def system_header(self):
        return self._system_header

    @property
    def cxl_mem_header(self):
        return self._cxl_mem_header

    @property
    def m2sreq_header(self):
        return self._m2sreq_header

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._release()

    def __del__(self):
        self._release()

    def __len__(self):
        return 17 + self._data_length

    def __bytes__(self):
        return PyBytes_FromStringAndSize(<char *> self._buf, 17 + self._data_length)

cdef PoolStruct __GenCxlMemM2SRwDPacket_pool

cdef class _GenCxlMemM2SRwDPacket:
    # class member vars
    cdef SystemHeader _system_header
    cdef CxlMemHeader _cxl_mem_header
    cdef CxlMemM2SRwDHeader _m2srwd_header
    cdef unsigned char _buf[MAX_PACKET_SIZE]
    cdef int _data_length

    #────────────────── Life-cycle management ──────────────────
    cdef void _release(self):
        pool_push(&__GenCxlMemM2SRwDPacket_pool, <PyObject*> self)

    cdef inline void _relocate(self) noexcept nogil:
        cdef unsigned char* base = &self._buf[0]
        self._system_header.attach(base + 0)
        self._cxl_mem_header.attach(base + 2)
        self._m2srwd_header.attach(base + 4)

    #─────────────────────── Builder ───────────────────────
    def __cinit__(self, payload=None):
        if not hasattr(self, '_data_length'):
            # first time only: allocate sub-headers
            self._data_length = 0
            self._system_header = SystemHeader()
            self._cxl_mem_header = CxlMemHeader()
            self._m2srwd_header = CxlMemM2SRwDHeader()
            self._relocate()
            Py_INCREF(self)

        if payload is not None:
            src = <const unsigned char*> payload
            dst = &self._buf[0]
            n = len(payload)
            if n > MAX_PACKET_SIZE:
                raise ValueError("packet too large")
            memcpy(dst, src, n)
            self._data_length = n - 17

    cdef inline void _build(
        self,
        int system_header__payload_type,
        int cxl_mem_header__msg_class,
        int m2srwd_header__valid,
        int m2srwd_header__mem_opcode,
        int m2srwd_header__meta_field,
        int m2srwd_header__meta_value,
        int m2srwd_header__snp_type,
        int m2srwd_header__ld_id,
        unsigned long long m2srwd_header__addr,
        const unsigned char* data_src,
        Py_ssize_t data_length
    ) noexcept nogil:
        cdef unsigned char* dst

        memset(&self._buf[0], 0, MAX_PACKET_SIZE)
        self._system_header._set_payload_type(system_header__payload_type)
        self._cxl_mem_header._set_msg_class(cxl_mem_header__msg_class)
        self._m2srwd_header._set_valid(m2srwd_header__valid)
        self._m2srwd_header._set_mem_opcode(m2srwd_header__mem_opcode)
        self._m2srwd_header._set_meta_field(m2srwd_header__meta_field)
        self._m2srwd_header._set_meta_value(m2srwd_header__meta_value)
        self._m2srwd_header._set_snp_type(m2srwd_header__snp_type)
        self._m2srwd_header._set_ld_id(m2srwd_header__ld_id)
        self._m2srwd_header._set_addr(m2srwd_header__addr)
        if data_src:
            dst = &self._buf[17]
            if data_length > MAX_PACKET_SIZE - 17:
                raise ValueError("data too large")
            memcpy(dst, data_src, data_length)
            self._data_length = data_length
        self._system_header._set_payload_length(17 + data_length)

    #────────────────── Python Interface ──────────────────
    @classmethod
    def create(
        cls,
        system_header__payload_type,
        cxl_mem_header__msg_class,
        m2srwd_header__valid,
        m2srwd_header__mem_opcode,
        m2srwd_header__meta_field,
        m2srwd_header__meta_value,
        m2srwd_header__snp_type,
        m2srwd_header__ld_id,
        m2srwd_header__addr,
        data: bytes | None = None,
    ):
        cdef PyObject *tmp
        cdef _GenCxlMemM2SRwDPacket pkt
        cdef Py_ssize_t data_length
        cdef const unsigned char* ptr

        if data:
            data_length = len(data)
            ptr = data
        else:
            data_length = 0
            ptr = NULL

        tmp = pool_pop(&__GenCxlMemM2SRwDPacket_pool)
        if tmp == NULL:
            pkt = cls()
        else:
            pkt = <_GenCxlMemM2SRwDPacket> tmp

        pkt._relocate()
        pkt._build(
            system_header__payload_type,
            cxl_mem_header__msg_class,
            m2srwd_header__valid,
            m2srwd_header__mem_opcode,
            m2srwd_header__meta_field,
            m2srwd_header__meta_value,
            m2srwd_header__snp_type,
            m2srwd_header__ld_id,
            m2srwd_header__addr, 
            ptr,
            data_length,
        )
        return pkt

    def assign(
        self,
        system_header__payload_type,
        cxl_mem_header__msg_class,
        m2srwd_header__valid,
        m2srwd_header__mem_opcode,
        m2srwd_header__meta_field,
        m2srwd_header__meta_value,
        m2srwd_header__snp_type,
        m2srwd_header__ld_id,
        m2srwd_header__addr,
        data: bytes | None = None,
    ):
        cdef Py_ssize_t data_length
        cdef const unsigned char* ptr

        if data:
            data_length = len(data)
            ptr = data
        else:
            data_length = 0
            ptr = NULL

        self._relocate()
        self._build(
            system_header__payload_type,
            cxl_mem_header__msg_class,
            m2srwd_header__valid,
            m2srwd_header__mem_opcode,
            m2srwd_header__meta_field,
            m2srwd_header__meta_value,
            m2srwd_header__snp_type,
            m2srwd_header__ld_id,
            m2srwd_header__addr, 
            ptr,
            data_length,
        )

    cpdef set_data(self, data):
        src = <const unsigned char*> data
        dst = &self._buf[17]
        n = len(data)
        if 17 + n > MAX_PACKET_SIZE:
            raise ValueError("packet too large")
        memcpy(dst, src, n)
        self._data_length = n

    cpdef get_data(self):
        return PyBytes_FromStringAndSize(<char*>&self._buf[17], self._data_length)

    cpdef int get_payload_offset(self):
       return 17

    cpdef int get_byte_offset(self, object other):
        cdef uint8_t* base_ptr  = &self._buf[0]
        cdef uint8_t* other_ptr = NULL
        if isinstance(other, SystemHeader):
            other_ptr = (<SystemHeader> other)._p
        elif isinstance(other, CxlMemHeader):
            other_ptr = (<CxlMemHeader> other)._p
        elif isinstance(other, CxlMemM2SRwDHeader):
            other_ptr = (<CxlMemM2SRwDHeader> other)._p
        else:
            raise TypeError(f"unsupported header type: {type(other)}")
        return <int>(other_ptr - base_ptr)

    cpdef void set_bytes(self, int offset, object data):
        cdef const unsigned char[::1] view = data
        cdef int i
        for i in range(view.shape[0]):
            self._buf[offset + i] = view[i]

    cpdef void write_bits(self, int start_bit, int width, unsigned long long value):
        _write_bits(&self._buf[0], start_bit, width, value)

    cpdef unsigned long long read_bits(self, int start_bit, int width):
        return _read_bits(&self._buf[0], start_bit, width)

    cpdef get_bytes(self, int start, int length):
        return PyBytes_FromStringAndSize(<char*>&self._buf[start], length)

    #──────────────────── Header accessors ────────────────────
    @property
    def system_header(self):
        return self._system_header

    @property
    def cxl_mem_header(self):
        return self._cxl_mem_header

    @property
    def m2srwd_header(self):
        return self._m2srwd_header

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._release()

    def __del__(self):
        self._release()

    def __len__(self):
        return 17 + self._data_length

    def __bytes__(self):
        return PyBytes_FromStringAndSize(<char *> self._buf, 17 + self._data_length)

cdef PoolStruct __GenCxlMemM2SBIRspPacket_pool

cdef class _GenCxlMemM2SBIRspPacket:
    # class member vars
    cdef SystemHeader _system_header
    cdef CxlMemHeader _cxl_mem_header
    cdef CxlMemM2SBIRspHeader _m2sbirsp_header
    cdef unsigned char _buf[MAX_PACKET_SIZE]
    cdef int _data_length

    #────────────────── Life-cycle management ──────────────────
    cdef void _release(self):
        pool_push(&__GenCxlMemM2SBIRspPacket_pool, <PyObject*> self)

    cdef inline void _relocate(self) noexcept nogil:
        cdef unsigned char* base = &self._buf[0]
        self._system_header.attach(base + 0)
        self._cxl_mem_header.attach(base + 2)
        self._m2sbirsp_header.attach(base + 4)

    #─────────────────────── Builder ───────────────────────
    def __cinit__(self, payload=None):
        if not hasattr(self, '_data_length'):
            # first time only: allocate sub-headers
            self._data_length = 0
            self._system_header = SystemHeader()
            self._cxl_mem_header = CxlMemHeader()
            self._m2sbirsp_header = CxlMemM2SBIRspHeader()
            self._relocate()
            Py_INCREF(self)

        if payload is not None:
            src = <const unsigned char*> payload
            dst = &self._buf[0]
            n = len(payload)
            if n > MAX_PACKET_SIZE:
                raise ValueError("packet too large")
            memcpy(dst, src, n)
            self._data_length = n - 9

    cdef inline void _build(
        self,
        int system_header__payload_type,
        int cxl_mem_header__msg_class,
        int m2sbirsp_header__valid,
        int m2sbirsp_header__opcode,
        int m2sbirsp_header__low_addr,
        int m2sbirsp_header__bi_id,
        int m2sbirsp_header__bi_tag,
        const unsigned char* data_src,
        Py_ssize_t data_length
    ) noexcept nogil:
        cdef unsigned char* dst

        memset(&self._buf[0], 0, MAX_PACKET_SIZE)
        self._system_header._set_payload_type(system_header__payload_type)
        self._cxl_mem_header._set_msg_class(cxl_mem_header__msg_class)
        self._m2sbirsp_header._set_valid(m2sbirsp_header__valid)
        self._m2sbirsp_header._set_opcode(m2sbirsp_header__opcode)
        self._m2sbirsp_header._set_low_addr(m2sbirsp_header__low_addr)
        self._m2sbirsp_header._set_bi_id(m2sbirsp_header__bi_id)
        self._m2sbirsp_header._set_bi_tag(m2sbirsp_header__bi_tag)
        if data_src:
            dst = &self._buf[9]
            if data_length > MAX_PACKET_SIZE - 9:
                raise ValueError("data too large")
            memcpy(dst, data_src, data_length)
            self._data_length = data_length
        self._system_header._set_payload_length(9 + data_length)

    #────────────────── Python Interface ──────────────────
    @classmethod
    def create(
        cls,
        system_header__payload_type,
        cxl_mem_header__msg_class,
        m2sbirsp_header__valid,
        m2sbirsp_header__opcode,
        m2sbirsp_header__low_addr,
        m2sbirsp_header__bi_id,
        m2sbirsp_header__bi_tag,
        data: bytes | None = None,
    ):
        cdef PyObject *tmp
        cdef _GenCxlMemM2SBIRspPacket pkt
        cdef Py_ssize_t data_length
        cdef const unsigned char* ptr

        if data:
            data_length = len(data)
            ptr = data
        else:
            data_length = 0
            ptr = NULL

        tmp = pool_pop(&__GenCxlMemM2SBIRspPacket_pool)
        if tmp == NULL:
            pkt = cls()
        else:
            pkt = <_GenCxlMemM2SBIRspPacket> tmp

        pkt._relocate()
        pkt._build(
            system_header__payload_type,
            cxl_mem_header__msg_class,
            m2sbirsp_header__valid,
            m2sbirsp_header__opcode,
            m2sbirsp_header__low_addr,
            m2sbirsp_header__bi_id,
            m2sbirsp_header__bi_tag, 
            ptr,
            data_length,
        )
        return pkt

    def assign(
        self,
        system_header__payload_type,
        cxl_mem_header__msg_class,
        m2sbirsp_header__valid,
        m2sbirsp_header__opcode,
        m2sbirsp_header__low_addr,
        m2sbirsp_header__bi_id,
        m2sbirsp_header__bi_tag,
        data: bytes | None = None,
    ):
        cdef Py_ssize_t data_length
        cdef const unsigned char* ptr

        if data:
            data_length = len(data)
            ptr = data
        else:
            data_length = 0
            ptr = NULL

        self._relocate()
        self._build(
            system_header__payload_type,
            cxl_mem_header__msg_class,
            m2sbirsp_header__valid,
            m2sbirsp_header__opcode,
            m2sbirsp_header__low_addr,
            m2sbirsp_header__bi_id,
            m2sbirsp_header__bi_tag, 
            ptr,
            data_length,
        )

    cpdef set_data(self, data):
        src = <const unsigned char*> data
        dst = &self._buf[9]
        n = len(data)
        if 9 + n > MAX_PACKET_SIZE:
            raise ValueError("packet too large")
        memcpy(dst, src, n)
        self._data_length = n

    cpdef get_data(self):
        return PyBytes_FromStringAndSize(<char*>&self._buf[9], self._data_length)

    cpdef int get_payload_offset(self):
       return 9

    cpdef int get_byte_offset(self, object other):
        cdef uint8_t* base_ptr  = &self._buf[0]
        cdef uint8_t* other_ptr = NULL
        if isinstance(other, SystemHeader):
            other_ptr = (<SystemHeader> other)._p
        elif isinstance(other, CxlMemHeader):
            other_ptr = (<CxlMemHeader> other)._p
        elif isinstance(other, CxlMemM2SBIRspHeader):
            other_ptr = (<CxlMemM2SBIRspHeader> other)._p
        else:
            raise TypeError(f"unsupported header type: {type(other)}")
        return <int>(other_ptr - base_ptr)

    cpdef void set_bytes(self, int offset, object data):
        cdef const unsigned char[::1] view = data
        cdef int i
        for i in range(view.shape[0]):
            self._buf[offset + i] = view[i]

    cpdef void write_bits(self, int start_bit, int width, unsigned long long value):
        _write_bits(&self._buf[0], start_bit, width, value)

    cpdef unsigned long long read_bits(self, int start_bit, int width):
        return _read_bits(&self._buf[0], start_bit, width)

    cpdef get_bytes(self, int start, int length):
        return PyBytes_FromStringAndSize(<char*>&self._buf[start], length)

    #──────────────────── Header accessors ────────────────────
    @property
    def system_header(self):
        return self._system_header

    @property
    def cxl_mem_header(self):
        return self._cxl_mem_header

    @property
    def m2sbirsp_header(self):
        return self._m2sbirsp_header

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._release()

    def __del__(self):
        self._release()

    def __len__(self):
        return 9 + self._data_length

    def __bytes__(self):
        return PyBytes_FromStringAndSize(<char *> self._buf, 9 + self._data_length)

cdef PoolStruct __GenCxlMemS2MBISnpPacket_pool

cdef class _GenCxlMemS2MBISnpPacket:
    # class member vars
    cdef SystemHeader _system_header
    cdef CxlMemHeader _cxl_mem_header
    cdef CxlMemS2MBISnpHeader _s2mbisnp_header
    cdef unsigned char _buf[MAX_PACKET_SIZE]
    cdef int _data_length

    #────────────────── Life-cycle management ──────────────────
    cdef void _release(self):
        pool_push(&__GenCxlMemS2MBISnpPacket_pool, <PyObject*> self)

    cdef inline void _relocate(self) noexcept nogil:
        cdef unsigned char* base = &self._buf[0]
        self._system_header.attach(base + 0)
        self._cxl_mem_header.attach(base + 2)
        self._s2mbisnp_header.attach(base + 4)

    #─────────────────────── Builder ───────────────────────
    def __cinit__(self, payload=None):
        if not hasattr(self, '_data_length'):
            # first time only: allocate sub-headers
            self._data_length = 0
            self._system_header = SystemHeader()
            self._cxl_mem_header = CxlMemHeader()
            self._s2mbisnp_header = CxlMemS2MBISnpHeader()
            self._relocate()
            Py_INCREF(self)

        if payload is not None:
            src = <const unsigned char*> payload
            dst = &self._buf[0]
            n = len(payload)
            if n > MAX_PACKET_SIZE:
                raise ValueError("packet too large")
            memcpy(dst, src, n)
            self._data_length = n - 14

    cdef inline void _build(
        self,
        int system_header__payload_type,
        int cxl_mem_header__msg_class,
        int s2mbisnp_header__valid,
        int s2mbisnp_header__opcode,
        int s2mbisnp_header__bi_id,
        int s2mbisnp_header__bi_tag,
        unsigned long long s2mbisnp_header__addr,
        const unsigned char* data_src,
        Py_ssize_t data_length
    ) noexcept nogil:
        cdef unsigned char* dst

        memset(&self._buf[0], 0, MAX_PACKET_SIZE)
        self._system_header._set_payload_type(system_header__payload_type)
        self._cxl_mem_header._set_msg_class(cxl_mem_header__msg_class)
        self._s2mbisnp_header._set_valid(s2mbisnp_header__valid)
        self._s2mbisnp_header._set_opcode(s2mbisnp_header__opcode)
        self._s2mbisnp_header._set_bi_id(s2mbisnp_header__bi_id)
        self._s2mbisnp_header._set_bi_tag(s2mbisnp_header__bi_tag)
        self._s2mbisnp_header._set_addr(s2mbisnp_header__addr)
        if data_src:
            dst = &self._buf[14]
            if data_length > MAX_PACKET_SIZE - 14:
                raise ValueError("data too large")
            memcpy(dst, data_src, data_length)
            self._data_length = data_length
        self._system_header._set_payload_length(14 + data_length)

    #────────────────── Python Interface ──────────────────
    @classmethod
    def create(
        cls,
        system_header__payload_type,
        cxl_mem_header__msg_class,
        s2mbisnp_header__valid,
        s2mbisnp_header__opcode,
        s2mbisnp_header__bi_id,
        s2mbisnp_header__bi_tag,
        s2mbisnp_header__addr,
        data: bytes | None = None,
    ):
        cdef PyObject *tmp
        cdef _GenCxlMemS2MBISnpPacket pkt
        cdef Py_ssize_t data_length
        cdef const unsigned char* ptr

        if data:
            data_length = len(data)
            ptr = data
        else:
            data_length = 0
            ptr = NULL

        tmp = pool_pop(&__GenCxlMemS2MBISnpPacket_pool)
        if tmp == NULL:
            pkt = cls()
        else:
            pkt = <_GenCxlMemS2MBISnpPacket> tmp

        pkt._relocate()
        pkt._build(
            system_header__payload_type,
            cxl_mem_header__msg_class,
            s2mbisnp_header__valid,
            s2mbisnp_header__opcode,
            s2mbisnp_header__bi_id,
            s2mbisnp_header__bi_tag,
            s2mbisnp_header__addr, 
            ptr,
            data_length,
        )
        return pkt

    def assign(
        self,
        system_header__payload_type,
        cxl_mem_header__msg_class,
        s2mbisnp_header__valid,
        s2mbisnp_header__opcode,
        s2mbisnp_header__bi_id,
        s2mbisnp_header__bi_tag,
        s2mbisnp_header__addr,
        data: bytes | None = None,
    ):
        cdef Py_ssize_t data_length
        cdef const unsigned char* ptr

        if data:
            data_length = len(data)
            ptr = data
        else:
            data_length = 0
            ptr = NULL

        self._relocate()
        self._build(
            system_header__payload_type,
            cxl_mem_header__msg_class,
            s2mbisnp_header__valid,
            s2mbisnp_header__opcode,
            s2mbisnp_header__bi_id,
            s2mbisnp_header__bi_tag,
            s2mbisnp_header__addr, 
            ptr,
            data_length,
        )

    cpdef set_data(self, data):
        src = <const unsigned char*> data
        dst = &self._buf[14]
        n = len(data)
        if 14 + n > MAX_PACKET_SIZE:
            raise ValueError("packet too large")
        memcpy(dst, src, n)
        self._data_length = n

    cpdef get_data(self):
        return PyBytes_FromStringAndSize(<char*>&self._buf[14], self._data_length)

    cpdef int get_payload_offset(self):
       return 14

    cpdef int get_byte_offset(self, object other):
        cdef uint8_t* base_ptr  = &self._buf[0]
        cdef uint8_t* other_ptr = NULL
        if isinstance(other, SystemHeader):
            other_ptr = (<SystemHeader> other)._p
        elif isinstance(other, CxlMemHeader):
            other_ptr = (<CxlMemHeader> other)._p
        elif isinstance(other, CxlMemS2MBISnpHeader):
            other_ptr = (<CxlMemS2MBISnpHeader> other)._p
        else:
            raise TypeError(f"unsupported header type: {type(other)}")
        return <int>(other_ptr - base_ptr)

    cpdef void set_bytes(self, int offset, object data):
        cdef const unsigned char[::1] view = data
        cdef int i
        for i in range(view.shape[0]):
            self._buf[offset + i] = view[i]

    cpdef void write_bits(self, int start_bit, int width, unsigned long long value):
        _write_bits(&self._buf[0], start_bit, width, value)

    cpdef unsigned long long read_bits(self, int start_bit, int width):
        return _read_bits(&self._buf[0], start_bit, width)

    cpdef get_bytes(self, int start, int length):
        return PyBytes_FromStringAndSize(<char*>&self._buf[start], length)

    #──────────────────── Header accessors ────────────────────
    @property
    def system_header(self):
        return self._system_header

    @property
    def cxl_mem_header(self):
        return self._cxl_mem_header

    @property
    def s2mbisnp_header(self):
        return self._s2mbisnp_header

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._release()

    def __del__(self):
        self._release()

    def __len__(self):
        return 14 + self._data_length

    def __bytes__(self):
        return PyBytes_FromStringAndSize(<char *> self._buf, 14 + self._data_length)

cdef PoolStruct __GenCxlMemS2MNDRPacket_pool

cdef class _GenCxlMemS2MNDRPacket:
    # class member vars
    cdef SystemHeader _system_header
    cdef CxlMemHeader _cxl_mem_header
    cdef CxlMemS2MNDRHeader _s2mndr_header
    cdef unsigned char _buf[MAX_PACKET_SIZE]
    cdef int _data_length

    #────────────────── Life-cycle management ──────────────────
    cdef void _release(self):
        pool_push(&__GenCxlMemS2MNDRPacket_pool, <PyObject*> self)

    cdef inline void _relocate(self) noexcept nogil:
        cdef unsigned char* base = &self._buf[0]
        self._system_header.attach(base + 0)
        self._cxl_mem_header.attach(base + 2)
        self._s2mndr_header.attach(base + 4)

    #─────────────────────── Builder ───────────────────────
    def __cinit__(self, payload=None):
        if not hasattr(self, '_data_length'):
            # first time only: allocate sub-headers
            self._data_length = 0
            self._system_header = SystemHeader()
            self._cxl_mem_header = CxlMemHeader()
            self._s2mndr_header = CxlMemS2MNDRHeader()
            self._relocate()
            Py_INCREF(self)

        if payload is not None:
            src = <const unsigned char*> payload
            dst = &self._buf[0]
            n = len(payload)
            if n > MAX_PACKET_SIZE:
                raise ValueError("packet too large")
            memcpy(dst, src, n)
            self._data_length = n - 9

    cdef inline void _build(
        self,
        int system_header__payload_type,
        int cxl_mem_header__msg_class,
        int s2mndr_header__valid,
        int s2mndr_header__opcode,
        int s2mndr_header__meta_field,
        int s2mndr_header__meta_value,
        int s2mndr_header__ld_id,
        const unsigned char* data_src,
        Py_ssize_t data_length
    ) noexcept nogil:
        cdef unsigned char* dst

        memset(&self._buf[0], 0, MAX_PACKET_SIZE)
        self._system_header._set_payload_type(system_header__payload_type)
        self._cxl_mem_header._set_msg_class(cxl_mem_header__msg_class)
        self._s2mndr_header._set_valid(s2mndr_header__valid)
        self._s2mndr_header._set_opcode(s2mndr_header__opcode)
        self._s2mndr_header._set_meta_field(s2mndr_header__meta_field)
        self._s2mndr_header._set_meta_value(s2mndr_header__meta_value)
        self._s2mndr_header._set_ld_id(s2mndr_header__ld_id)
        if data_src:
            dst = &self._buf[9]
            if data_length > MAX_PACKET_SIZE - 9:
                raise ValueError("data too large")
            memcpy(dst, data_src, data_length)
            self._data_length = data_length
        self._system_header._set_payload_length(9 + data_length)

    #────────────────── Python Interface ──────────────────
    @classmethod
    def create(
        cls,
        system_header__payload_type,
        cxl_mem_header__msg_class,
        s2mndr_header__valid,
        s2mndr_header__opcode,
        s2mndr_header__meta_field,
        s2mndr_header__meta_value,
        s2mndr_header__ld_id,
        data: bytes | None = None,
    ):
        cdef PyObject *tmp
        cdef _GenCxlMemS2MNDRPacket pkt
        cdef Py_ssize_t data_length
        cdef const unsigned char* ptr

        if data:
            data_length = len(data)
            ptr = data
        else:
            data_length = 0
            ptr = NULL

        tmp = pool_pop(&__GenCxlMemS2MNDRPacket_pool)
        if tmp == NULL:
            pkt = cls()
        else:
            pkt = <_GenCxlMemS2MNDRPacket> tmp

        pkt._relocate()
        pkt._build(
            system_header__payload_type,
            cxl_mem_header__msg_class,
            s2mndr_header__valid,
            s2mndr_header__opcode,
            s2mndr_header__meta_field,
            s2mndr_header__meta_value,
            s2mndr_header__ld_id, 
            ptr,
            data_length,
        )
        return pkt

    def assign(
        self,
        system_header__payload_type,
        cxl_mem_header__msg_class,
        s2mndr_header__valid,
        s2mndr_header__opcode,
        s2mndr_header__meta_field,
        s2mndr_header__meta_value,
        s2mndr_header__ld_id,
        data: bytes | None = None,
    ):
        cdef Py_ssize_t data_length
        cdef const unsigned char* ptr

        if data:
            data_length = len(data)
            ptr = data
        else:
            data_length = 0
            ptr = NULL

        self._relocate()
        self._build(
            system_header__payload_type,
            cxl_mem_header__msg_class,
            s2mndr_header__valid,
            s2mndr_header__opcode,
            s2mndr_header__meta_field,
            s2mndr_header__meta_value,
            s2mndr_header__ld_id, 
            ptr,
            data_length,
        )

    cpdef set_data(self, data):
        src = <const unsigned char*> data
        dst = &self._buf[9]
        n = len(data)
        if 9 + n > MAX_PACKET_SIZE:
            raise ValueError("packet too large")
        memcpy(dst, src, n)
        self._data_length = n

    cpdef get_data(self):
        return PyBytes_FromStringAndSize(<char*>&self._buf[9], self._data_length)

    cpdef int get_payload_offset(self):
       return 9

    cpdef int get_byte_offset(self, object other):
        cdef uint8_t* base_ptr  = &self._buf[0]
        cdef uint8_t* other_ptr = NULL
        if isinstance(other, SystemHeader):
            other_ptr = (<SystemHeader> other)._p
        elif isinstance(other, CxlMemHeader):
            other_ptr = (<CxlMemHeader> other)._p
        elif isinstance(other, CxlMemS2MNDRHeader):
            other_ptr = (<CxlMemS2MNDRHeader> other)._p
        else:
            raise TypeError(f"unsupported header type: {type(other)}")
        return <int>(other_ptr - base_ptr)

    cpdef void set_bytes(self, int offset, object data):
        cdef const unsigned char[::1] view = data
        cdef int i
        for i in range(view.shape[0]):
            self._buf[offset + i] = view[i]

    cpdef void write_bits(self, int start_bit, int width, unsigned long long value):
        _write_bits(&self._buf[0], start_bit, width, value)

    cpdef unsigned long long read_bits(self, int start_bit, int width):
        return _read_bits(&self._buf[0], start_bit, width)

    cpdef get_bytes(self, int start, int length):
        return PyBytes_FromStringAndSize(<char*>&self._buf[start], length)

    #──────────────────── Header accessors ────────────────────
    @property
    def system_header(self):
        return self._system_header

    @property
    def cxl_mem_header(self):
        return self._cxl_mem_header

    @property
    def s2mndr_header(self):
        return self._s2mndr_header

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._release()

    def __del__(self):
        self._release()

    def __len__(self):
        return 9 + self._data_length

    def __bytes__(self):
        return PyBytes_FromStringAndSize(<char *> self._buf, 9 + self._data_length)

cdef PoolStruct __GenCxlMemS2MDRSPacket_pool

cdef class _GenCxlMemS2MDRSPacket:
    # class member vars
    cdef SystemHeader _system_header
    cdef CxlMemHeader _cxl_mem_header
    cdef CxlMemS2MDRSHeader _s2mdrs_header
    cdef unsigned char _buf[MAX_PACKET_SIZE]
    cdef int _data_length

    #────────────────── Life-cycle management ──────────────────
    cdef void _release(self):
        pool_push(&__GenCxlMemS2MDRSPacket_pool, <PyObject*> self)

    cdef inline void _relocate(self) noexcept nogil:
        cdef unsigned char* base = &self._buf[0]
        self._system_header.attach(base + 0)
        self._cxl_mem_header.attach(base + 2)
        self._s2mdrs_header.attach(base + 4)

    #─────────────────────── Builder ───────────────────────
    def __cinit__(self, payload=None):
        if not hasattr(self, '_data_length'):
            # first time only: allocate sub-headers
            self._data_length = 0
            self._system_header = SystemHeader()
            self._cxl_mem_header = CxlMemHeader()
            self._s2mdrs_header = CxlMemS2MDRSHeader()
            self._relocate()
            Py_INCREF(self)

        if payload is not None:
            src = <const unsigned char*> payload
            dst = &self._buf[0]
            n = len(payload)
            if n > MAX_PACKET_SIZE:
                raise ValueError("packet too large")
            memcpy(dst, src, n)
            self._data_length = n - 9

    cdef inline void _build(
        self,
        int system_header__payload_type,
        int cxl_mem_header__msg_class,
        int s2mdrs_header__valid,
        int s2mdrs_header__opcode,
        int s2mdrs_header__meta_field,
        int s2mdrs_header__meta_value,
        int s2mdrs_header__ld_id,
        const unsigned char* data_src,
        Py_ssize_t data_length
    ) noexcept nogil:
        cdef unsigned char* dst

        memset(&self._buf[0], 0, MAX_PACKET_SIZE)
        self._system_header._set_payload_type(system_header__payload_type)
        self._cxl_mem_header._set_msg_class(cxl_mem_header__msg_class)
        self._s2mdrs_header._set_valid(s2mdrs_header__valid)
        self._s2mdrs_header._set_opcode(s2mdrs_header__opcode)
        self._s2mdrs_header._set_meta_field(s2mdrs_header__meta_field)
        self._s2mdrs_header._set_meta_value(s2mdrs_header__meta_value)
        self._s2mdrs_header._set_ld_id(s2mdrs_header__ld_id)
        if data_src:
            dst = &self._buf[9]
            if data_length > MAX_PACKET_SIZE - 9:
                raise ValueError("data too large")
            memcpy(dst, data_src, data_length)
            self._data_length = data_length
        self._system_header._set_payload_length(9 + data_length)

    #────────────────── Python Interface ──────────────────
    @classmethod
    def create(
        cls,
        system_header__payload_type,
        cxl_mem_header__msg_class,
        s2mdrs_header__valid,
        s2mdrs_header__opcode,
        s2mdrs_header__meta_field,
        s2mdrs_header__meta_value,
        s2mdrs_header__ld_id,
        data: bytes | None = None,
    ):
        cdef PyObject *tmp
        cdef _GenCxlMemS2MDRSPacket pkt
        cdef Py_ssize_t data_length
        cdef const unsigned char* ptr

        if data:
            data_length = len(data)
            ptr = data
        else:
            data_length = 0
            ptr = NULL

        tmp = pool_pop(&__GenCxlMemS2MDRSPacket_pool)
        if tmp == NULL:
            pkt = cls()
        else:
            pkt = <_GenCxlMemS2MDRSPacket> tmp

        pkt._relocate()
        pkt._build(
            system_header__payload_type,
            cxl_mem_header__msg_class,
            s2mdrs_header__valid,
            s2mdrs_header__opcode,
            s2mdrs_header__meta_field,
            s2mdrs_header__meta_value,
            s2mdrs_header__ld_id, 
            ptr,
            data_length,
        )
        return pkt

    def assign(
        self,
        system_header__payload_type,
        cxl_mem_header__msg_class,
        s2mdrs_header__valid,
        s2mdrs_header__opcode,
        s2mdrs_header__meta_field,
        s2mdrs_header__meta_value,
        s2mdrs_header__ld_id,
        data: bytes | None = None,
    ):
        cdef Py_ssize_t data_length
        cdef const unsigned char* ptr

        if data:
            data_length = len(data)
            ptr = data
        else:
            data_length = 0
            ptr = NULL

        self._relocate()
        self._build(
            system_header__payload_type,
            cxl_mem_header__msg_class,
            s2mdrs_header__valid,
            s2mdrs_header__opcode,
            s2mdrs_header__meta_field,
            s2mdrs_header__meta_value,
            s2mdrs_header__ld_id, 
            ptr,
            data_length,
        )

    cpdef set_data(self, data):
        src = <const unsigned char*> data
        dst = &self._buf[9]
        n = len(data)
        if 9 + n > MAX_PACKET_SIZE:
            raise ValueError("packet too large")
        memcpy(dst, src, n)
        self._data_length = n

    cpdef get_data(self):
        return PyBytes_FromStringAndSize(<char*>&self._buf[9], self._data_length)

    cpdef int get_payload_offset(self):
       return 9

    cpdef int get_byte_offset(self, object other):
        cdef uint8_t* base_ptr  = &self._buf[0]
        cdef uint8_t* other_ptr = NULL
        if isinstance(other, SystemHeader):
            other_ptr = (<SystemHeader> other)._p
        elif isinstance(other, CxlMemHeader):
            other_ptr = (<CxlMemHeader> other)._p
        elif isinstance(other, CxlMemS2MDRSHeader):
            other_ptr = (<CxlMemS2MDRSHeader> other)._p
        else:
            raise TypeError(f"unsupported header type: {type(other)}")
        return <int>(other_ptr - base_ptr)

    cpdef void set_bytes(self, int offset, object data):
        cdef const unsigned char[::1] view = data
        cdef int i
        for i in range(view.shape[0]):
            self._buf[offset + i] = view[i]

    cpdef void write_bits(self, int start_bit, int width, unsigned long long value):
        _write_bits(&self._buf[0], start_bit, width, value)

    cpdef unsigned long long read_bits(self, int start_bit, int width):
        return _read_bits(&self._buf[0], start_bit, width)

    cpdef get_bytes(self, int start, int length):
        return PyBytes_FromStringAndSize(<char*>&self._buf[start], length)

    #──────────────────── Header accessors ────────────────────
    @property
    def system_header(self):
        return self._system_header

    @property
    def cxl_mem_header(self):
        return self._cxl_mem_header

    @property
    def s2mdrs_header(self):
        return self._s2mdrs_header

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._release()

    def __del__(self):
        self._release()

    def __len__(self):
        return 9 + self._data_length

    def __bytes__(self):
        return PyBytes_FromStringAndSize(<char *> self._buf, 9 + self._data_length)

cdef PoolStruct __GenCciBasePacket_pool

cdef class _GenCciBasePacket:
    # class member vars
    cdef SystemHeader _system_header
    cdef CciHeader _cci_header
    cdef unsigned char _buf[MAX_PACKET_SIZE]
    cdef int _data_length

    #────────────────── Life-cycle management ──────────────────
    cdef void _release(self):
        pool_push(&__GenCciBasePacket_pool, <PyObject*> self)

    cdef inline void _relocate(self) noexcept nogil:
        cdef unsigned char* base = &self._buf[0]
        self._system_header.attach(base + 0)
        self._cci_header.attach(base + 2)

    #─────────────────────── Builder ───────────────────────
    def __cinit__(self, payload=None):
        if not hasattr(self, '_data_length'):
            # first time only: allocate sub-headers
            self._data_length = 0
            self._system_header = SystemHeader()
            self._cci_header = CciHeader()
            self._relocate()
            Py_INCREF(self)

        if payload is not None:
            src = <const unsigned char*> payload
            dst = &self._buf[0]
            n = len(payload)
            if n > MAX_PACKET_SIZE:
                raise ValueError("packet too large")
            memcpy(dst, src, n)
            self._data_length = n - 4

    #────────────────── Python Interface ──────────────────
    cpdef set_data(self, data):
        src = <const unsigned char*> data
        dst = &self._buf[4]
        n = len(data)
        if 4 + n > MAX_PACKET_SIZE:
            raise ValueError("packet too large")
        memcpy(dst, src, n)
        self._data_length = n

    cpdef get_data(self):
        return PyBytes_FromStringAndSize(<char*>&self._buf[4], self._data_length)

    cpdef int get_payload_offset(self):
       return 4

    cpdef int get_byte_offset(self, object other):
        cdef uint8_t* base_ptr  = &self._buf[0]
        cdef uint8_t* other_ptr = NULL
        if isinstance(other, SystemHeader):
            other_ptr = (<SystemHeader> other)._p
        elif isinstance(other, CciHeader):
            other_ptr = (<CciHeader> other)._p
        else:
            raise TypeError(f"unsupported header type: {type(other)}")
        return <int>(other_ptr - base_ptr)

    cpdef void set_bytes(self, int offset, object data):
        cdef const unsigned char[::1] view = data
        cdef int i
        for i in range(view.shape[0]):
            self._buf[offset + i] = view[i]

    cpdef void write_bits(self, int start_bit, int width, unsigned long long value):
        _write_bits(&self._buf[0], start_bit, width, value)

    cpdef unsigned long long read_bits(self, int start_bit, int width):
        return _read_bits(&self._buf[0], start_bit, width)

    cpdef get_bytes(self, int start, int length):
        return PyBytes_FromStringAndSize(<char*>&self._buf[start], length)

    #──────────────────── Header accessors ────────────────────
    @property
    def system_header(self):
        return self._system_header

    @property
    def cci_header(self):
        return self._cci_header

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._release()

    def __del__(self):
        self._release()

    def __len__(self):
        return 4 + self._data_length

    def __bytes__(self):
        return PyBytes_FromStringAndSize(<char *> self._buf, 4 + self._data_length)

cdef PoolStruct __GenCciMessagePacket_pool

cdef class _GenCciMessagePacket:
    # class member vars
    cdef CciMessageHeader _cci_msg_header
    cdef unsigned char _buf[MAX_PACKET_SIZE]
    cdef int _data_length

    #────────────────── Life-cycle management ──────────────────
    cdef void _release(self):
        pool_push(&__GenCciMessagePacket_pool, <PyObject*> self)

    cdef inline void _relocate(self) noexcept nogil:
        cdef unsigned char* base = &self._buf[0]
        self._cci_msg_header.attach(base + 0)

    #─────────────────────── Builder ───────────────────────
    def __cinit__(self, payload=None):
        if not hasattr(self, '_data_length'):
            # first time only: allocate sub-headers
            self._data_length = 0
            self._cci_msg_header = CciMessageHeader()
            self._relocate()
            Py_INCREF(self)

        if payload is not None:
            src = <const unsigned char*> payload
            dst = &self._buf[0]
            n = len(payload)
            if n > MAX_PACKET_SIZE:
                raise ValueError("packet too large")
            memcpy(dst, src, n)
            self._data_length = n - 12

    #────────────────── Python Interface ──────────────────
    cpdef set_data(self, data):
        src = <const unsigned char*> data
        dst = &self._buf[12]
        n = len(data)
        if 12 + n > MAX_PACKET_SIZE:
            raise ValueError("packet too large")
        memcpy(dst, src, n)
        self._data_length = n

    cpdef get_data(self):
        return PyBytes_FromStringAndSize(<char*>&self._buf[12], self._data_length)

    cpdef int get_payload_offset(self):
       return 12

    cpdef int get_byte_offset(self, object other):
        cdef uint8_t* base_ptr  = &self._buf[0]
        cdef uint8_t* other_ptr = NULL
        if isinstance(other, CciMessageHeader):
            other_ptr = (<CciMessageHeader> other)._p
        else:
            raise TypeError(f"unsupported header type: {type(other)}")
        return <int>(other_ptr - base_ptr)

    cpdef void set_bytes(self, int offset, object data):
        cdef const unsigned char[::1] view = data
        cdef int i
        for i in range(view.shape[0]):
            self._buf[offset + i] = view[i]

    cpdef void write_bits(self, int start_bit, int width, unsigned long long value):
        _write_bits(&self._buf[0], start_bit, width, value)

    cpdef unsigned long long read_bits(self, int start_bit, int width):
        return _read_bits(&self._buf[0], start_bit, width)

    cpdef get_bytes(self, int start, int length):
        return PyBytes_FromStringAndSize(<char*>&self._buf[start], length)

    #──────────────────── Header accessors ────────────────────
    @property
    def cci_msg_header(self):
        return self._cci_msg_header

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._release()

    def __del__(self):
        self._release()

    def __len__(self):
        return 12 + self._data_length

    def __bytes__(self):
        return PyBytes_FromStringAndSize(<char *> self._buf, 12 + self._data_length)

cdef PoolStruct __GenCciPayloadPacket_pool

cdef class _GenCciPayloadPacket:
    # class member vars
    cdef SystemHeader _system_header
    cdef CciHeader _cci_header
    cdef unsigned char _buf[MAX_PACKET_SIZE]
    cdef int _data_length

    #────────────────── Life-cycle management ──────────────────
    cdef void _release(self):
        pool_push(&__GenCciPayloadPacket_pool, <PyObject*> self)

    cdef inline void _relocate(self) noexcept nogil:
        cdef unsigned char* base = &self._buf[0]
        self._system_header.attach(base + 0)
        self._cci_header.attach(base + 2)

    #─────────────────────── Builder ───────────────────────
    def __cinit__(self, payload=None):
        if not hasattr(self, '_data_length'):
            # first time only: allocate sub-headers
            self._data_length = 0
            self._system_header = SystemHeader()
            self._cci_header = CciHeader()
            self._relocate()
            Py_INCREF(self)

        if payload is not None:
            src = <const unsigned char*> payload
            dst = &self._buf[0]
            n = len(payload)
            if n > MAX_PACKET_SIZE:
                raise ValueError("packet too large")
            memcpy(dst, src, n)
            self._data_length = n - 4

    #────────────────── Python Interface ──────────────────
    cpdef set_data(self, data):
        src = <const unsigned char*> data
        dst = &self._buf[4]
        n = len(data)
        if 4 + n > MAX_PACKET_SIZE:
            raise ValueError("packet too large")
        memcpy(dst, src, n)
        self._data_length = n

    cpdef get_data(self):
        return PyBytes_FromStringAndSize(<char*>&self._buf[4], self._data_length)

    cpdef int get_payload_offset(self):
       return 4

    cpdef int get_byte_offset(self, object other):
        cdef uint8_t* base_ptr  = &self._buf[0]
        cdef uint8_t* other_ptr = NULL
        if isinstance(other, SystemHeader):
            other_ptr = (<SystemHeader> other)._p
        elif isinstance(other, CciHeader):
            other_ptr = (<CciHeader> other)._p
        else:
            raise TypeError(f"unsupported header type: {type(other)}")
        return <int>(other_ptr - base_ptr)

    cpdef void set_bytes(self, int offset, object data):
        cdef const unsigned char[::1] view = data
        cdef int i
        for i in range(view.shape[0]):
            self._buf[offset + i] = view[i]

    cpdef void write_bits(self, int start_bit, int width, unsigned long long value):
        _write_bits(&self._buf[0], start_bit, width, value)

    cpdef unsigned long long read_bits(self, int start_bit, int width):
        return _read_bits(&self._buf[0], start_bit, width)

    cpdef get_bytes(self, int start, int length):
        return PyBytes_FromStringAndSize(<char*>&self._buf[start], length)

    #──────────────────── Header accessors ────────────────────
    @property
    def system_header(self):
        return self._system_header

    @property
    def cci_header(self):
        return self._cci_header

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._release()

    def __del__(self):
        self._release()

    def __len__(self):
        return 4 + self._data_length

    def __bytes__(self):
        return PyBytes_FromStringAndSize(<char *> self._buf, 4 + self._data_length)

cdef PoolStruct __GenCciRequestPacket_pool

cdef class _GenCciRequestPacket:
    # class member vars
    cdef SystemHeader _system_header
    cdef CciHeader _cci_header
    cdef CciMessageHeader _cci_msg_header
    cdef unsigned char _buf[MAX_PACKET_SIZE]
    cdef int _data_length

    #────────────────── Life-cycle management ──────────────────
    cdef void _release(self):
        pool_push(&__GenCciRequestPacket_pool, <PyObject*> self)

    cdef inline void _relocate(self) noexcept nogil:
        cdef unsigned char* base = &self._buf[0]
        self._system_header.attach(base + 0)
        self._cci_header.attach(base + 2)
        self._cci_msg_header.attach(base + 4)

    #─────────────────────── Builder ───────────────────────
    def __cinit__(self, payload=None):
        if not hasattr(self, '_data_length'):
            # first time only: allocate sub-headers
            self._data_length = 0
            self._system_header = SystemHeader()
            self._cci_header = CciHeader()
            self._cci_msg_header = CciMessageHeader()
            self._relocate()
            Py_INCREF(self)

        if payload is not None:
            src = <const unsigned char*> payload
            dst = &self._buf[0]
            n = len(payload)
            if n > MAX_PACKET_SIZE:
                raise ValueError("packet too large")
            memcpy(dst, src, n)
            self._data_length = n - 16

    #────────────────── Python Interface ──────────────────
    cpdef set_data(self, data):
        src = <const unsigned char*> data
        dst = &self._buf[16]
        n = len(data)
        if 16 + n > MAX_PACKET_SIZE:
            raise ValueError("packet too large")
        memcpy(dst, src, n)
        self._data_length = n

    cpdef get_data(self):
        return PyBytes_FromStringAndSize(<char*>&self._buf[16], self._data_length)

    cpdef int get_payload_offset(self):
       return 16

    cpdef int get_byte_offset(self, object other):
        cdef uint8_t* base_ptr  = &self._buf[0]
        cdef uint8_t* other_ptr = NULL
        if isinstance(other, SystemHeader):
            other_ptr = (<SystemHeader> other)._p
        elif isinstance(other, CciHeader):
            other_ptr = (<CciHeader> other)._p
        elif isinstance(other, CciMessageHeader):
            other_ptr = (<CciMessageHeader> other)._p
        else:
            raise TypeError(f"unsupported header type: {type(other)}")
        return <int>(other_ptr - base_ptr)

    cpdef void set_bytes(self, int offset, object data):
        cdef const unsigned char[::1] view = data
        cdef int i
        for i in range(view.shape[0]):
            self._buf[offset + i] = view[i]

    cpdef void write_bits(self, int start_bit, int width, unsigned long long value):
        _write_bits(&self._buf[0], start_bit, width, value)

    cpdef unsigned long long read_bits(self, int start_bit, int width):
        return _read_bits(&self._buf[0], start_bit, width)

    cpdef get_bytes(self, int start, int length):
        return PyBytes_FromStringAndSize(<char*>&self._buf[start], length)

    #──────────────────── Header accessors ────────────────────
    @property
    def system_header(self):
        return self._system_header

    @property
    def cci_header(self):
        return self._cci_header

    @property
    def cci_msg_header(self):
        return self._cci_msg_header

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._release()

    def __del__(self):
        self._release()

    def __len__(self):
        return 16 + self._data_length

    def __bytes__(self):
        return PyBytes_FromStringAndSize(<char *> self._buf, 16 + self._data_length)

cdef PoolStruct __GenCciResponsePacket_pool

cdef class _GenCciResponsePacket:
    # class member vars
    cdef SystemHeader _system_header
    cdef CciHeader _cci_header
    cdef CciMessageHeader _cci_msg_header
    cdef unsigned char _buf[MAX_PACKET_SIZE]
    cdef int _data_length

    #────────────────── Life-cycle management ──────────────────
    cdef void _release(self):
        pool_push(&__GenCciResponsePacket_pool, <PyObject*> self)

    cdef inline void _relocate(self) noexcept nogil:
        cdef unsigned char* base = &self._buf[0]
        self._system_header.attach(base + 0)
        self._cci_header.attach(base + 2)
        self._cci_msg_header.attach(base + 4)

    #─────────────────────── Builder ───────────────────────
    def __cinit__(self, payload=None):
        if not hasattr(self, '_data_length'):
            # first time only: allocate sub-headers
            self._data_length = 0
            self._system_header = SystemHeader()
            self._cci_header = CciHeader()
            self._cci_msg_header = CciMessageHeader()
            self._relocate()
            Py_INCREF(self)

        if payload is not None:
            src = <const unsigned char*> payload
            dst = &self._buf[0]
            n = len(payload)
            if n > MAX_PACKET_SIZE:
                raise ValueError("packet too large")
            memcpy(dst, src, n)
            self._data_length = n - 16

    #────────────────── Python Interface ──────────────────
    cpdef set_data(self, data):
        src = <const unsigned char*> data
        dst = &self._buf[16]
        n = len(data)
        if 16 + n > MAX_PACKET_SIZE:
            raise ValueError("packet too large")
        memcpy(dst, src, n)
        self._data_length = n

    cpdef get_data(self):
        return PyBytes_FromStringAndSize(<char*>&self._buf[16], self._data_length)

    cpdef int get_payload_offset(self):
       return 16

    cpdef int get_byte_offset(self, object other):
        cdef uint8_t* base_ptr  = &self._buf[0]
        cdef uint8_t* other_ptr = NULL
        if isinstance(other, SystemHeader):
            other_ptr = (<SystemHeader> other)._p
        elif isinstance(other, CciHeader):
            other_ptr = (<CciHeader> other)._p
        elif isinstance(other, CciMessageHeader):
            other_ptr = (<CciMessageHeader> other)._p
        else:
            raise TypeError(f"unsupported header type: {type(other)}")
        return <int>(other_ptr - base_ptr)

    cpdef void set_bytes(self, int offset, object data):
        cdef const unsigned char[::1] view = data
        cdef int i
        for i in range(view.shape[0]):
            self._buf[offset + i] = view[i]

    cpdef void write_bits(self, int start_bit, int width, unsigned long long value):
        _write_bits(&self._buf[0], start_bit, width, value)

    cpdef unsigned long long read_bits(self, int start_bit, int width):
        return _read_bits(&self._buf[0], start_bit, width)

    cpdef get_bytes(self, int start, int length):
        return PyBytes_FromStringAndSize(<char*>&self._buf[start], length)

    #──────────────────── Header accessors ────────────────────
    @property
    def system_header(self):
        return self._system_header

    @property
    def cci_header(self):
        return self._cci_header

    @property
    def cci_msg_header(self):
        return self._cci_msg_header

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._release()

    def __del__(self):
        self._release()

    def __len__(self):
        return 16 + self._data_length

    def __bytes__(self):
        return PyBytes_FromStringAndSize(<char *> self._buf, 16 + self._data_length)

