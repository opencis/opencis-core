# cython: language_level=3, boundscheck=False, wraparound=False, no_gc=True
from libc.stdint cimport uint8_t, uint16_t, uint32_t, uint64_t
from cpython.bytes cimport PyBytes_FromStringAndSize
cimport cython
from collections import deque
from libc.string  cimport memcpy
from packet_constants import *
from libc.stdint cimport uintptr_t, uint8_t, uint16_t, uint32_t, uint64_t
from cpython.ref cimport Py_INCREF
cimport cython
from cpython.bytearray cimport PyByteArray_FromStringAndSize
from cython cimport view     # brings in view.array


ctypedef enum:
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
    __slots__ = ("_p",)               # uint8_t* into the packet buffer
    cdef uint8_t* _p

    def __cinit__(self):
        self._p = <uint8_t*>0         # NULL until first attach()

    cdef void attach(self, uint8_t* p) nogil:
        self._p = p                   # 0-cost pointer swap

    # ───── payload_type : bits 0-3 ──────────────────────────────────────────
    cdef inline uint8_t _get_payload_type(self) nogil:
        return self._p[0] & 0x0F

    cdef inline void _set_payload_type(self, uint8_t v) nogil:
        self._p[0] = (self._p[0] & 0xF0) | (v & 0x0F)

    @property
    def payload_type(self):
        return self._get_payload_type()

    @payload_type.setter
    def payload_type(self, v):
        self._set_payload_type(<uint8_t>v)

    # ───── payload_length : bits 4-15 (12 b) ───────────────────────────────
    cdef inline uint16_t _get_payload_len(self) nogil:
        return ((self._p[0] >> 4) & 0x0F) | (self._p[1] << 4)

    cdef inline void _set_payload_len(self, uint16_t v) nogil:
        self._p[0] = (self._p[0] & 0x0F) | ((v & 0x000F) << 4)
        self._p[1] = (v >> 4) & 0xFF

    @property
    def payload_length(self):
        return self._get_payload_len()

    @payload_length.setter
    def payload_length(self, v):
        self._set_payload_len(<uint16_t>v)

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
    __slots__ = ("_p",)
    cdef uint8_t* _p

    def __cinit__(self):
        self._p = <uint8_t*>0

    cdef void attach(self, uint8_t* p) nogil:
        self._p = p

    # port_index : bits 0-7
    cdef inline uint8_t _get_port_index(self) nogil:
        return self._p[0]

    cdef inline void _set_port_index(self, uint8_t v) nogil:
        self._p[0] = v

    @property
    def port_index(self):
        return self._get_port_index()

    @port_index.setter
    def port_index(self, v):
        self._set_port_index(<uint8_t>v)

    # msg_class : bits 8-15
    cdef inline uint8_t _get_msg_class(self) nogil:
        return self._p[1]

    cdef inline void _set_msg_class(self, uint8_t v) nogil:
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
#  CxlMemM2SReqHeader  –  zero-alloc view with Python-visible properties
# ---------------------------------------------------------------------------

cdef class CxlMemM2SReqHeader:
    __slots__ = ("_p",)
    cdef uint8_t* _p

    def __cinit__(self):
        self._p = <uint8_t*>0

    cdef void attach(self, uint8_t* p) nogil:
        self._p = p

    # ------------------------------------------------------------------ fast helpers
    cdef inline uint8_t  _get_valid_fast(self)      nogil: return self._p[0] & 0x01
    cdef inline void     _set_valid_fast(self, uint8_t v) nogil:
        self._p[0] = (self._p[0] & 0xFE) | (v & 0x01)

    cdef inline uint8_t  _get_mem_opcode_fast(self) nogil: return (self._p[0] >> 1) & 0x0F
    cdef inline void     _set_mem_opcode_fast(self, uint8_t v) nogil:
        self._p[0] = (self._p[0] & 0xE1) | ((v & 0x0F) << 1)

    cdef inline uint8_t  _get_snp_type_fast(self)   nogil: return (self._p[0] >> 5) & 0x07
    cdef inline void     _set_snp_type_fast(self, uint8_t v) nogil:
        self._p[0] = (self._p[0] & 0x1F) | ((v & 0x07) << 5)

    cdef inline uint8_t  _get_meta_field_fast(self) nogil: return self._p[1] & 0x03
    cdef inline void     _set_meta_field_fast(self, uint8_t v) nogil:
        self._p[1] = (self._p[1] & 0xFC) | (v & 0x03)

    cdef inline uint8_t  _get_meta_value_fast(self) nogil: return (self._p[1] >> 2) & 0x03
    cdef inline void     _set_meta_value_fast(self, uint8_t v) nogil:
        self._p[1] = (self._p[1] & 0xF3) | ((v & 0x03) << 2)

    cdef inline uint16_t _get_tag_fast(self)  nogil: return <uint16_t>_read_bits(self._p, 12, 16)
    cdef inline void     _set_tag_fast(self, uint16_t v)   nogil: _write_bits(self._p, 12, 16, v)

    cdef inline uint64_t _get_addr_fast(self) nogil: return _read_bits(self._p, 28, 46)
    cdef inline void     _set_addr_fast(self, uint64_t v)  nogil: _write_bits(self._p, 28, 46, v)

    cdef inline uint8_t  _get_ld_id_fast(self)  nogil: return <uint8_t>_read_bits(self._p, 74, 4)
    cdef inline void     _set_ld_id_fast(self, uint8_t v)  nogil: _write_bits(self._p, 74, 4, v)

    cdef inline uint32_t _get_rsvd_fast(self)   nogil: return <uint32_t>_read_bits(self._p, 78, 20)
    cdef inline void     _set_rsvd_fast(self, uint32_t v)  nogil: _write_bits(self._p, 78, 20, v)

    cdef inline uint8_t  _get_tc_fast(self)     nogil: return <uint8_t>_read_bits(self._p, 98, 2)
    cdef inline void     _set_tc_fast(self, uint8_t v)     nogil: _write_bits(self._p, 98, 2, v)

    cdef inline uint8_t  _get_padding_fast(self) nogil: return <uint8_t>_read_bits(self._p, 100, 4)
    cdef inline void     _set_padding_fast(self, uint8_t v) nogil: _write_bits(self._p, 100, 4, v)

    # ------------------------------------------------------------------ tiny Python wrappers
    def _get_valid(self):            return self._get_valid_fast()
    def _set_valid(self, v):         self._set_valid_fast(<uint8_t>v)

    def _get_mem_opcode(self):       return self._get_mem_opcode_fast()
    def _set_mem_opcode(self, v):    self._set_mem_opcode_fast(<uint8_t>v)

    def _get_snp_type(self):         return self._get_snp_type_fast()
    def _set_snp_type(self, v):      self._set_snp_type_fast(<uint8_t>v)

    def _get_meta_field(self):       return self._get_meta_field_fast()
    def _set_meta_field(self, v):    self._set_meta_field_fast(<uint8_t>v)

    def _get_meta_value(self):       return self._get_meta_value_fast()
    def _set_meta_value(self, v):    self._set_meta_value_fast(<uint8_t>v)

    def _get_tag(self):              return self._get_tag_fast()
    def _set_tag(self, v):           self._set_tag_fast(<uint16_t>v)

    def _get_addr(self):             return self._get_addr_fast()
    def _set_addr(self, v):          self._set_addr_fast(<uint64_t>v)

    def _get_ld_id(self):            return self._get_ld_id_fast()
    def _set_ld_id(self, v):         self._set_ld_id_fast(<uint8_t>v)

    def _get_rsvd(self):             return self._get_rsvd_fast()
    def _set_rsvd(self, v):          self._set_rsvd_fast(<uint32_t>v)

    def _get_tc(self):               return self._get_tc_fast()
    def _set_tc(self, v):            self._set_tc_fast(<uint8_t>v)

    def _get_padding(self):          return self._get_padding_fast()
    def _set_padding(self, v):       self._set_padding_fast(<uint8_t>v)

    # ------------------------------------------------------------------ Python properties
    valid       = property(_get_valid,       _set_valid)
    mem_opcode  = property(_get_mem_opcode,  _set_mem_opcode)
    snp_type    = property(_get_snp_type,    _set_snp_type)
    meta_field  = property(_get_meta_field,  _set_meta_field)
    meta_value  = property(_get_meta_value,  _set_meta_value)
    tag         = property(_get_tag,         _set_tag)
    addr        = property(_get_addr,        _set_addr)
    ld_id       = property(_get_ld_id,       _set_ld_id)
    rsvd        = property(_get_rsvd,        _set_rsvd)
    tc          = property(_get_tc,          _set_tc)
    padding     = property(_get_padding,     _set_padding)

    # ------------------------------------------------------------------ misc
    @classmethod
    def get_size(cls):
        return 13

    def __len__(self):
        return 13

    def __bytes__(self):
        return PyBytes_FromStringAndSize(<char*>self._p, 13)



# ─── packet object with integrated pool ─────────────────────────────────────
@cython.freelist(256)                    # C-level freelist for emergency speed
cdef class CxlMemPooledPacket:
    # ---------- class-wide pool (Python level, for debugging) ---------------
    _POOL_MAX = 8192
    _pool     = deque()

    # ---------- fixed constants --------------------------------------------
    _CAP = 200              # max bytes in backing buffer

    # ---------- instance fields --------------------------------------------
    cdef unsigned char[:] _ba           # zero-filled backing store
    cdef uint8_t[:]       _mv           # alias typed as uint8_t
    cdef Py_ssize_t       _cap
    cdef Py_ssize_t       _data_len

    cdef SystemHeader       _system_header
    cdef CxlMemHeader       _cxl_mem_header
    cdef CxlMemM2SReqHeader _m2sreq_header

    # ------------------------------------------------------------------ fast pool helpers
    cdef object _acquire(self):
        """C-speed allocator / recycler (no Python overhead)."""
        cdef object pool = CxlMemPooledPacket._pool
        print("HERE?")
        if pool:
            pkt = <CxlMemPooledPacket> pool.pop()
            pkt._relocate()
            return pkt
        # fresh object – normal allocation runs __cinit__
        return cls()

    cdef void _release(self):
        cdef object pool = self.__class__._pool
        pool = self.__class__._pool
        if len(pool) < self.__class__._POOL_MAX:
            pool.append(self)

    # ---------- public pool API & context manager ---------------------------
    @classmethod
    def acquire(cls):
        return cls._acquire()

    cpdef release(self):
        self._release()          # cheap; grabs GIL only for list append

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()

    def __del__(self):
        self.release()

    @classmethod
    def pool_size(cls):
        return len(cls._pool)

    # ------------------------------------------------------------------ one-time allocation
    cdef void _alloc_once(self):
        """Allocate backing store + header singletons (called exactly once)."""
        cdef Py_ssize_t n = self._CAP

        # zero-filled
        self._ba = view.array(shape=(n,),
                              itemsize=1,
                              format="B",
                              mode="c")
        self._mv  = self._ba
        self._cap = n
        self._data_len = 0

        self._system_header  = SystemHeader()
        self._cxl_mem_header = CxlMemHeader()
        self._m2sreq_header  = CxlMemM2SReqHeader()
        self._relocate()  # point views at buffer

    # ------------------------------------------------------------------ relocate header views
    cdef void _relocate(self):
        """Re-attach header singletons after buffer reuse."""
        cdef uint8_t* base = &self._mv[0]
        self._system_header.attach(base + 0)   # bytes 0-1
        self._cxl_mem_header.attach(base + 2)  # bytes 2-3
        self._m2sreq_header.attach(base + 6)   # bytes 6-18

    # ------------------------------------------------------------------ life-cycle hooks
    def __cinit__(self, payload: bytes or None = None):
        cdef const unsigned char[:] mv_src
        cdef unsigned char[:] mv_dst
        cdef uint8_t n

        print("cinit CALLED")
        if not hasattr(self, "_ba"):           # first time ever
            self._alloc_once()

        if payload is not None:                # receive path
            mv_src = data
            mv_dst = self._ba
            n = len(payload)
            if n > self._cap:
                raise ValueError("packet too large")
            memcpy(&mv_dst[17], &mv_src[0], n)
            self._data_len = n - 17
        else:
            self._data_len = 0                 # builder will fill later
        self._relocate()

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
        cdef CxlMemPooledPacket pkt
        cdef object pool = CxlMemPooledPacket._pool
        if pool:
            pkt = <CxlMemPooledPacket> pool.pop()
        else:
            pkt = cls()

        pkt._relocate()
        pkt._build(addr, opcode, meta_field, meta_value, snp_type, ld_id, data)
        return pkt

    cdef void _build(self,
                     addr: int,
                     opcode: int,
                     meta_field: int,
                     meta_value: int,
                     snp_type: int,
                     ld_id: int,
                     bytes data
    ):
        cdef const unsigned char[:] mv_src = data
        cdef unsigned char[:] mv_dst = self._ba

        cdef Py_ssize_t n = len(data)

        self._system_header.payload_type  = SYSTEM_PAYLOAD_TYPE.CXL_MEM
        self._system_header.payload_length = 17 + n
        self._cxl_mem_header.msg_class     = CXL_MEM_MSG_CLASS.M2S_REQ
        self._m2sreq_header.valid         = 1
        self._m2sreq_header.mem_opcode    = opcode
        self._m2sreq_header.meta_field    = meta_field
        self._m2sreq_header.meta_value    = meta_value
        self._m2sreq_header.snp_type      = snp_type
        self._m2sreq_header.ld_id         = ld_id
        self._m2sreq_header.addr          = addr >> 6

        if 17 + n > self._cap:
            raise ValueError("data too large")
        memcpy(&mv_dst[17], &mv_src[0], n)

        self._data_len = n

    # ------------------------------------------------------------------ mutators / accessors
    def set_data(self, bytes payload):
        cdef Py_ssize_t n = len(payload)
        if 17 + n > self._cap:
            raise ValueError("payload too large")
        self._ba[17:17 + n] = payload
        self._data_len = n
        self._system_header.payload_length = 17 + n

    def raw_bytes(self) -> bytes:
        return PyBytes_FromStringAndSize(<char*>&self._mv[0], 17 + self._data_len)

    @property
    def view(self):
        """Memory-view of the in-use bytes (header + payload)."""
        return self._mv[:17 + self._data_len]

    def is_mem_rd(self) -> bool:
        return self._m2sreq_header.mem_opcode == CXL_MEM_M2SREQ_OPCODE.MEM_RD

    # ------------------------------------------------------------------ python specials
    def __len__(self):
        return 17 + self._data_len



def demo():
    pkt1 = CxlMemPooledPacket.create(
        0x1000,
        5,
        100,
        200,
        222,
        5
    )
    #print("Here 1")
    raw  = bytes(pkt1.view)          # send
    #print("Here 2")
    del pkt1                         # recycled
    #print("Here 3")
    pkt2 = CxlMemPooledPacket(raw)   # receive using same object
    #print("Here 4")
    assert bytes(pkt2.view) == raw
    #print("Here 5")
    pkt2.release()
    #print("Round-trip OK, freelist length =", len(CxlMemPooledPacket._pool))