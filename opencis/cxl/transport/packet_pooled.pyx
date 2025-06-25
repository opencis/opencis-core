# cython: language_level=3, boundscheck=False, wraparound=False, no_gc=True
from collections import deque
from libc.string  cimport memcpy
from packet_constants import *
from libc.stdint cimport uintptr_t, uint64_t
from cpython.ref cimport Py_INCREF


ctypedef enum:
    SYSTEM_PAYLOAD_TYPE_CXL_MEM = 7
    CXL_MEM_MSG_CLASS_M2S_REQ = 2
    CXL_MEM_M2SREQ_OPCODE_MEM_RD = 1


cdef class HeaderBuffer:
    cdef unsigned char* p

    cdef inline void relocate(self, unsigned char* q) nogil:
        self.p = q

    cpdef unsigned long long read_bits(self, int start_bit, int width):
        cdef unsigned char* buf = self.p
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
        cdef unsigned char* buf = self.p
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


cdef class SystemHeader(HeaderBuffer):
    @property
    def payload_type(self):
        return self.read_bits(0, 4)

    @payload_type.setter
    def payload_type(self, val):
        self.write_bits(0, 4, val & ((1 << 4) - 1))

    @property
    def payload_length(self):
        return self.read_bits(4, 12)

    @payload_length.setter
    def payload_length(self, val):
        self.write_bits(4, 12, val & ((1 << 12) - 1))

    @classmethod
    def get_size(cls):
        return 2

    def __len__(self):
        return self.get_size()

    def __bytes__(self):
        return self.to_bytes()

    def __cinit__(self, unsigned char[::1] buf):
        self._buf = buf


cdef class CxlMemHeader(HeaderBuffer):
    @property
    def port_index(self):
        return self.read_bits(0, 8)

    @port_index.setter
    def port_index(self, val):
        self.write_bits(0, 8, val & ((1 << 8) - 1))

    @property
    def msg_class(self):
        return self.read_bits(8, 8)

    @msg_class.setter
    def msg_class(self, val):
        self.write_bits(8, 8, val & ((1 << 8) - 1))

    @classmethod
    def get_size(cls):
        return 2

    def __len__(self):
        return self.get_size()

    def __bytes__(self):
        return self.to_bytes()

    def __cinit__(self, unsigned char[::1] buf):
        self._buf = buf




cdef class CxlMemM2SReqHeader(HeaderBuffer):
    @property
    def valid(self):
        return self.read_bits(0, 1)

    @valid.setter
    def valid(self, val):
        self.write_bits(0, 1, val & ((1 << 1) - 1))

    @property
    def mem_opcode(self):
        return self.read_bits(1, 4)

    @mem_opcode.setter
    def mem_opcode(self, val):
        self.write_bits(1, 4, val & ((1 << 4) - 1))

    @property
    def snp_type(self):
        return self.read_bits(5, 3)

    @snp_type.setter
    def snp_type(self, val):
        self.write_bits(5, 3, val & ((1 << 3) - 1))

    @property
    def meta_field(self):
        return self.read_bits(8, 2)

    @meta_field.setter
    def meta_field(self, val):
        self.write_bits(8, 2, val & ((1 << 2) - 1))

    @property
    def meta_value(self):
        return self.read_bits(10, 2)

    @meta_value.setter
    def meta_value(self, val):
        self.write_bits(10, 2, val & ((1 << 2) - 1))

    @property
    def tag(self):
        return self.read_bits(12, 16)

    @tag.setter
    def tag(self, val):
        self.write_bits(12, 16, val & ((1 << 16) - 1))

    @property
    def addr(self):
        return self.read_bits(28, 46)

    @addr.setter
    def addr(self, val):
        self.write_bits(28, 46, val & ((1 << 46) - 1))

    @property
    def ld_id(self):
        return self.read_bits(74, 4)

    @ld_id.setter
    def ld_id(self, val):
        self.write_bits(74, 4, val & ((1 << 4) - 1))

    @property
    def rsvd(self):
        return self.read_bits(78, 20)

    @rsvd.setter
    def rsvd(self, val):
        self.write_bits(78, 20, val & ((1 << 20) - 1))

    @property
    def tc(self):
        return self.read_bits(98, 2)

    @tc.setter
    def tc(self, val):
        self.write_bits(98, 2, val & ((1 << 2) - 1))

    @property
    def padding(self):
        return self.read_bits(100, 4)

    @padding.setter
    def padding(self, val):
        self.write_bits(100, 4, val & ((1 << 4) - 1))

    @classmethod
    def get_size(cls):
        return 13

    def __len__(self):
        return self.get_size()

    def __bytes__(self):
        return self.to_bytes()

    def __cinit__(self, unsigned char[::1] buf):
        self._buf = buf

# ------------------------------------------------------------------ #
#  POOL MIX-IN (cdef for speed, but *Python* classes can inherit it) #
# ------------------------------------------------------------------ #


# ------------------------------------------------------------
# pool_mixin.pyx  –  Minimal freelist mix-in (explicit release)
# ------------------------------------------------------------
# cython: language_level = 3
# cython: boundscheck = False, wraparound = False

from collections import deque
cimport cython








# ------------------------------------------------------------
# pool_mixin.pyx  –  Minimal, working freelist mix-in
# ------------------------------------------------------------
# cython: language_level = 3
# cython: boundscheck = False, wraparound = False

from collections import deque
cimport cython

# ------------------------------------------------------------
# pool_mixin_debug.pyx  –  Freelist mix-in WITH DEBUG PRINTS
# ------------------------------------------------------------
# cython: language_level = 3
# cython: boundscheck   = False
# cython: wraparound    = False

from collections import deque
cimport cython


# ------------------------------------------------------------
# pool_mixin_debug.pyx  –  Freelist mix-in WITH DEBUG PRINTS
# (compile-tested on Cython 3.0)
# ------------------------------------------------------------
# cython: language_level = 3
# cython: boundscheck   = False
# cython: wraparound    = False

from collections import deque
cimport cython


# ------------------------------------------------------------
# pool_mixin_debug.pyx  –  Freelist mix-in WITH DEBUG PRINTS
# (compile-tested on Cython 3.0)
# ------------------------------------------------------------
# cython: language_level = 3
# cython: boundscheck   = False
# cython: wraparound    = False

from collections import deque
cimport cython


# cython: language_level=3, boundscheck=False, wraparound=False
from collections import deque
cimport cython


# cython: language_level=3, boundscheck=False, wraparound=False
from collections import deque
cimport cython


cdef class _PoolMixin:
    """Freelist mix-in – DEBUG BUILD."""

    _pool     = deque()   # Python-level attributes (always mutable)
    _POOL_MAX = 4

    # ---------- borrow / allocate --------------------------------------
    cpdef _acquire(cls):
        # C-level declarations *first*
        cdef object pool = cls._pool
        cdef object pkt, hook

        print(f"[DEBUG] _acquire<{cls.__name__}> pool_len={len(pool)}")

        if pool:                               # recycled
            print("[DEBUG]   Recycled -> pop")
            pkt  = pool.pop()
            hook = getattr(pkt, "_relocate", None)
            if hook is not None:
                print(f"[DEBUG]   _relocate id={id(pkt)}")
                hook()
            else:
                print("[DEBUG]   No _relocate()")
            return pkt

        # fresh
        print("[DEBUG]   Fresh allocation")
        pkt  = super(cls, cls).__new__(cls)
        hook = getattr(pkt, "_alloc_once", None)
        if hook is None:
            raise AttributeError(f"{cls.__name__} missing _alloc_once()")
        print(f"[DEBUG]   _alloc_once id={id(pkt)}")
        hook()
        return pkt

    # ---------- Python-level wrapper -----------------------------------
    @classmethod
    def acquire(cls, *a, **kw):
        print(f"[DEBUG] acquire<{cls.__name__}> (Python caller)")
        return cls._acquire(cls, *a, **kw)

    # ---------- return to freelist -------------------------------------
    cdef void release(self):
        cdef object cls  = self.__class__
        cdef object pool = cls._pool

        print(f"[DEBUG] release<{cls.__name__}> id={id(self)} pool_len={len(pool)}")
        if len(pool) < cls._POOL_MAX:
            pool.append(self)
            print(f"[DEBUG]   Recycled (pool now {len(pool)})")
        else:
            print(f"[DEBUG]   Pool full ({cls._POOL_MAX}) -> drop")

    # ---------- context-manager hooks ----------------------------------
    def __enter__(self):
        print(f"[DEBUG] __enter__ id={id(self)}")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        print(f"[DEBUG] __exit__ id={id(self)} exc={exc_type}")
        self.release()

    # ---------- helper --------------------------------------------------
    @classmethod
    def pool_size(cls): return len(cls._pool)




cdef inline void _do_build(
        SystemHeader                sh,
        CxlMemHeader                mh,
        CxlMemM2SReqHeader          rh,
        uint64_t                    addr,
        int                         opcode,
        int                         meta_field,
        int                         meta_value,
        int                         snp_type,
        int                         ld_id):

    sh.payload_type  = SYSTEM_PAYLOAD_TYPE.CXL_MEM
    mh.msg_class     = CXL_MEM_MSG_CLASS.M2S_REQ
    rh.valid         = 1
    rh.mem_opcode    = opcode
    rh.meta_field    = meta_field
    rh.meta_value    = meta_value
    rh.snp_type      = snp_type
    rh.ld_id         = ld_id
    rh.addr          = addr >> 6
    sh.payload_length = 17        # 17-byte header, no data

cdef inline void _do_relocate(SystemHeader sh,
                              CxlMemHeader mh,
                              CxlMemM2SReqHeader rh,
                              unsigned char[::1] mv):
    cdef unsigned char* base = &mv[0]        # raw pointer to byte 0
    sh.relocate(base + 0)                    # [0:2]
    mh.relocate(base + 2)                    # [2:4]
    rh.relocate(base + 4)                    # [4:17]

class CxlMemPooledPacket(_PoolMixin):
    """
    · pkt = CxlMemPooledPacket(raw_bytes)         # receive path
    · pkt = CxlMemPooledPacket.create(...)        # send/builder path
    """

    # ------------ one-time class initialisation --------------------
    _POOL_MAX: int = 4
    _pool: deque   = deque()

    # ------------ internal helpers --------------------------------
    def _alloc_once(self):                 # <<-- NOTE: Python-level def (fine)
        cap      = 17 + 4096               # hdr + max payload
        self._ba = bytearray(cap)
        self._mv = memoryview(self._ba).cast('B')
        self.system_header_  = SystemHeader(self._mv[0:2])
        self.cxl_mem_header_ = CxlMemHeader(self._mv[2:4])
        self.m2sreq_header_  = CxlMemM2SReqHeader(self._mv[4:17])
        self._cap = cap
        self._data_len = 0
        
    # ------------ constructor (receive path) -----------------------
    def __init__(self, payload: bytes | None = None):
        if not hasattr(self, "_ba"):
            self._alloc_once()

        if payload is not None:
            n = len(payload)
            if n > self._cap:
                raise ValueError("packet too large")
            self._ba[:n] = payload
            self._data_len = n - 17
        else:
            self._data_len = 0
        self._relocate()


    def _relocate(self) -> None:
        _do_relocate(self.system_header_,
                     self.cxl_mem_header_,
                     self.m2sreq_header_,
                     self._mv)

    # ------------ builder (send path) ------------------------------
    @classmethod
    def create(
        cls,
        addr: int,
        opcode: int,
        meta_field: int,
        meta_value: int,
        snp_type: int,
        ld_id: int
    ):
        cdef object pkt = cls._acquire(cls) # C-speed call
        print("Here 11")
        #pkt = cls._acquire()
        print("Here 12")
        _do_build(
            pkt.system_header_,
            pkt.cxl_mem_header_,
            pkt.m2sreq_header_,
            addr,
            opcode,
            meta_field,
            meta_value,
            snp_type,
            ld_id,
        )
        print("Here 13")
        return pkt

    def raw_bytes(self) -> bytes:
        return bytes(self._buffer[:17])

    def _build(self,
               addr: int,
               opcode: int,
               meta_field: int,
               meta_value: int,
               snp_type: int,
               ld_id: int) -> None:
        """
        Python-visible wrapper that just forwards to the inline C helper.
        All heavy work happens in _do_build, so this wrapper’s overhead is
        a single C/Python call, typically < 80 ns.
        """
        self._relocate()            # three pointer stores
        _do_build(self.system_header_,
                  self.cxl_mem_header_,
                  self.m2sreq_header_,
                  addr,
                  opcode,
                  meta_field,
                  meta_value,
                  snp_type,
                  ld_id)
        self._data_length = 0       # no payload in an M2S-REQ

    # ------------ convenience for writer.write() -------------------
    @property
    def view(self):
        return self._mv[:17 + self._data_len]

    # ------------ example predicate from your snippet --------------
    def is_mem_rd(self) -> bool:
        return self.m2sreq_header.mem_opcode == CXL_MEM_M2SREQ_OPCODE.MEM_RD

def demo():
    pkt1 = CxlMemPooledPacket.create(
        0x1000,
        5,
        100,
        200,
        222,
        5
    )
    print("Here 1")
    raw  = bytes(pkt1.view)          # send
    print("Here 2")
    del pkt1                         # recycled
    print("Here 3")
    pkt2 = CxlMemPooledPacket(raw)   # receive using same object
    print("Here 4")
    assert bytes(pkt2.view) == raw
    print("Here 5")
    print("Round-trip OK, freelist length =", len(CxlMemPooledPacket._pool))