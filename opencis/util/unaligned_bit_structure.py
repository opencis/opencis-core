"""
 Copyright (c) 2024, Eeum, Inc.

 This software is licensed under the terms of the Revised BSD License.
 See LICENSE for details.
"""

from typing import (
    List,
    Dict,
    Type,
    Union,
    Optional,
    cast,
    TypedDict,
)
from dataclasses import dataclass, field
from enum import Enum, auto
import inspect

from opencis.util.logger import logger

# pylint: disable=redefined-outer-name, protected-access


class FIELD_ATTR(Enum):
    RO = auto()
    ROS = auto()
    RW = auto()
    RWS = auto()
    RWO = auto()
    RWL = auto()
    RW1CS = auto()
    HW_INIT = auto()
    RW1C = auto()
    RESERVED = auto()


@dataclass
class BitField:
    name: str
    start: int
    end: int
    attribute: FIELD_ATTR = FIELD_ATTR.RW
    default: int = 0

    def is_readonly(self):
        return self.attribute in (FIELD_ATTR.RO, FIELD_ATTR.HW_INIT)


ByteFieldType = Type[Union[int, bytearray]]


@dataclass
class ByteField:
    name: str
    start: int
    end: int
    type: ByteFieldType = field(default=int)
    attribute: FIELD_ATTR = FIELD_ATTR.RW
    default: int = 0
    mask: Optional[int] = None

    def is_readonly(self):
        return self.attribute in (FIELD_ATTR.RO, FIELD_ATTR.HW_INIT)


@dataclass
class DynamicByteFieldInstance:
    name: str
    start: int
    length: int
    type: ByteFieldType = field(default=int)
    attribute: FIELD_ATTR = FIELD_ATTR.RW
    default: int = 0
    mask: Optional[int] = None

    def is_read_only(self):
        return self.attribute in (FIELD_ATTR.RO, FIELD_ATTR.HW_INIT)


@dataclass
class DynamicByteField:
    """
    Dynamic byte fields may have different sizes depending on which
    packet they currently belong to. In order to prevent nasty side
    effects, we have to create a "spawner" class that initializes
    a new dynamic byte field every time a dynamically-sized packet
    is created.
    """

    name: str
    start: int
    length: int
    type: ByteFieldType = field(default=int)
    attribute: FIELD_ATTR = FIELD_ATTR.RW
    default: int = 0
    mask: Optional[int] = None

    def is_read_only(self):
        return self.attribute in (FIELD_ATTR.RO, FIELD_ATTR.HW_INIT)

    def spawn(self):
        return DynamicByteFieldInstance(
            self.name,
            self.start,
            self.length,
            self.type,
            self.attribute,
            self.default,
            self.mask,
        )


@dataclass
class StructureField:
    name: str
    start: int
    end: int
    structure: Type["UnalignedBitStructure"]
    mask: Optional[int] = None
    options: Optional[Dict] = None
    default: int = 0


DataField = Union[BitField, ByteField, DynamicByteField, StructureField]
BITS_IN_BYTE = 8


@dataclass
class BitMaskEntry:
    name: str
    value: Union[int, "UnalignedBitStructure"]
    offset: int = 0


class ShareableByteArray:
    _data: bytearray

    def __init__(
        self,
        size: int = 0,
        data_bytes: Optional[Union[bytearray, "ShareableByteArray"]] = None,
        offset: Optional[int] = None,
        data_type: Optional[str] = "data",
    ):
        if not data_bytes:
            self._data = bytearray(size)
        elif isinstance(data_bytes, bytearray):
            self._data = data_bytes
        elif isinstance(data_bytes, ShareableByteArray):
            self._data = data_bytes._data
        else:
            raise Exception("Unexpected type for data_bytes")

        # TODO: ensure size / offset are valid
        self.size = size
        self.offset = offset if offset else 0
        self.data_type = data_type

    def __getitem__(self, index: int) -> int:
        # TODO: handle OOB
        offset = self.offset + index
        data = self._data[offset]
        # logger.debug(f"[Buffer] RD[{self.type}], offset = {offset:03x}, data = {data:x}")
        return data

    def __setitem__(self, index: int, value: int):
        # TODO: hanlde OOB
        # print(f"len={len(self._data)}, offset={self.offset}, index={index}")
        offset = self.offset + index
        self._data[offset] = value
        # logger.debug(f"[Buffer] WR[{self.type}], offset = {offset:03x}, data = {value:x}")

    def __str__(self) -> str:
        data = self.__bytes__()
        return " ".join([format(b, "02x") for b in data])

    def __len__(self) -> int:
        return self.size

    def __int__(self) -> int:
        return int.from_bytes(self._data[self.offset : self.offset + self.size], "little")

    def __bytes__(self) -> bytes:
        return bytes(self._data[self.offset : self.offset + self.size])

    def reset(self, data: Optional[bytearray] = None):
        start = self.offset
        end = self.offset + self.size
        if not data:
            self._data[start:end] = bytearray(self.size)
        else:
            # appears to be out of bounds, but this works in Python
            self._data[start:end] = data
            self.size = len(data)

    def resize(self, new_size: int):
        if new_size < 0:
            raise Exception("Cannot resize ShareableByteArray to negative length!")
        # extension
        if new_size > self.size:
            self._data.extend(bytearray([0] * (new_size - self.size)))
        # truncation
        else:
            self._data = self._data[:new_size]
        self.size = new_size

    def get_hex_dump(self, line_length: int = 16):
        hex_string = " ".join(
            f"{byte:02x}" for byte in self._data[self.offset : self.offset + self.size]
        )
        return "\n".join(
            hex_string[i : i + line_length * 3] for i in range(0, len(hex_string), line_length * 3)
        )

    def write_bytes(self, start_offset: int, end_offset: int, value: int):
        # NOTE: Assume little-endian byte order
        length = end_offset - start_offset + 1
        start = start_offset + self.offset
        end = end_offset + self.offset
        val_bytes = value.to_bytes(length, "little")
        self._data[start : end + 1] = val_bytes

    def read_bytes(self, start_offset: int, end_offset: int) -> int:
        # NOTE: Assume little-endian byte order
        start = start_offset + self.offset
        end = end_offset + self.offset
        return int.from_bytes(self._data[start : end + 1], "little")

    def write_bits(self, offset, width, value):
        """
        Writes the given value to the byte array starting at the specified bit offset
        and spanning the specified bit width, allowing for unaligned writes.
        """

        byte_offset = offset // 8
        bit_offset = offset % 8
        end_offset = offset + width - 1
        byte_end_offset = end_offset // 8
        bit_end_offset = end_offset % 8

        # Handle the case where the write fits entirely within a single byte
        if byte_offset == byte_end_offset:
            mask = ((1 << width) - 1) << bit_offset
            self[byte_offset] &= ~mask
            self[byte_offset] |= (value << bit_offset) & mask
            return

        # Handle the case where the write spans multiple bytes
        mask1 = ((1 << (8 - bit_offset)) - 1) << bit_offset
        mask2 = (1 << (bit_end_offset + 1)) - 1

        self[byte_offset] &= ~mask1
        self[byte_offset] |= (value << bit_offset) & mask1
        value = value >> (8 - bit_offset)

        for i in range(byte_offset + 1, byte_end_offset):
            self[i] = value & 0xFF
            value = value >> 8

        self[byte_end_offset] &= ~mask2
        self[byte_end_offset] |= value & mask2

    def read_bits(self, offset, width):
        """
        Reads a value from the byte array starting at the specified bit offset
        and spanning the specified bit width, allowing for unaligned reads.
        """
        byte_offset = offset // 8
        bit_offset = offset % 8
        end_offset = offset + width - 1
        byte_end_offset = end_offset // 8
        bit_end_offset = end_offset % 8

        # Handle the case where the read fits entirely within a single byte
        if byte_offset == byte_end_offset:
            mask = ((1 << width) - 1) << bit_offset
            return (self[byte_offset] & mask) >> bit_offset

        # Handle the case where the read spans multiple bytes
        mask1 = ((1 << (BITS_IN_BYTE - bit_offset)) - 1) << bit_offset
        mask2 = (1 << (bit_end_offset + 1)) - 1

        result = self[byte_end_offset] & mask2

        for i in range(byte_end_offset - 1, byte_offset, -1):
            result = result << BITS_IN_BYTE
            result |= self[i]

        result = result << (BITS_IN_BYTE - bit_offset)
        result |= (self[byte_offset] & mask1) >> bit_offset
        return result

    def copy_from(self, data: "ShareableByteArray", dest_offset: int = 0):
        for byte in bytes(data):
            self[dest_offset] = byte
            dest_offset += 1

    def create_shared(
        self, size: Optional[int] = None, offset: Optional[int] = None
    ) -> "ShareableByteArray":
        if size is None:
            size = self.size
        if offset is None:
            offset = 0

        return ShareableByteArray(size, self, offset, self.data_type)


class UnalignedBitStructure:
    _fields: List[DataField] = []
    _verbose: bool = False
    _dynamic_field: Optional[DynamicByteField] = None

    def __init__(
        self,
        data: Optional[ShareableByteArray] = None,
        parent_name: Optional[str] = None,
    ):
        self._parent_name = parent_name
        self._field_names = []
        self._total_bits = 0
        self._class_name = type(self).__name__

        if self._fields:
            self._check_if_fields_are_valid()

        if data:
            self._data = data
            if self._fields and self._last_offset >= len(self._data):
                raise Exception(
                    f"{self._class_name}: "
                    + f"The last DataField.end({self._last_offset:x}) is greater "
                    + f"than the data size({len(self._data):x})"
                )
        elif self._fields:
            size = UnalignedBitStructure.get_size(self._fields)
            if self._verbose:
                logger.debug(f"[Structure] Creating a new data buffer, size: 0x{size:x}")
            self._data = ShareableByteArray(size)
            if self._verbose:
                logger.debug(
                    f"[Structure] {self._class_name}: Creating Byte Array of size {size:x}"
                )
        else:
            raise Exception(f"{self._class_name}: self._fields must not be an empty array")

        for f in self._fields:
            if isinstance(f, BitField):
                self._add_bit_field(f)
            elif isinstance(f, ByteField):
                self._add_byte_field(f)
            elif isinstance(f, DynamicByteField):
                self._add_dynamic_byte_field(f.spawn())
            elif isinstance(f, StructureField):
                self._add_structured_field(f)

    def _check_if_fields_are_valid(self):
        fields = self._fields
        bit_fields = 0
        byte_fields = 0
        dynamic_byte_fields = 0
        structure_fields = 0

        for f in fields:
            if isinstance(f, BitField):
                bit_fields += 1
            elif isinstance(f, ByteField):
                byte_fields += 1
            elif isinstance(f, DynamicByteField):
                dynamic_byte_fields += 1
            elif isinstance(f, StructureField):
                structure_fields += 1
            else:
                raise Exception(f"{self._class_name}: Unexpected field type {type(f).__name__})")

        if bit_fields > 0 and (byte_fields > 0 or structure_fields > 0):
            raise Exception(
                f"{self._class_name}: A BitField cannot mixed with a ByteField or a StructureField"
            )

        if dynamic_byte_fields > 1:
            raise Exception(
                "The current implementation does not allow for more than one dynamic byte field."
            )

        last_offset = -1
        for f_idx, f in enumerate(fields):
            if f.start != last_offset + 1:
                raise Exception(
                    f"'{self._class_name}.{f.name}': "
                    "DataField.start isn't aligned to the previous field"
                )
            if isinstance(f, DynamicByteField) is False and f.end < f.start:
                raise Exception(
                    f"'{self._class_name}.{f.name}': "
                    "DataField.end cannot be less than DataField.start"
                )
            if isinstance(f, DynamicByteField) and f.length < 0:
                raise Exception(
                    f"'{self._class_name}.{f.name}': "
                    "A byte field with negative length is nonsensical"
                )
            if isinstance(f, DynamicByteField) and f_idx != len(fields) - 1:
                raise Exception(
                    f"'{self._class_name}.{f.name}: "
                    "DynamicByteFields must be the last field in their respective packets"
                )

            if not isinstance(f, DynamicByteField):
                last_offset = f.end
            else:
                last_offset += f.length

        if bit_fields > 0 and (last_offset + 1) % 8 != 0:
            raise Exception(
                f"{self._class_name}: The last DataField.end should be aligned to byte boundary"
            )

        self._has_bit_fields = bit_fields > 0

        if self._has_bit_fields:
            self._last_offset = last_offset / BITS_IN_BYTE
        else:
            self._last_offset = last_offset

    @staticmethod
    def ascii_str_to_int(ascii_str: str, length: int) -> int:
        ascii_bytes = ascii_str.encode("ascii")
        if len(ascii_bytes) < length:
            ascii_bytes = ascii_bytes + bytes(length - len(ascii_bytes))
        return int.from_bytes(ascii_bytes, byteorder="little")

    @classmethod
    def get_size(cls, fields: Optional[List[DataField]] = None) -> int:
        """
        It is usually a bad idea to call this method on a dynamically-sized
        packet class, since the returned size will __not__ include the size
        of the dynamically-sized field (which is by default 0)
        """
        if not fields:
            fields = cls._fields
        last_field = fields[-1]
        if isinstance(last_field, BitField):
            # NOTE: We may have to throw an error instead
            return (last_field.end + 1) // BITS_IN_BYTE
        if isinstance(last_field, (ByteField, StructureField)):
            return last_field.end + 1
        if isinstance(last_field, DynamicByteField):
            return last_field.start + last_field.length
        raise Exception(f"Unexpected field type {type(last_field).__name__}")

    @classmethod
    def make_quiet(cls):
        cls._verbose = False

    @staticmethod
    def get_size_from_options(options: Optional[TypedDict]) -> int:
        # pylint: disable=unused-argument
        return 0

    # This must be followed by packet.system_header.payload_length = len(packet)
    def set_dynamic_field_length(self, new_len: int):
        if self._dynamic_field is None:
            return
        old_length = self._dynamic_field.length
        self._dynamic_field.length = new_len
        self._data.resize(len(self) + new_len - old_length)

    def _add_field_name(self, name: str):
        if name in self._field_names:
            raise Exception(f"field {name} has been already added")
        self._field_names.append(name)

    def _add_bit_field(self, field: BitField):
        width = field.end - field.start + 1
        self._add_field_name(field.name)

        def make_setter(start, width):
            def setter(self, value: int):
                self._data.write_bits(start, width, value)

            return setter

        def make_getter(start, width):
            def getter(self) -> int:
                return self._data.read_bits(start, width)

            return getter

        if field.default > 0 and self._verbose:
            logger.debug(
                f"[Structure] {self._class_name}: Default {field.name} = {field.default:x}"
            )

        self._data.write_bits(field.start, width, field.default)

        setattr(
            self.__class__,
            field.name,
            property(
                make_getter(field.start, width),
                make_setter(field.start, width),
            ),
        )

    def _add_byte_field(self: "UnalignedBitStructure", field: ByteField):
        self._add_field_name(field.name)

        # TODO: Support bytearray type

        def make_setter(start_offset: int, end_offset: int):
            def setter(self: "UnalignedBitStructure", value: int):
                self._data.write_bytes(start_offset, end_offset, value)

            return setter

        def make_getter(start_offset: int, end_offset: int):
            def getter(self: "UnalignedBitStructure") -> int:
                return self._data.read_bytes(start_offset, end_offset)

            return getter

        if field.default > 0:
            self._data.write_bytes(field.start, field.end, field.default)

        setattr(
            self.__class__,
            field.name,
            property(make_getter(field.start, field.end), make_setter(field.start, field.end)),
        )

    def _add_dynamic_byte_field(self: "UnalignedBitStructure", field: DynamicByteFieldInstance):
        self._add_field_name(field.name)
        if self._dynamic_field is not None:
            raise Exception(
                f"'{self._class_name}' instance already "
                f"contains a dynamic field: {self._dynamic_field.name}"
            )
        self._dynamic_field = field

        def make_setter(field: DynamicByteFieldInstance):
            def setter(self: "UnalignedBitStructure", value: int):
                self._data.write_bytes(field.start, field.start + field.length - 1, value)

            return setter

        def make_getter(field: DynamicByteFieldInstance):
            def getter(self: "UnalignedBitStructure") -> int:
                return self._data.read_bytes(field.start, field.start + field.length - 1)

            return getter

        if field.default > 0:
            self._data.write_bytes(field.start, field.start + field.length, field.default)

        setattr(
            self.__class__,
            field.name,
            property(make_getter(field), make_setter(field)),
        )

    def _add_structured_field(self: "UnalignedBitStructure", field: StructureField):
        self._add_field_name(field.name)
        offset = field.start + self._data.offset
        size = field.end - field.start + 1
        data = ShareableByteArray(size, self._data, offset)
        name = field.name
        if self._parent_name:
            name = f"{self._parent_name}.{name}"

        if self._verbose:
            logger.debug(f"[Structure] Creating structure {name}, offset= 0x{offset:x}")
        if field.options:
            if "options" not in inspect.signature(field.structure).parameters:
                raise Exception(
                    f'The constructor of structure "{name}" did not define "options" parameter'
                )
            struct = field.structure(data, name, field.options)
        else:
            struct = field.structure(data, name)

        if field.default > 0:
            struct._data.write_bytes(0, field.end - field.start, field.default)

        setattr(self, field.name, struct)

    def write_bytes(self, start_offset: int, end_offset: int, value: int):
        self._data.write_bytes(start_offset, end_offset, value)

    def read_bytes(self, start_offset: int, end_offset: int) -> int:
        return self._data.read_bytes(start_offset, end_offset)

    def _write_bits(self, offset: int, width: int, value: int):
        self._data.write_bits(offset, width, value)

    def _read_bits(self, offset: int, width: int):
        return self._data.read_bits(offset, width)

    def write_fields_from_dict(self, data: Dict):
        for key, value in data.items():
            setattr(self, key, value)

    def read_fields_to_dict(self) -> Dict:
        data = {}
        for field in self._fields:
            if not isinstance(field, (BitField, ByteField)):
                continue
            if field.attribute == FIELD_ATTR.RESERVED:
                continue
            data[field.name] = getattr(self, field.name)
        return data

    def __str__(self) -> str:
        return str(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def __int__(self) -> int:
        return int(self._data)

    def __bytes__(self) -> bytes:
        return bytes(self._data)

    def reset(self, data: Optional[Union[bytearray, bytes]] = None):
        if data is None:
            self._data.reset(data)
            return

        if isinstance(data, bytes):
            data = bytearray(data)

        if self._dynamic_field is None:
            self._data.reset(data)
        else:
            old_size: int = len(self._data)
            self._data.reset(data)
            self._dynamic_field.length += len(data) - old_size

    def get_pretty_string(self, indent: int = 0):
        indent_str = " " * indent
        string = ""
        for field in self._fields:
            if isinstance(field, BitField):
                string += f"{indent_str}{field.name}: {hex(getattr(self, field.name))}\n"
            elif isinstance(field, ByteField):
                string += f"{indent_str}{field.name}: {hex(getattr(self, field.name))}\n"
            elif isinstance(field, StructureField):
                string += f"{indent_str}{field.name}:\n"
                string += getattr(self, field.name).get_pretty_string(indent + 2)
            elif isinstance(field, DynamicByteFieldInstance):
                string += f"{indent_str}{field.name}: <-- {hex(getattr(self, field.name))} -->\n"
        return string

    def get_hex_dump(self, line_length: int = 16):
        return self._data.get_hex_dump(line_length)


class BitMaskedBitStructure(UnalignedBitStructure):
    def __init__(
        self,
        data: Optional[ShareableByteArray] = None,
        parent_name: Optional[str] = None,
    ):
        self.initialized = False
        super().__init__(data, parent_name)

        self._bitmask_bytes = ShareableByteArray(len(self), data_type="mask")

        if self._has_bit_fields:
            self._create_bit_field_masks()
        else:
            for field in self._fields:
                if isinstance(field, ByteField):
                    self._create_byte_field_mask(field)
                elif isinstance(field, StructureField):
                    self._create_structure_field_mask(field)
                else:
                    raise Exception(f"Unexpected BitField Type {type(field).__name__}")

        self.initialized = True

    def _create_bit_field_masks(self):
        bitmask = 0
        for field in self._fields:
            width = field.end - field.start + 1
            if not field.is_readonly():
                bitmask |= ((1 << width) - 1) << field.start
        self._bitmask_bytes.write_bytes(0, len(self) - 1, bitmask)

    def _create_byte_field_mask(self, field: ByteField):
        bitmask = 0
        bitmask_bytes = len(self._bitmask_bytes)
        if field.mask is not None:
            bitmask = field.mask

        elif not field.is_readonly():
            bitmask = (1 << (field.end - field.start + 1) * BITS_IN_BYTE) - 1

        if field.start >= len(self._bitmask_bytes):
            raise Exception(
                f"{self._class_name}.{field.name}: start({field.start:x}) "
                f"is greater than bitmask size({bitmask_bytes:x})"
            )
        if field.end >= len(self._bitmask_bytes):
            raise Exception(
                f"{self._class_name}.{field.name}: end({field.end:x}) "
                f"is greater than bitmask size({bitmask_bytes:x})"
            )

        self._bitmask_bytes.write_bytes(field.start, field.end, bitmask)

    def _create_structure_field_mask(self, field: StructureField):
        struct = getattr(self, field.name)
        if field.mask is not None:
            struct._bitmask_bytes.write_bytes(0, len(struct) - 1, field.mask)
            self._bitmask_bytes.write_bytes(field.start, field.end, field.mask)
        else:
            self._bitmask_bytes.copy_from(struct._bitmask_bytes, field.start)

    def write_bytes(self, start_offset: int, end_offset: int, value: int):
        mask = self._bitmask_bytes.read_bytes(start_offset, end_offset)
        current_value = self._data.read_bytes(start_offset, end_offset)
        value = (current_value & ~mask) | (value & mask)

        structure_field = self._get_structure_field(start_offset)
        if structure_field:
            struct = cast("BitMaskedBitStructure", getattr(self, structure_field.name))
            new_start_offset = start_offset - structure_field.start
            new_end_offset = end_offset - structure_field.start
            struct.write_bytes(new_start_offset, new_end_offset, value)
            return

        self._data.write_bytes(start_offset, end_offset, value)
        # size = end_offset - start_offset + 1
        # logger.debug(
        #     f"[WR] ADDR: 0x{start_offset:04x}, SIZE: {size}, DATA: 0x{value:08x}"
        # )
        self._print_bytes(start_offset, end_offset, False)

    def read_bytes(self, start_offset: int, end_offset: int) -> int:
        value = self._data.read_bytes(start_offset, end_offset)

        structure_field = self._get_structure_field(start_offset)
        if structure_field:
            struct = cast("BitMaskedBitStructure", getattr(self, structure_field.name))
            value = struct.read_bytes(
                start_offset - structure_field.start, end_offset - structure_field.start
            )
            return value

        # size = end_offset - start_offset + 1
        # logger.debug(
        #     f"[RD] ADDR: 0x{start_offset:04x}, SIZE: {size}, DATA: 0x{value:08x}"
        # )

        self._print_bytes(start_offset, end_offset, True)
        return self._data.read_bytes(start_offset, end_offset)

    def _get_structure_field(self, offset: int) -> Optional[StructureField]:
        if self._has_bit_fields:
            return None

        selected_field = None
        for field in self._fields:
            if isinstance(field, DynamicByteFieldInstance):
                continue
            if field.start <= offset <= field.end:
                selected_field = field
                break

        if not selected_field:
            return None

        if isinstance(selected_field, ByteField):
            return None

        return selected_field

    # TODO: When a byte field is greater than 64-bit, support printing access
    # to the partial range. This is helpful when printing a large byte field
    def _print_bytes(self, start_offset: int, end_offset: int, read=False):
        prefix = f"{self._parent_name}." if self._parent_name else ""
        if read:
            prefix = "[RD] " + prefix
        else:
            prefix = "[WR] " + prefix

        if self._has_bit_fields:
            value = int(self)
            message = prefix
            if prefix[-1] == ".":
                message = prefix[:-1]
            value_str = format(value, f"0{(end_offset - start_offset + 1)*2}x")
            logger.debug(f"{message}[{start_offset:x}:{end_offset:x}]: 0x{value_str}")
            for field in self._fields:
                if field.attribute == FIELD_ATTR.RESERVED:
                    continue
                bit_width = field.end - field.start + 1
                leading_zeros = (field.end - field.start + 4) // 4
                value = self._data.read_bits(field.start, bit_width)
                value_str = format(value, f"0{leading_zeros}x")
                mask = self._bitmask_bytes.read_bits(field.start, bit_width)
                mask_str = format(mask, f"0{leading_zeros}x")
                message = f"{prefix}{field.name}: 0x{value_str} [MASK: 0x{mask_str}]"
                logger.debug(message)

        else:
            selected_fields = []
            for field in self._fields:
                if field.start <= start_offset and end_offset <= field.end:
                    selected_fields.append(field)
                elif start_offset <= field.start and field.end <= end_offset:
                    selected_fields.append(field)
            for field in selected_fields:
                # if isinstance(field, ByteField):
                if field.start <= start_offset and end_offset <= field.end:
                    byte_offset_start = start_offset - field.start
                    byte_offset_end = end_offset - field.start
                    field_range = f"[{byte_offset_start:x}:{byte_offset_end:x}]"
                    leading_zeros = (end_offset - start_offset + 1) * 2
                    value = self._data.read_bytes(start_offset, end_offset)
                    value_str = format(value, f"0{leading_zeros}x")
                    mask = self._bitmask_bytes.read_bytes(start_offset, end_offset)
                    mask_str = format(mask, f"0{leading_zeros}x")
                    message = (
                        f"{prefix}{field.name}{field_range}: 0x{value_str} [MASK: 0x{mask_str}]"
                    )
                    logger.debug(message)
                else:
                    field_range = ""
                    leading_zeros = (field.end - field.start + 1) * 2
                    value = self._data.read_bytes(field.start, field.end)
                    value_str = format(value, f"0{leading_zeros}x")
                    mask = self._bitmask_bytes.read_bytes(field.start, field.end)
                    mask_str = format(mask, f"0{leading_zeros}x")
                    message = (
                        f"{prefix}{field.name}{field_range}: 0x{value_str} [MASK: 0x{mask_str}]"
                    )
                    logger.debug(message)
            # else:
            #     raise Exception("Only ByteField is expected")

    def get_byte_and_bit_field_string(
        self, name: str, value: int, mask: int, indent: int, leading_zeros: int
    ) -> str:
        indent_str = " " * indent
        value_str = format(value, f"0{leading_zeros}x")
        mask_str = format(mask, f"0{leading_zeros}x")
        string = ""
        if len(value_str) > 16:
            string += f"{indent_str}{name}:"
            new_indent_str = ""
            for offset in range(0, len(value_str), 16):
                value_seg = value_str[offset : offset + 16]
                mask_seg = mask_str[offset : offset + 16]
                string += f"{new_indent_str} 0x{value_seg} [MASK: 0x{mask_seg}]\n"
                new_indent_str = indent_str + " " * (len(name) + 1)
        else:
            string += f"{indent_str}{name}: 0x{value_str} [MASK: 0x{mask_str}]\n"
        return string

    def get_pretty_string(self, indent: int = 0):
        string = ""
        for field in self._fields:
            if isinstance(field, BitField):
                if field.attribute == FIELD_ATTR.RESERVED:
                    continue
                bit_width = field.end - field.start + 1
                leading_zeros = (field.end - field.start + 4) // 4
                value = self._data.read_bits(field.start, bit_width)
                mask = self._bitmask_bytes.read_bits(field.start, bit_width)
                string = BitMaskedBitStructure.get_byte_and_bit_field_string(
                    self, field.name, value, mask, indent, leading_zeros=leading_zeros
                )
            elif isinstance(field, ByteField):
                if field.attribute == FIELD_ATTR.RESERVED:
                    continue
                leading_zeros = (field.end - field.start + 1) * 2
                value = self._data.read_bytes(field.start, field.end)
                mask = self._bitmask_bytes.read_bytes(field.start, field.end)
                string += BitMaskedBitStructure.get_byte_and_bit_field_string(
                    self, field.name, value, mask, indent, leading_zeros
                )
            elif isinstance(field, StructureField):
                indent_str = " " * indent
                offset = self._data.offset + field.start
                string += f"{indent_str}{field.name} [OFFSET: 0x{offset:03x}]:\n"
                string += getattr(self, field.name).get_pretty_string(indent + 2)
        return string
