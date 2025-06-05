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
    field_defs = "".join(
        f"    @property\n"
        f"    def {n}(self):\n"
        f"        return self.read_bits({s}, {w})\n\n"
        f"    @{n}.setter\n"
        f"    def {n}(self, val):\n"
        f"        self.write_bits({s}, {w}, val)\n\n"
        for n, s, w in layout
    )
    return f"cdef class {name}(PacketBuffer):\n{field_defs}\n"


def emit_composite(packet_name, layout, field_sizes):
    lines = [f"cdef class Raw{packet_name}(PacketBuffer):"]
    offset = 0
    field_entries = []

    # Normalize layout
    for entry in layout:
        if isinstance(entry, tuple):
            field_entries.append(entry)
        elif entry == "DataField":
            field_entries.append("DataField")
        else:
            field_entries.append((entry, entry.lower()))

    # Compute ACTUAL_SIZE in bytes
    total_bits = 0
    for entry in field_entries:
        if entry == "DataField":
            continue
        struct, _ = entry
        total_bits += sum(w for _, _, w in field_sizes[struct])
    total_bytes = (total_bits + 7) // 8

    lines.append(f"    cdef readonly int ACTUAL_SIZE")
    lines.append(f"    cdef int _data_length")

    # Declare cdef fields
    for entry in field_entries:
        if entry == "DataField":
            continue
        struct, varname = entry
        lines.append(f"    cdef {struct} {varname}_")

    lines.append("")

    # Python properties
    for entry in field_entries:
        if entry == "DataField":
            continue
        _, varname = entry
        lines.append(f"    @property")
        lines.append(f"    def {varname}(self):")
        lines.append(f"        return self.{varname}_")
        lines.append("")

    # __cinit__ with safe bytearray allocation
    lines.append("    def __cinit__(self, unsigned char[::1] buf = None):")
    lines.append("        if buf is None:")
    lines.append(f"            raw_buf = bytearray({total_bytes})")
    lines.append("            buf = raw_buf")
    lines.append(f"        self.ACTUAL_SIZE = {total_bytes}")
    lines.append("        self.buf = buf")

    offset = 0
    for entry in field_entries:
        if entry == "DataField":
            continue
        struct, varname = entry
        size_bits = sum(w for _, _, w in field_sizes[struct])
        size_bytes = (size_bits + 7) // 8
        lines.append(f"        self.{varname}_ = {struct}(buf[{offset}:{offset + size_bytes}])")
        offset += size_bytes

    if "DataField" in field_entries:
        lines.append("")
        lines.append(f"    def get_data(self):")
        lines.append(f"        return self.get_bytes({offset}, self.get_size() - {offset})\n")
        lines.append(f"    def set_data(self, unsigned char[::1] data):")
        lines.append(f"        self.set_bytes({offset}, data)")
        lines.append(f"        self._data_length = data.shape[0]")
        lines.append("")
        lines.append(f"    cpdef int get_size(self):")
        lines.append(f"        return self.ACTUAL_SIZE + self._data_length")

    else:
        lines.append("")
        lines.append(f"    cpdef int get_size(self):")
        lines.append(f"        return self.ACTUAL_SIZE")

    return "\n".join(lines) + "\n"


def main():
    base = Path(__file__).parent
    fields = load_module(base / "fields.py", "fields")
    packets = load_module(base / "packets.py", "packets")

    out_file = base / "packet_structs.pyx"
    with open(out_file, "w") as f:
        f.write("from packet_base cimport PacketBuffer\n\n")

        field_sizes = {
            name: value
            for name, value in vars(fields).items()
            if not name.startswith("__") and isinstance(value, list)
        }

        for name, layout in field_sizes.items():
            f.write(emit_struct(name, layout))
            f.write("\n")

        for packet_name, layout in packets.PACKETS.items():
            f.write(emit_composite(packet_name, layout, field_sizes))
            f.write("\n")


if __name__ == "__main__":
    main()
