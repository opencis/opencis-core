from pathlib import Path
import importlib.util
import sys


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

    total_bits = sum(w for _, _, w in layout)
    total_bytes = (total_bits + 7) // 8

    return (
        f"cdef class {name}(PacketBuffer):\n"
        f"{field_defs}"
        f"    @classmethod\n"
        f"    def get_size(cls):\n"
        f"        return {total_bytes}\n\n"
        f"    def __len__(self):\n"
        f"        return self.get_size()\n\n"
        f"    def __bytes__(self):\n"
        f"        return self.to_bytes()\n"
    )


def emit_composite(packet_name, layout, field_sizes):
    lines = [f"cdef class Raw{packet_name}(PacketBuffer):"]
    offset = 0
    field_entries = []

    for entry in layout:
        if isinstance(entry, tuple):
            field_entries.append(entry)
        elif entry == ("DataField", "data"):
            field_entries.append(("DataField", "data"))
        else:
            field_entries.append((entry, entry.lower()))

    total_bits = 0
    for entry in field_entries:
        struct, _ = entry
        if struct == "DataField":
            continue
        total_bits += sum(w for _, _, w in field_sizes[struct])
    total_bytes = (total_bits + 7) // 8

    lines.append(f"    ACTUAL_SIZE = {total_bytes}")
    lines.append(f"    cdef int _data_length")

    for struct, varname in field_entries:
        if struct == "DataField":
            continue
        lines.append(f"    cdef {struct} {varname}_")

    lines.append("")

    for struct, varname in field_entries:
        if struct == "DataField":
            continue
        lines.append(f"    @property")
        lines.append(f"    def {varname}(self):")
        lines.append(f"        return self.{varname}_")
        lines.append("")

    lines.append("    def __cinit__(self, unsigned char[::1] buf = None):")
    lines.append("        if buf is None:")
    lines.append(f"            raw_buf = bytearray(200)")
    lines.append("            buf = raw_buf")
    lines.append(f"        self.ACTUAL_SIZE = {total_bytes}")
    lines.append("        self.buf = buf")

    offset = 0
    for struct, varname in field_entries:
        if struct == "DataField":
            continue
        size_bits = sum(w for _, _, w in field_sizes[struct])
        size_bytes = (size_bits + 7) // 8
        lines.append(f"        self.{varname}_ = {struct}(buf[{offset}:{offset + size_bytes}])")
        offset += size_bytes

    if ("DataField", "data") in field_entries:
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

    lines.append("")
    lines.append("    def __bytes__(self):")
    lines.append("        return self.to_bytes()")
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
