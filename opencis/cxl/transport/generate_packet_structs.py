"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from pathlib import Path
import importlib.util
import sys


def load_module(path, module_name):
    spec = importlib.util.spec_from_file_location(module_name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


def emit_struct(name, layout):
    total_bits = max(start + width for _, start, width in layout)
    size = (total_bits + 7) // 8

    LINE_WIDTH = 75
    dash_line = "─" * LINE_WIDTH

    code = (
        f"# {dash_line}\n"
        f"#    {name}  ({size} bytes)\n"
        f"# {dash_line}\n"
        f"cdef class {name}:\n"
        "    __slots__ = ('_p')\n"
        "    cdef uint8_t* _p\n\n"
        "    def __cinit__(self):\n"
        "        self._p = <uint8_t*>NULL  # NULL until first attach()\n\n"
        "    cdef void attach(self, uint8_t* p) noexcept nogil:\n"
        "        self._p = p\n\n"
    )

    for field_name, start, width in layout:
        end = start + width - 1
        spec = f"bit {start}" if width == 1 else f"bits {start}-{end}"
        suffix = f" ({width} b)"
        comment = f"    # ───── {field_name} : {spec}{suffix} "
        pad_len = LINE_WIDTH - (len(comment) - 2)
        code += comment + "─" * pad_len + "\n"

        byte = start // 8
        bit = start % 8

        if width <= 8:
            mask = (1 << width) - 1
            clear = ~(mask << bit) & 0xFF

            # getter
            if bit == 0 and width == 8:
                code += (
                    f"    cdef inline uint8_t _get_{field_name}(self) noexcept nogil:\n"
                    f"        return self._p[{byte}]\n\n"
                )
            elif bit == 0:
                code += (
                    f"    cdef inline uint8_t _get_{field_name}(self) noexcept nogil:\n"
                    f"        return self._p[{byte}] & 0x{mask:02X}\n\n"
                )
            else:
                code += (
                    f"    cdef inline uint8_t _get_{field_name}(self) noexcept nogil:\n"
                    f"        return (self._p[{byte}] >> {bit}) & 0x{mask:02X}\n\n"
                )

            # setter
            if bit == 0 and width == 8:
                code += (
                    f"    cdef inline void _set_{field_name}(self, uint8_t v) noexcept nogil:\n"
                    f"        self._p[{byte}] = v\n\n"
                )
            elif bit == 0:
                code += (
                    f"    cdef inline void _set_{field_name}(self, uint8_t v) noexcept nogil:\n"
                    f"        self._p[{byte}] = (self._p[{byte}] & 0x{clear:02X}) | "
                    f"(v & 0x{mask:02X})\n\n"
                )
            else:
                code += (
                    f"    cdef inline void _set_{field_name}(self, uint8_t v) noexcept nogil:\n"
                    f"        self._p[{byte}] = (self._p[{byte}] & 0x{clear:02X}) | "
                    f"((v & 0x{mask:02X}) << {bit})\n\n"
                )
        else:
            # wide fields
            if width <= 16:
                ctype = "uint16_t"
            elif width <= 32:
                ctype = "uint32_t"
            else:
                ctype = "uint64_t"

            code += (
                f"    cdef inline {ctype} _get_{field_name}(self) noexcept nogil:\n"
                f"        return <{ctype}>_read_bits(self._p, {start}, {width})\n\n"
                f"    cdef inline void _set_{field_name}(self, {ctype} v) noexcept nogil:\n"
                f"        _write_bits(self._p, {start}, {width}, v)\n\n"
            )

        # property and setter
        cast = (
            "uint8_t"
            if width <= 8
            else "uint16_t" if width <= 16 else "uint32_t" if width <= 32 else "uint64_t"
        )
        code += (
            f"    @property\n"
            f"    def {field_name}(self):\n"
            f"        return self._get_{field_name}()\n\n"
            f"    @{field_name}.setter\n"
            f"    def {field_name}(self, v):\n"
            f"        self._set_{field_name}(<{cast}>v)\n\n"
        )

    code += (
        "    # ───── misc helpers ────────────────────────────────────────────────────\n"
        "    @classmethod\n"
        f"    def get_size(cls):\n"
        f"        return {size}\n\n"
        "    def __len__(self):\n"
        f"        return {size}\n\n"
        "    def __bytes__(self):\n"
        f"        return PyBytes_FromStringAndSize(<char*>self._p, {size})\n"
    )
    return code


def emit_composite(packet_name, descriptor, field_sizes):
    raw_name = packet_name
    layout = descriptor["layout"]
    create_args = descriptor.get("create_args", {})

    # internal names
    class_name = f"_Gen{raw_name}"
    pool_name = f"_{class_name}_pool"

    lines = []
    lines.append(f"cdef PoolStruct {pool_name}\n")
    lines.append(f"cdef class {class_name}:")
    lines.append("    # class member vars")

    # build (struct, varname) list
    field_entries = []
    for entry in layout:
        struct, varname = entry
        field_entries.append((struct, varname))

    # compute byte-offsets for each struct
    offset = 0
    offset_map = {}
    for struct, _ in field_entries:
        struct_fields = field_sizes[struct]
        max_bit = max(start + width for _, start, width in struct_fields)
        size_bytes = (max_bit + 7) // 8
        offset_map[struct] = (offset, size_bytes)
        offset += size_bytes
    total_header_bytes = offset

    # emit declarations
    for struct, varname in field_entries:
        lines.append(f"    cdef {struct} _{varname}")
    lines.append("    cdef unsigned char _buf[MAX_PACKET_SIZE]")
    lines.append("    cdef int _data_length\n")

    # lifecycle / pool management
    lines.append("    #────────────────── Life-cycle management ──────────────────")
    lines.append("    cdef void _release(self):")
    lines.append(f"        pool_push(&{pool_name}, <PyObject*> self)\n")
    lines.append("    cdef inline void _relocate(self) noexcept nogil:")
    lines.append("        cdef unsigned char* base = &self._buf[0]")
    for struct, varname in field_entries:
        off, _ = offset_map[struct]
        lines.append(f"        self._{varname}.attach(base + {off})")
    lines.append("")

    # __cinit__ (first-time init + optional payload copy)
    lines.append("    #─────────────────────── Builder ───────────────────────")
    lines.append("    def __cinit__(self, payload=None):")
    lines.append("        if not hasattr(self, '_data_length'):")
    lines.append("            # first time only: allocate sub-headers")
    lines.append("            self._data_length = 0")
    for struct, varname in field_entries:
        lines.append(f"            self._{varname} = {struct}()")
    lines.append("            self._relocate()")
    lines.append("            Py_INCREF(self)\n")
    lines.append("        if payload is not None:")
    lines.append("            src = <const unsigned char*> payload")
    lines.append("            dst = &self._buf[0]")
    lines.append("            n = len(payload)")
    lines.append("            if n > MAX_PACKET_SIZE:")
    lines.append('                raise ValueError("packet too large")')
    lines.append("            memcpy(dst, src, n)")
    lines.append(f"            self._data_length = n - {total_header_bytes}\n")

    create_fields = []
    for struct, varname in field_entries:
        for fld in create_args.get(struct, []):
            create_fields.append((struct, varname, fld))

    if create_fields:
        # _build()
        lines.append("    cdef inline void _build(")
        lines.append("        self,")
        for struct, varname, fld_name in create_fields:
            fields = field_sizes[struct]

            (_, _, fld_width) = next((tup for tup in fields if tup[0] == fld_name), None)
            if fld_width > 32:
                lines.append(f"        unsigned long long {varname}__{fld_name},")
            else:
                lines.append(f"        int {varname}__{fld_name},")
        lines.append("        const unsigned char* data_src,")
        lines.append("        Py_ssize_t data_length")
        lines.append("    ) noexcept nogil:")
        lines.append("        cdef unsigned char* dst\n")
        lines.append("        memset(&self._buf[0], 0, MAX_PACKET_SIZE)")
        for _, varname, fld in create_fields:
            lines.append(f"        self._{varname}._set_{fld}({varname}__{fld})")
        lines.append("        if data_src:")
        lines.append(f"            dst = &self._buf[{total_header_bytes}]")
        lines.append(f"            if data_length > MAX_PACKET_SIZE - {total_header_bytes}:")
        lines.append('                raise ValueError("data too large")')
        lines.append("            memcpy(dst, data_src, data_length)")
        lines.append("            self._data_length = data_length")
        lines.append(
            f"        self._system_header._set_payload_length({total_header_bytes} + data_length)"
        )
        lines.append("")

    lines.append("    #────────────────── Python Interface ──────────────────")
    if create_fields:
        # create()
        lines.append("    @classmethod")
        lines.append("    def create(")
        lines.append("        cls,")
        for _, varname, fld in create_fields:
            lines.append(f"        {varname}__{fld},")
        lines.append("        data: bytes | None = None,")
        lines.append("    ):")
        lines.append("        cdef PyObject *tmp")
        lines.append(f"        cdef {class_name} pkt")
        lines.append("        cdef Py_ssize_t data_length")
        lines.append("        cdef const unsigned char* ptr")
        lines.append("")
        lines.append("        if data:")
        lines.append("            data_length = len(data)")
        lines.append("            ptr = data")
        lines.append("        else:")
        lines.append("            data_length = 0")
        lines.append("            ptr = NULL")
        lines.append("")
        lines.append(f"        tmp = pool_pop(&{pool_name})")
        lines.append("        if tmp == NULL:")
        lines.append("            pkt = cls()")
        lines.append("        else:")
        lines.append("            pkt = <" + class_name + "> tmp\n")
        lines.append("        pkt._relocate()")
        build_args = ",\n".join(
            f"            {varname}__{fld}" for _, varname, fld in create_fields
        )
        if build_args:
            build_args += ", "
        build_args += "\n            ptr,\n            data_length,"
        lines.append(f"        pkt._build(\n{build_args}\n        )")
        lines.append("        return pkt\n")

        # assign()
        lines.append("    def assign(")
        lines.append("        self,")
        for _, varname, fld in create_fields:
            lines.append(f"        {varname}__{fld},")
        lines.append("        data: bytes | None = None,")
        lines.append("    ):")
        lines.append("        cdef Py_ssize_t data_length")
        lines.append("        cdef const unsigned char* ptr")
        lines.append("")
        lines.append("        if data:")
        lines.append("            data_length = len(data)")
        lines.append("            ptr = data")
        lines.append("        else:")
        lines.append("            data_length = 0")
        lines.append("            ptr = NULL")
        lines.append("")
        lines.append("        self._relocate()")
        build_args = ",\n".join(
            f"            {varname}__{fld}" for _, varname, fld in create_fields
        )
        if build_args:
            build_args += ", "
        build_args += "\n            ptr,\n            data_length,"
        lines.append(f"        self._build(\n{build_args}\n        )")
        lines.append("")

    # set_data()
    lines.append("    cpdef set_data(self, data):")
    lines.append("        src = <const unsigned char*> data")
    lines.append(f"        dst = &self._buf[{total_header_bytes}]")
    lines.append("        n = len(data)")
    lines.append(f"        if {total_header_bytes} + n > MAX_PACKET_SIZE:")
    lines.append('            raise ValueError("packet too large")')
    lines.append("        memcpy(dst, src, n)")
    lines.append("        self._data_length = n\n")

    # get_data()
    lines.append("    cpdef get_data(self):")
    lines.append(
        f"        return PyBytes_FromStringAndSize(<char*>&self._buf[{total_header_bytes}], "
        "self._data_length)\n"
    )
    lines.append("    cpdef int get_payload_offset(self):")
    lines.append(f"       return {total_header_bytes}\n")

    lines.append("    cpdef int get_byte_offset(self, object other):")
    lines.append("        cdef uint8_t* base_ptr  = &self._buf[0]")
    lines.append("        cdef uint8_t* other_ptr = NULL")
    for i, (struct, varname) in enumerate(field_entries):
        if i == 0:
            lines.append(f"        if isinstance(other, {struct}):")
        else:
            lines.append(f"        elif isinstance(other, {struct}):")
        lines.append(f"            other_ptr = (<{struct}> other)._p")
    lines.append("        else:")
    lines.append('            raise TypeError(f"unsupported header type: {type(other)}")')
    lines.append("        return <int>(other_ptr - base_ptr)\n")

    lines.append("    cpdef void set_bytes(self, int offset, object data):")
    lines.append("        cdef const unsigned char[::1] view = data")
    lines.append("        cdef int i")
    lines.append("        for i in range(view.shape[0]):")
    lines.append("            self._buf[offset + i] = view[i]\n")

    lines.append(
        "    cpdef void write_bits(self, int start_bit, int width, unsigned long long value):"
    )
    lines.append("        _write_bits(&self._buf[0], start_bit, width, value)\n")

    lines.append("    cpdef unsigned long long read_bits(self, int start_bit, int width):")
    lines.append("        return _read_bits(&self._buf[0], start_bit, width)\n")

    lines.append("    cpdef get_bytes(self, int start, int length):")
    lines.append("        return PyBytes_FromStringAndSize(<char*>&self._buf[start], length)\n")

    lines.append("    #──────────────────── Header accessors ────────────────────")
    for struct, varname in field_entries:
        lines.append("    @property")
        lines.append(f"    def {varname}(self):")
        lines.append(f"        return self._{varname}\n")

    lines.append("    def __enter__(self):")
    lines.append("        return self\n")
    lines.append("    def __exit__(self, exc_type, exc_val, exc_tb):")
    lines.append("        self._release()\n")
    lines.append("    def __del__(self):")
    lines.append("        self._release()\n")
    lines.append("    def __len__(self):")
    lines.append(f"        return {total_header_bytes} + self._data_length\n")
    lines.append("    def __bytes__(self):")
    lines.append(
        f"        return PyBytes_FromStringAndSize(<char *> self._buf, "
        f"{total_header_bytes} + self._data_length)\n"
    )

    return "\n".join(lines)


TOP_CONTENT = """
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
        buf[byte_off] = (buf[byte_off] & ~mask) | \\
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
    MAX_PACKET_SIZE = 512
    POOL_SIZE = 128


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

"""


def main():
    base = Path(__file__).parent
    fields = load_module(base / "fields.py", "fields")
    packets = load_module(base / "packets.py", "packets")

    out_file = base / "packet_structs.pyx"
    with open(out_file, "w") as f:
        f.write(TOP_CONTENT)

        field_sizes = {
            name: value
            for name, value in vars(fields).items()
            if not name.startswith("__") and isinstance(value, list)
        }

        for name, layout in field_sizes.items():
            f.write(emit_struct(name, layout))
            f.write("\n")

        for packet_name, descriptor in packets.PACKETS.items():
            f.write(emit_composite(packet_name, descriptor, field_sizes))
            f.write("\n")

        py_shim = base / "packet_structs.pyi"
        with py_shim.open("w") as s:
            s.write(
                "# Auto-generated shim. Do NOT edit.\n\n"
                "# pylint: disable=missing-module-docstring\n\n"
            )
            for pkt in packets.PACKETS:
                s.write(f"class _Gen{pkt}: ...\n")
            for hdr in field_sizes:
                s.write(f"class {hdr}: ...\n")


if __name__ == "__main__":
    main()
