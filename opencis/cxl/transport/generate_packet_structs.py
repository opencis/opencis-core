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
        "    __slots__ = ()\n"
        "    cdef uint8_t* _p\n\n"
        "    def __cinit__(self):\n"
        "        self._p = <uint8_t*>0         # NULL until first attach()\n\n"
        "    cdef void attach(self, uint8_t* p) noexcept nogil:\n"
        "        self._p = p                   # 0-cost pointer swap\n\n"
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
                    f"        self._p[{byte}] = (self._p[{byte}] & 0x{clear:02X}) | (v & 0x{mask:02X})\n\n"
                )
            else:
                code += (
                    f"    cdef inline void _set_{field_name}(self, uint8_t v) noexcept nogil:\n"
                    f"        self._p[{byte}] = (self._p[{byte}] & 0x{clear:02X}) | ((v & 0x{mask:02X}) << {bit})\n\n"
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


def emit_composite(packet_name, layout, field_sizes):
    packet_name = f"_Gen{packet_name}"
    lines = [f"\ncdef class {packet_name}(PacketBuffer):"]

    has_data_field = False
    field_entries = []
    for entry in layout:
        if isinstance(entry, tuple) and entry[0] == "DataField":
            has_data_field = True
            field_entries.append(entry)
        elif isinstance(entry, tuple):
            field_entries.append(entry)
        else:
            field_entries.append((entry, entry.lower()))

    offset = 0
    offset_map = {}
    for struct, _ in field_entries:
        if struct == "DataField":
            continue
        struct_fields = field_sizes[struct]
        size_bits = max(start + width for _, start, width in struct_fields)
        size_bytes = (size_bits + 7) // 8
        offset_map[struct] = (offset, size_bytes)
        offset += size_bytes

    total_header_bytes = offset

    lines.append("    cdef readonly int HEADER_SIZE")
    lines.append("    cdef int _data_length")

    for struct, varname in field_entries:
        if struct != "DataField":
            lines.append(f"    cdef {struct} {varname}_")
    lines.append("")

    for struct, varname in field_entries:
        if struct != "DataField":
            lines.append("    @property")
            lines.append(f"    def {varname}(self):")
            lines.append(f"        return self.{varname}_")
            lines.append("")

    lines.append("    def __cinit__(self, buf=None):")
    lines.append(f"        self.HEADER_SIZE = {total_header_bytes}")
    lines.append("        if buf is not None:")
    lines.append("            self._data_length = len(buf) - self.HEADER_SIZE")
    lines.append("        else:")
    lines.append("            self._data_length = 0")
    lines.append("")
    lines.append("        cdef unsigned char[::1] mv = self._buf")
    for struct, varname in field_entries:
        if struct == "DataField":
            continue
        offset_start, size_bytes = offset_map[struct]
        lines.append(
            f"        self.{varname}_ = "
            f"{struct}(mv[{offset_start}:{offset_start + size_bytes}])"
        )

    lines.append("")
    lines.append("    def get_payload_offset(self) -> int:")
    lines.append("        return self.HEADER_SIZE")
    lines.append("")

    if has_data_field:
        lines.append("    cpdef bytes get_data(self):")
        lines.append("        if self._data_length <= 0:")
        lines.append("            return b''")
        lines.append(
            "        return (<const unsigned char*> "
            f"&self._buf[{total_header_bytes}])[:self._data_length]"
        )
        lines.append("")
        lines.append("    cpdef void set_data(self, data):")
        lines.append("        cdef const unsigned char* ptr = data")
        lines.append("        cdef Py_ssize_t n = len(data)")
        lines.append("        self.set_data_raw(ptr, n)")
        lines.append("")
        lines.append("    cpdef void set_data_raw(self, const unsigned char* data, Py_ssize_t n):")
        lines.append(f"        memcpy(&self._buf[{total_header_bytes}], data, n)")
        lines.append("        self._data_length = n")
    else:
        lines.append("    cpdef bytes get_data(self):")
        lines.append('        return b""')
        lines.append("")
        lines.append("    cpdef void set_data(self, data):")
        lines.append("        pass")
        lines.append("")
        lines.append("    cpdef void set_data_raw(self, const unsigned char* data, Py_ssize_t n):")
        lines.append("        pass")
    lines.append("")
    lines.append("    cpdef int get_size(self):")
    lines.append("        return self.HEADER_SIZE + self._data_length")
    lines.append("")
    lines.append("    def __len__(self):")
    lines.append("        return self.get_size()")
    lines.append("")
    lines.append("    def __bytes__(self):")
    lines.append("        return self.to_bytes()")

    return "\n".join(lines)


TOP_CONTENT = """# cython: language_level=3, boundscheck=False, wraparound=False, no_gc=True, infer_types=True
from libc.stdint cimport uint8_t, uint16_t, uint32_t, uint64_t
from libc.string  cimport memcpy
from cpython.bytes cimport PyBytes_FromStringAndSize
from libc.stdint cimport uintptr_t, uint8_t, uint16_t, uint32_t, uint64_t
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

    # Pure C pointer math—no GIL needed
    p.buf[p.tail] = obj
    p.tail    = (p.tail + 1) & (POOL_SIZE - 1)
    p.count  += 1


cdef inline PyObject* pool_pop(PoolStruct *p) noexcept nogil:
    if p.count == 0:
        return NULL

    cdef PyObject *obj = p.buf[p.head]
    p.buf[p.head]     = NULL
    p.head            = (p.head + 1) & (POOL_SIZE - 1)
    p.count          -= 1

    return obj  # caller owns the reference held by the pool
"""


def main():
    base = Path(__file__).parent
    fields = load_module(base / "fields.py", "fields")
    packets = load_module(base / "packets.py", "packets")

    out_file = base / "packet_test.pyx"
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

        # f.write(
        #     "# Generated file\n\n"
        #     "from opencis.cxl.transport.packet_base cimport PacketBuffer\n"
        #     "from libc.string cimport memcpy\n\n"
        # )
        # for packet_name, layout in packets.PACKETS.items():
        #     f.write(emit_composite(packet_name, layout, field_sizes))
        #     f.write("\n")

        # py_shim = base / "packet_structs.pyi"
        # with py_shim.open("w") as s:
        #     s.write(
        #         "# Auto-generated shim. Do NOT edit.\n\n"
        #         "# pylint: disable=missing-module-docstring\n\n"
        #     )
        #     for pkt in packets.PACKETS:
        #         s.write(f"class _Gen{pkt}: ...\n")
        #     for hdr in field_sizes:
        #         s.write(f"class {hdr}: ...\n")


if __name__ == "__main__":
    main()
