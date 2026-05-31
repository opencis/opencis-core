"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.

Generates packet_structs.py — a pure-Python drop-in for the Cython
packet_structs extension, so the codebase can run without a C compiler.
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


MAX_PACKET_SIZE = 512


def total_bytes(layout):
    max_bit = max(start + width for _, start, width in layout)
    return (max_bit + 7) // 8


def emit_header_class(name, layout):
    size = total_bytes(layout)
    lines = []
    lines.append(f"class {name}:")
    lines.append(f"    _size = {size}")
    lines.append("")
    lines.append("    def __init__(self):")
    lines.append(f"        self._buf = bytearray({size})")
    lines.append(f"        self._p = 0  # byte-offset into parent buffer (set by attach)")
    lines.append(f"        self._parent_buf = self._buf  # default: own buffer")
    lines.append("")
    lines.append("    def _attach(self, parent_buf: bytearray, offset: int):")
    lines.append("        self._parent_buf = parent_buf")
    lines.append("        self._p = offset")
    lines.append("")

    for field_name, start, width in layout:
        lines.append(f"    # field: {field_name}  bits {start}-{start+width-1} ({width} b)")
        lines.append("    @property")
        lines.append(f"    def {field_name}(self):")
        lines.append(f"        return _read_bits(self._parent_buf, self._p * 8 + {start}, {width})")
        lines.append(f"    @{field_name}.setter")
        lines.append(f"    def {field_name}(self, v):")
        lines.append(f"        _write_bits(self._parent_buf, self._p * 8 + {start}, {width}, v)")
        lines.append("")

    lines.append("    @classmethod")
    lines.append("    def get_size(cls):")
    lines.append(f"        return {size}")
    lines.append("")
    lines.append("    def __len__(self):")
    lines.append(f"        return {size}")
    lines.append("")
    lines.append("    def __bytes__(self):")
    lines.append(f"        return bytes(self._parent_buf[self._p : self._p + {size}])")
    lines.append("")
    return "\n".join(lines)


def emit_packet_class(packet_name, descriptor, field_sizes):
    layout = descriptor["layout"]
    create_args = descriptor.get("create_args", {})

    # Compute byte offsets for each header
    offset = 0
    offset_map = {}
    entry_sizes = []
    for struct, varname in layout:
        s = total_bytes(field_sizes[struct])
        offset_map[struct] = (offset, s)
        entry_sizes.append((struct, varname, offset, s))
        offset += s
    total_header = offset

    class_name = f"_Gen{packet_name}"

    lines = []
    lines.append(f"class {class_name}:")
    lines.append(f"    _header_size = {total_header}")
    lines.append("")
    lines.append(f"    def __init__(self, payload=None):")
    lines.append(f"        self._buf = bytearray({MAX_PACKET_SIZE})")
    lines.append(f"        self._data_length = 0")
    for struct, varname, off, size in entry_sizes:
        lines.append(f"        self._{varname} = {struct}()")
        lines.append(f"        self._{varname}._attach(self._buf, {off})")
    lines.append("        if payload is not None:")
    lines.append("            n = len(payload)")
    lines.append(f"            if n > {MAX_PACKET_SIZE}:")
    lines.append('                raise ValueError("packet too large")')
    lines.append("            self._buf[:n] = payload")
    lines.append(f"            self._data_length = n - {total_header}")
    lines.append("")

    # Header accessors
    for struct, varname, off, size in entry_sizes:
        lines.append("    @property")
        lines.append(f"    def {varname}(self):")
        lines.append(f"        return self._{varname}")
        lines.append("")

    # create_fields list
    create_fields = []
    for struct, varname in layout:
        for fld in create_args.get(struct, []):
            create_fields.append((struct, varname, fld))

    if create_fields:
        # create()
        params = ", ".join(f"{vn}__{fn}" for _, vn, fn in create_fields)
        lines.append("    @classmethod")
        lines.append(f"    def create(cls, {params}, data: bytes = None):")
        lines.append(f"        pkt = cls()")
        lines.append(f"        pkt._buf = bytearray({MAX_PACKET_SIZE})")
        for struct, varname, off, size in entry_sizes:
            lines.append(f"        pkt._{varname}._attach(pkt._buf, {off})")
        for _, vn, fn in create_fields:
            lines.append(f"        pkt._{vn}.{fn} = {vn}__{fn}")
        lines.append("        if data is not None:")
        lines.append(f"            ptr = {total_header}")
        lines.append("            n = len(data)")
        lines.append(f"            if {total_header} + n > {MAX_PACKET_SIZE}:")
        lines.append('                raise ValueError("data too large")')
        lines.append("            pkt._buf[ptr:ptr+n] = data")
        lines.append("            pkt._data_length = n")
        # set payload_length in system_header if it's in the layout
        if any(vn == "system_header" for _, vn, _ in create_fields):
            lines.append(f"        pkt._system_header.payload_length = {total_header} + pkt._data_length")
        elif any(vn == "system_header" for _, vn, __, ___ in entry_sizes):
            lines.append(f"        pkt._system_header.payload_length = {total_header} + pkt._data_length")
        lines.append("        return pkt")
        lines.append("")

        # assign()
        lines.append(f"    def assign(self, {params}, data: bytes = None):")
        lines.append(f"        self._buf = bytearray({MAX_PACKET_SIZE})")
        for struct, varname, off, size in entry_sizes:
            lines.append(f"        self._{varname}._attach(self._buf, {off})")
        for _, vn, fn in create_fields:
            lines.append(f"        self._{vn}.{fn} = {vn}__{fn}")
        lines.append("        if data is not None:")
        lines.append(f"            ptr = {total_header}")
        lines.append("            n = len(data)")
        lines.append("            self._buf[ptr:ptr+n] = data")
        lines.append("            self._data_length = n")
        if any(vn == "system_header" for _, vn, __, ___ in entry_sizes):
            lines.append(f"        self._system_header.payload_length = {total_header} + self._data_length")
        lines.append("")

    # set_data / get_data / helpers
    lines.append("    def set_data(self, data):")
    lines.append(f"        n = len(data)")
    lines.append(f"        if {total_header} + n > {MAX_PACKET_SIZE}:")
    lines.append('            raise ValueError("packet too large")')
    lines.append(f"        self._buf[{total_header}:{total_header}+n] = data")
    lines.append(f"        self._data_length = n")
    lines.append("")

    lines.append("    def get_data(self):")
    lines.append(f"        return bytes(self._buf[{total_header}:{total_header}+self._data_length])")
    lines.append("")

    lines.append("    def get_payload_offset(self):")
    lines.append(f"        return {total_header}")
    lines.append("")

    lines.append("    def get_size(self):")
    lines.append(f"        return {total_header} + self._data_length")
    lines.append("")

    lines.append("    def get_byte_offset(self, other):")
    for i, (struct, varname, off, size) in enumerate(entry_sizes):
        kw = "if" if i == 0 else "elif"
        lines.append(f"        {kw} isinstance(other, {struct}):")
        lines.append(f"            return {off}")
    lines.append(f"        raise TypeError(f'unsupported header type: {{type(other)}}')")
    lines.append("")

    lines.append("    def set_bytes(self, offset, data):")
    lines.append("        n = len(data)")
    lines.append("        self._buf[offset:offset+n] = data")
    lines.append("")

    lines.append("    def write_bits(self, start_bit, width, value):")
    lines.append("        _write_bits(self._buf, start_bit, width, value)")
    lines.append("")

    lines.append("    def read_bits(self, start_bit, width):")
    lines.append("        return _read_bits(self._buf, start_bit, width)")
    lines.append("")

    lines.append("    def get_bytes(self, start, length):")
    lines.append("        return bytes(self._buf[start:start+length])")
    lines.append("")

    lines.append("    def __len__(self):")
    lines.append(f"        return {total_header} + self._data_length")
    lines.append("")

    lines.append("    def __bytes__(self):")
    lines.append(f"        return bytes(self._buf[:{total_header} + self._data_length])")
    lines.append("")

    lines.append("    def __iter__(self):")
    lines.append(f"        return iter(self._buf[:{total_header} + self._data_length])")
    lines.append("")

    lines.append("    def __getitem__(self, key):")
    lines.append(f"        return self._buf[:{total_header} + self._data_length][key]")
    lines.append("")

    lines.append("    def __enter__(self):")
    lines.append("        return self")
    lines.append("")

    lines.append("    def __exit__(self, *a):")
    lines.append("        pass")
    lines.append("")

    # Public name alias (without _Gen prefix)
    lines.append(f"{packet_name} = {class_name}")
    lines.append("")

    return "\n".join(lines)


HEADER = '''\
"""
Auto-generated pure-Python fallback for the Cython packet_structs extension.
Generated by generate_py_fallback.py — do NOT edit by hand.

This module provides identical API to the compiled Cython extension so the
codebase runs without Microsoft Visual C++ Build Tools.
"""

# ---------------------------------------------------------------------------
# Bit manipulation helpers (mirrors the Cython _read_bits / _write_bits)
# ---------------------------------------------------------------------------

def _read_bits(buf: bytearray, start_bit: int, width: int) -> int:
    result = 0
    for i in range(width):
        byte_index = (start_bit + i) >> 3
        bit_offset = (start_bit + i) & 7
        if (buf[byte_index] >> bit_offset) & 1:
            result |= 1 << i
    return result


def _write_bits(buf: bytearray, start_bit: int, width: int, value: int) -> None:
    for i in range(width):
        byte_index = (start_bit + i) >> 3
        bit_offset = (start_bit + i) & 7
        if (value >> i) & 1:
            buf[byte_index] |= 1 << bit_offset
        else:
            buf[byte_index] &= ~(1 << bit_offset)

'''


def main():
    base = Path(__file__).parent
    fields = load_module(base / "fields.py", "fields")
    packets = load_module(base / "packets.py", "packets")

    out_file = base / "packet_structs.py"
    with open(out_file, "w", encoding="utf-8") as f:
        f.write(HEADER)

        field_sizes = {
            name: value
            for name, value in vars(fields).items()
            if not name.startswith("__") and isinstance(value, list)
        }

        f.write("# ---------------------------------------------------------------------------\n")
        f.write("# Header structs (one class per fields.py entry)\n")
        f.write("# ---------------------------------------------------------------------------\n\n")
        for name, layout in field_sizes.items():
            f.write(emit_header_class(name, layout))
            f.write("\n")

        f.write("# ---------------------------------------------------------------------------\n")
        f.write("# Composite packet classes (one class per packets.py entry)\n")
        f.write("# ---------------------------------------------------------------------------\n\n")
        for packet_name, descriptor in packets.PACKETS.items():
            f.write(emit_packet_class(packet_name, descriptor, field_sizes))
            f.write("\n")

        # Try to import compiled Cython module to override pure-Python implementation
        f.write("# ---------------------------------------------------------------------------\n")
        f.write("# Override with compiled Cython extension if available\n")
        f.write("# ---------------------------------------------------------------------------\n")
        f.write("try:\n")
        f.write("    from opencis.cxl.transport._packet_structs_cython import *\n")
        f.write("except ImportError:\n")
        f.write("    pass\n")

    print(f"Generated: {out_file}")


if __name__ == "__main__":
    main()
