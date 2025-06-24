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
    field_defs = ""
    for n, s, w in layout:
        field_defs += (
            "    @property\n"
            f"    def {n}(self):\n"
            f"        return self.read_bits({s}, {w})\n\n"
            f"    @{n}.setter\n"
            f"    def {n}(self, val):\n"
            f"        self.write_bits({s}, {w}, val & ((1 << {w}) - 1))\n\n"
        )

    total_bits = max(s + w for _, s, w in layout)
    total_bytes = (total_bits + 7) // 8

    return (
        f"cdef class {name}(HeaderBuffer):\n"
        f"{field_defs}"
        "    @classmethod\n"
        "    def get_size(cls):\n"
        f"        return {total_bytes}\n\n"
        "    def __len__(self):\n"
        "        return self.get_size()\n\n"
        "    def __bytes__(self):\n"
        "        return self.to_bytes()\n\n"
        "    def __cinit__(self, unsigned char[::1] buf):\n"
        "        self._buf = buf\n\n"
    )


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


def main():
    base = Path(__file__).parent
    fields = load_module(base / "fields.py", "fields")
    packets = load_module(base / "packets.py", "packets")

    out_file = base / "packet_structs.pyx"
    with open(out_file, "w") as f:
        f.write("from opencis.cxl.transport.packet_base cimport PacketBuffer, HeaderBuffer\n\n")

        field_sizes = {
            name: value
            for name, value in vars(fields).items()
            if not name.startswith("__") and isinstance(value, list)
        }

        for name, layout in field_sizes.items():
            f.write(emit_struct(name, layout))
            f.write("\n")

        f.write(
            "# Generated file\n\n"
            "from opencis.cxl.transport.packet_base cimport PacketBuffer\n"
            "from libc.string cimport memcpy\n\n"
        )
        for packet_name, layout in packets.PACKETS.items():
            f.write(emit_composite(packet_name, layout, field_sizes))
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
