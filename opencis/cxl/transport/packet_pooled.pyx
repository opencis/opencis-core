# cython: language_level=3, boundscheck=False, wraparound=False, no_gc=True, infer_types=True
from libc.stdint cimport uint8_t, uint16_t, uint32_t, uint64_t
from libc.string  cimport memcpy
from cpython.bytes cimport PyBytes_FromStringAndSize
from libc.stdint cimport uintptr_t, uint8_t, uint16_t, uint32_t, uint64_t
from cpython.ref cimport Py_INCREF, Py_DECREF
from cpython.object cimport PyObject

ctypedef enum:
    MAX_PACKET_SIZE = 200
    POOL_SIZE = 4
    SYSTEM_PAYLOAD_TYPE_CXL_MEM = 7
    CXL_MEM_MSG_CLASS_M2S_REQ = 2
    CXL_MEM_M2SREQ_OPCODE_MEM_RD = 1


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


# ────────────────────────────────────────────────────────────────────────────
#  1.  SystemHeader  (2 bytes)
# ────────────────────────────────────────────────────────────────────────────
cdef class SystemHeader:
    __slots__ = ()
    cdef uint8_t* _p

    def __cinit__(self):
        self._p = <uint8_t*>0         # NULL until first attach()

    cdef void attach(self, uint8_t* p) noexcept nogil:
        self._p = p                   # 0-cost pointer swap

    # ───── payload_type : bits 0-3 ──────────────────────────────────────────
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
        return ((self._p[0] >> 4) & 0x0F) | (self._p[1] << 4)

    cdef inline void _set_payload_length(self, uint16_t v) noexcept nogil:
        self._p[0] = (self._p[0] & 0x0F) | ((v & 0x000F) << 4)
        self._p[1] = (v >> 4) & 0xFF

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


# ────────────────────────────────────────────────────────────────────────────
#  2.  CxlMemHeader  (2 bytes)
# ────────────────────────────────────────────────────────────────────────────

cdef class CxlMemHeader:
    __slots__ = ()
    cdef uint8_t* _p

    def __cinit__(self):
        self._p = <uint8_t*>0

    cdef void attach(self, uint8_t* p) noexcept nogil:
        self._p = p

    # port_index : bits 0-7
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

    # msg_class : bits 8-15
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

    @classmethod
    def get_size(cls):
        return 2

    def __len__(self):
        return 2

    def __bytes__(self):
        return PyBytes_FromStringAndSize(<char*>self._p, 2)


# ---------------------------------------------------------------------------
#  CxlMemM2SReqHeader – with SystemHeader-style accessors
# ---------------------------------------------------------------------------

cdef class CxlMemM2SReqHeader:
    __slots__ = ()
    cdef uint8_t* _p

    def __cinit__(self):
        self._p = <uint8_t*>0

    cdef void attach(self, uint8_t* p) noexcept nogil:
        self._p = p

    # ───── valid : bit 0 ───────────────────────────────────────────────────
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

    # ───── mem_opcode : bits 1–4 ───────────────────────────────────────────
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

    # ───── snp_type : bits 5–7 ─────────────────────────────────────────────
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

    # ───── meta_field : bits 8–9 ───────────────────────────────────────────
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

    # ───── meta_value : bits 10–11 ─────────────────────────────────────────
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

    # ───── tag : bits 12–27 (16 b) ─────────────────────────────────────────
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

    # ───── addr : bits 28–73 (46 b) ────────────────────────────────────────
    cdef inline uint64_t _get_addr(self) noexcept nogil:
        return _read_bits(self._p, 28, 46)

    cdef inline void _set_addr(self, uint64_t v) noexcept nogil:
        _write_bits(self._p, 28, 46, v)

    @property
    def addr(self):
        return self._get_addr()

    @addr.setter
    def addr(self, v):
        self._set_addr(<uint64_t>v)

    # ───── ld_id : bits 74–77 (4 b) ────────────────────────────────────────
    cdef inline uint8_t _get_ld_id(self) noexcept nogil:
        return <uint8_t>_read_bits(self._p, 74, 4)

    cdef inline void _set_ld_id(self, uint8_t v) noexcept nogil:
        _write_bits(self._p, 74, 4, v)

    @property
    def ld_id(self):
        return self._get_ld_id()

    @ld_id.setter
    def ld_id(self, v):
        self._set_ld_id(<uint8_t>v)

    # ───── rsvd : bits 78–97 (20 b) ────────────────────────────────────────
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

    # ───── tc : bits 98–99 (2 b) ───────────────────────────────────────────
    cdef inline uint8_t _get_tc(self) noexcept nogil:
        return <uint8_t>_read_bits(self._p, 98, 2)

    cdef inline void _set_tc(self, uint8_t v) noexcept nogil:
        _write_bits(self._p, 98, 2, v)

    @property
    def tc(self):
        return self._get_tc()

    @tc.setter
    def tc(self, v):
        self._set_tc(<uint8_t>v)

    # ───── padding : bits 100–103 (4 b) ────────────────────────────────────
    cdef inline uint8_t _get_padding(self) noexcept nogil:
        return <uint8_t>_read_bits(self._p, 100, 4)

    cdef inline void _set_padding(self, uint8_t v) noexcept nogil:
        _write_bits(self._p, 100, 4, v)

    @property
    def padding(self):
        return self._get_padding()

    @padding.setter
    def padding(self, v):
        self._set_padding(<uint8_t>v)

    # ------------------------------------------------------------------ misc
    @classmethod
    def get_size(cls):
        return 13

    def __len__(self):
        return 13

    def __bytes__(self):
        return PyBytes_FromStringAndSize(<char*>self._p, 13)




# ─── Module‐level struct & API ──────────────────────────────────────

cdef struct PoolStruct:
    PyObject *buf[POOL_SIZE]
    Py_ssize_t head
    Py_ssize_t tail
    Py_ssize_t count

cdef inline void pool_push(PoolStruct *p, PyObject *obj) noexcept nogil:
    # Only reacquire the GIL for the refcount ops:
    if p.count == POOL_SIZE:
        with gil:
            Py_DECREF(<object>obj)
        return

    with gil:
        Py_INCREF(<object>obj)

    # Pure C pointer math—no GIL needed
    p.buf[p.tail] = obj
    p.tail    = (p.tail + 1) & (POOL_SIZE - 1)
    p.count  += 1


cdef inline PyObject* pool_pop(PoolStruct *p) noexcept nogil:
    if p.count == 0:
        return NULL

    # Pure C
    cdef PyObject *obj = p.buf[p.head]
    p.buf[p.head]     = NULL
    p.head            = (p.head + 1) & (POOL_SIZE - 1)
    p.count          -= 1

    return obj  # caller owns the reference held by the pool



# CxlMemM2SRwDPacket Definition

cdef PoolStruct _CxlMemM2SRwDPacket_pool

cdef class _GenCxlMemM2SRwDPacket:
    __slots__ = ()
    # Buffer
    cdef unsigned char _ba[MAX_PACKET_SIZE]
    cdef Py_ssize_t    _data_length

    # Headers
    cdef SystemHeader       _system_header
    cdef CxlMemHeader       _cxl_mem_header
    cdef CxlMemM2SReqHeader _m2sreq_header

    # ------------------------------------------------------------------  life-cycle management
    cdef void _release(self):
        pool_push(&_CxlMemM2SRwDPacket_pool, <PyObject*> self)

    cdef inline void _relocate(self) noexcept nogil:
        cdef unsigned char* base = &self._ba[0]
        self._system_header.attach(base + 0)   # bytes 0-1
        self._cxl_mem_header.attach(base + 2)  # bytes 2-3
        self._m2sreq_header.attach(base + 6)   # bytes 6-18

    # ------------------------------------------------------------------
    def __cinit__(self, payload=None):
        cdef const unsigned char* src 
        cdef unsigned char* dst
        cdef Py_ssize_t n

        if not hasattr(self, "_data_length"):
            # First-time only: init headers
            self._data_length = 0
            self._system_header  = SystemHeader()
            self._cxl_mem_header = CxlMemHeader()
            self._m2sreq_header  = CxlMemM2SReqHeader()
            self._relocate()

        if payload is not None:
            src = <const unsigned char*> payload
            dst = &self._ba[0]
            n = len(payload)
            if n > MAX_PACKET_SIZE:
                raise ValueError("packet too large")
            memcpy(dst, src, n)
            self._data_length = n - 18

    # ------------------------------------------------------------------ builder (send path)
    @classmethod
    def create(cls,
               addr: int,
               opcode: int,
               meta_field: int,
               meta_value: int,
               snp_type: int,
               ld_id: int,
               data: bytes
    ):
        cdef PyObject *tmp
        cdef _GenCxlMemM2SRwDPacket pkt
        cdef Py_ssize_t n = len(data)
        cdef const unsigned char* raw = data

        tmp = pool_pop(&_CxlMemM2SRwDPacket_pool)
        if tmp == NULL:
            pkt = cls()
        else:
            pkt = <_GenCxlMemM2SRwDPacket> tmp

        pkt._relocate()
        pkt._build(addr, opcode, meta_field, meta_value, snp_type, ld_id, raw, n)

        return pkt

    def assign(self,
               addr: int,
               opcode: int,
               meta_field: int,
               meta_value: int,
               snp_type: int,
               ld_id: int,
               data: bytes
    ):
        cdef const unsigned char* raw = data
        cdef Py_ssize_t n = len(data)

        self._relocate()
        self._build(addr, opcode, meta_field, meta_value, snp_type, ld_id, raw, n)

    cdef inline void _build(self,
                     int addr,
                     int opcode,
                     int meta_field,
                     int meta_value,
                     int snp_type,
                     int ld_id,
                     const unsigned char* src,
                     Py_ssize_t n,
    ) noexcept nogil:
        cdef unsigned char* dst = &self._ba[18]

        self._system_header._set_payload_type(3)
        self._system_header._set_payload_length(18 + n)
        self._cxl_mem_header._set_msg_class(6)
        self._m2sreq_header._set_valid(1)
        self._m2sreq_header._set_mem_opcode(opcode)
        self._m2sreq_header._set_meta_field(meta_field)
        self._m2sreq_header._set_meta_value(meta_value)
        self._m2sreq_header._set_snp_type(snp_type)
        self._m2sreq_header._set_ld_id(ld_id)
        self._m2sreq_header._set_addr(addr >> 6)

        if 18 + n > MAX_PACKET_SIZE:
            raise ValueError("data too large")
        memcpy(dst, src, n)
        self._data_length = n

    # ------------------------------------------------------------------ mutators / accessors
    @property
    def to_bytes(self):
        return PyBytes_FromStringAndSize(<char *> self._ba, 18 + self._data_length)

    @property
    def system_header(self):
        return self._system_header

    @property
    def cxl_mem_header(self):
        return self._cxl_mem_header

    @property
    def m2sreq_header(self):
        return self._m2sreq_header

    # ------------------------------------------------------------------ python specials
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._release()

    def __del__(self):
        self._release()

    def __len__(self):
        return 18 + self._data_length

    def __bytes__(self):
        return PyBytes_FromStringAndSize(<char *> self._ba, 18 + self._data_length)


def demo():
    data = b'\x02' * 64
    pkt1 = _GenCxlMemM2SRwDPacket.create(
        0x1000,
        5,
        100,
        200,
        222,
        5,
        bytes(data)
    )
    raw  = bytes(pkt1)
    pkt2 = _GenCxlMemM2SRwDPacket(raw)
    assert bytes(pkt2) == raw
    print("Round-trip OK")