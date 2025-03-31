"""
Copyright (c) 2024, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

import pytest

from opencis.util.unaligned_bit_structure import (
    ShareableByteArray,
    UnalignedBitStructure,
    BitField,
    ByteField,
    StructureField,
)


class BitFieldStructure(UnalignedBitStructure):
    field1: int
    field2: int
    field3: int
    field4: int
    field5: int
    field6: int
    field7: int
    _fields = [
        BitField("field1", 0, 0),  # 1 Bit
        BitField("field2", 1, 2),  # 2 Bits
        BitField("field3", 3, 5),  # 3 Bits
        BitField("field4", 6, 9),  # 4 Bits spans across byte boundary
        BitField("field5", 10, 30),  # 21 Bits spans across 3 bytes
        BitField("field6", 31, 70),  # 40 Bits spans across 6 bytes
        BitField("field7", 71, 71),  # 1 Bit
    ]


class ByteFieldStructure(UnalignedBitStructure):
    field1: int
    field2: int
    field3: int
    field4: int
    _fields = [
        ByteField("field1", 0, 0),  # 1 Byte
        ByteField("field2", 1, 2),  # 2 Bytes
        ByteField("field3", 3, 5),  # 3 Bytes
        ByteField("field4", 6, 9),  # 4 Bytes
    ]


class StructureFieldStructure(UnalignedBitStructure):
    bits: BitFieldStructure
    bytes: ByteFieldStructure
    _fields = [
        StructureField("bits", 0, 8, BitFieldStructure),
        StructureField("bytes", 9, 18, ByteFieldStructure),
    ]


class LiterallyUnalignedBitStructure(UnalignedBitStructure):
    field1: int
    field2: int
    field3: int
    field4: int
    _fields = [
        ByteField("field1", 0, 0),  # 1 Byte
        ByteField("field2", 1, 2),  # 2 Bytes
        ByteField("field3", 2, 5),  # 4 Bytes (unaligned!!)
        ByteField("field4", 6, 9),  # 4 Bytes
    ]


class LiterallyUnalignedBytes(UnalignedBitStructure):
    field1: int
    field2: int
    field3: int
    field4: int
    _fields = [
        BitField("field1", 0, 1),  # 2 bits
        BitField("field2", 2, 5),  # 4 bits
    ]


def test_shareable_bytearray():
    data_array = bytearray([0xDE, 0xAD, 0xBE, 0xEF, 0x10, 0x15, 0x20, 0x25, 0xBE, 0xDB, 0xED, 0xFF])
    shared = ShareableByteArray(len(data_array), data_array)

    shared_deadbeef = shared.create_shared(4, 0)
    shared_random = shared.create_shared(8, 4)
    shared_copy = shared.create_shared()

    assert bytes(shared_deadbeef) == bytearray([0xDE, 0xAD, 0xBE, 0xEF])
    assert bytes(shared_random) == bytearray([0x10, 0x15, 0x20, 0x25, 0xBE, 0xDB, 0xED, 0xFF])
    assert bytes(shared_copy) == data_array

    assert shared_deadbeef.get_hex_dump(line_length=4) == "de ad be ef"
    assert shared_random.get_hex_dump(line_length=4) == "10 15 20 25 \nbe db ed ff"

    shared.resize(10)

    assert bytes(shared) == bytearray([0xDE, 0xAD, 0xBE, 0xEF, 0x10, 0x15, 0x20, 0x25, 0xBE, 0xDB])
    assert bytes(shared_deadbeef) == bytearray([0xDE, 0xAD, 0xBE, 0xEF])
    assert bytes(shared_copy) != bytes(shared)


def test_literally_unaligned_bit_structure():
    # pylint: disable=unused-variable
    with pytest.raises(
        Exception, match=r".*DataField.start isn't aligned to the previous field$"
    ) as exc_info:
        unaligned = LiterallyUnalignedBitStructure()

    with pytest.raises(
        Exception, match=r".*The last DataField.end should be aligned to byte boundary$"
    ) as exc_info:
        unaligned_pt2 = LiterallyUnalignedBytes()


def test_individual_bit_fields():
    struct = BitFieldStructure()
    assert len(struct) == 9

    struct.field1 = 1
    assert str(struct) == "01 00 00 00 00 00 00 00 00"

    struct.reset()
    struct.field2 = 3
    assert str(struct) == "06 00 00 00 00 00 00 00 00"

    struct.reset()
    struct.field3 = 7
    assert str(struct) == "38 00 00 00 00 00 00 00 00"

    struct.reset()
    struct.field4 = 0xF
    assert str(struct) == "c0 03 00 00 00 00 00 00 00"

    struct.reset()
    struct.field5 = 0b111111111111111111111
    assert str(struct) == "00 fc ff 7f 00 00 00 00 00"

    struct.reset()
    struct.field6 = 0xFFFFFFFFFF
    assert str(struct) == "00 00 00 80 ff ff ff ff 7f"

    struct.reset()
    struct.field7 = 1
    assert str(struct) == "00 00 00 00 00 00 00 00 80"


def test_accumulated_bit_fields():
    struct = BitFieldStructure()
    assert len(struct) == 9

    struct.field1 = 1
    struct.field2 = 3
    assert str(struct) == "07 00 00 00 00 00 00 00 00"
    struct.field3 = 7
    assert str(struct) == "3f 00 00 00 00 00 00 00 00"
    struct.field4 = 0xF
    assert str(struct) == "ff 03 00 00 00 00 00 00 00"
    struct.field5 = 0b111111111111111111111
    assert str(struct) == "ff ff ff 7f 00 00 00 00 00"
    struct.field6 = 0xFFFFFFFFFF
    assert str(struct) == "ff ff ff ff ff ff ff ff 7f"
    struct.field7 = 1
    assert str(struct) == "ff ff ff ff ff ff ff ff ff"


def test_bit_field_attributes():
    struct = BitFieldStructure()
    assert hasattr(struct, "field1")
    assert hasattr(struct, "field2")
    assert hasattr(struct, "field3")
    assert hasattr(struct, "field4")
    assert hasattr(struct, "field5")
    assert hasattr(struct, "field6")
    assert hasattr(struct, "field7")


def test_bit_field_getters():
    struct = BitFieldStructure()
    struct.reset(bytearray([0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF]))
    assert struct.field1 == 1
    assert struct.field2 == 3
    assert struct.field3 == 7
    assert struct.field4 == 0xF
    assert struct.field5 == 0b111111111111111111111
    assert struct.field6 == 0xFFFFFFFFFF
    assert struct.field7 == 1


def test_individual_byte_fields():
    struct = ByteFieldStructure()
    assert len(struct) == 10

    struct.field1 = 0x12
    assert str(struct) == "12 00 00 00 00 00 00 00 00 00"

    struct.reset()
    struct.field2 = 0x3456
    assert str(struct) == "00 56 34 00 00 00 00 00 00 00"

    struct.reset()
    struct.field3 = 0x789ABC
    assert str(struct) == "00 00 00 bc 9a 78 00 00 00 00"

    struct.reset()
    struct.field4 = 0xDEF12345
    assert str(struct) == "00 00 00 00 00 00 45 23 f1 de"


def test_accumulated_byte_fields():
    struct = ByteFieldStructure()
    assert len(struct) == 10

    struct.field1 = 0x12
    assert str(struct) == "12 00 00 00 00 00 00 00 00 00"
    struct.field2 = 0x3456
    assert str(struct) == "12 56 34 00 00 00 00 00 00 00"
    struct.field3 = 0x789ABC
    assert str(struct) == "12 56 34 bc 9a 78 00 00 00 00"
    struct.field4 = 0xDEF12345
    assert str(struct) == "12 56 34 bc 9a 78 45 23 f1 de"


def test_byte_field_attributes():
    struct = ByteFieldStructure()
    assert hasattr(struct, "field1")
    assert hasattr(struct, "field2")
    assert hasattr(struct, "field3")
    assert hasattr(struct, "field4")


def test_byte_field_getters():
    struct = ByteFieldStructure()
    data_str = "12 56 34 bc 9a 78 45 23 f1 de"
    data = bytearray([int(byte_str, 16) for byte_str in data_str.split(" ")])
    struct.reset(data)
    assert struct.field1 == 0x12
    assert struct.field2 == 0x3456
    assert struct.field3 == 0x789ABC
    assert struct.field4 == 0xDEF12345


def test_individual_structure_field():
    struct = StructureFieldStructure()
    assert len(struct) == 19

    struct.bits.field1 = 1
    assert str(struct) == "01 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00"

    struct.reset()
    struct.bits.field2 = 3
    assert str(struct) == "06 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00"

    struct.reset()
    struct.bits.field3 = 7
    assert str(struct) == "38 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00"

    struct.reset()
    struct.bits.field4 = 0xF
    assert str(struct) == "c0 03 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00"

    struct.reset()
    struct.bits.field5 = 0b111111111111111111111
    assert str(struct) == "00 fc ff 7f 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00"

    struct.reset()
    struct.bits.field6 = 0xFFFFFFFFFF
    assert str(struct) == "00 00 00 80 ff ff ff ff 7f 00 00 00 00 00 00 00 00 00 00"

    struct.reset()
    struct.bits.field7 = 1
    assert str(struct) == "00 00 00 00 00 00 00 00 80 00 00 00 00 00 00 00 00 00 00"

    struct.reset()
    struct.bytes.field1 = 0x12
    assert str(struct) == "00 00 00 00 00 00 00 00 00 12 00 00 00 00 00 00 00 00 00"

    struct.reset()
    struct.bytes.field2 = 0x3456
    assert str(struct) == "00 00 00 00 00 00 00 00 00 00 56 34 00 00 00 00 00 00 00"

    struct.reset()
    struct.bytes.field3 = 0x789ABC
    assert str(struct) == "00 00 00 00 00 00 00 00 00 00 00 00 bc 9a 78 00 00 00 00"

    struct.reset()
    struct.bytes.field4 = 0xDEF12345
    assert str(struct) == "00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 45 23 f1 de"
