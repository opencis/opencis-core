"""
Copyright (c) 2024, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

import pytest

from opencis.util.unaligned_bit_structure import (
    UnalignedBitStructure,
    ByteField,
    DynamicByteField,
)

from opencis.cxl.transport.transaction import (
    CxlIoMemWrPacket,
)


class DynamicByteStructure(UnalignedBitStructure):
    field1: int
    field2: int
    field3: int
    payload: int
    _fields = [
        ByteField("field1", 0, 0),  # 1 Byte
        ByteField("field2", 1, 2),  # 2 Bytes
        ByteField("field3", 3, 5),  # 3 Bytes
        DynamicByteField("payload", 6, 1),
    ]


def test_basic_dbf():
    pckt = bytes([35, 25, 85, 90, 15, 100, 200, 210, 95])
    DBS = DynamicByteStructure()
    DBS.reset(pckt)
    assert DBS.field1 == 0x23
    assert DBS.field2 == 0x5519
    assert DBS.field3 == 0x640F5A
    assert DBS.payload == 0x5FD2C8
    assert len(DBS) == len(pckt)

    pckt2 = bytes([1, 1, 1, 1, 1, 1, 2, 3])
    DBS.reset(pckt2)
    assert DBS.field3 == 0x10101
    assert DBS.payload == 0x302
    assert len(DBS) == len(pckt2)

    pckt3 = bytes([1, 1, 1, 1, 1, 1, 8, 16, 24, 32, 110, 251])
    DBS.reset(pckt3)
    assert DBS.field3 == 0x10101
    assert DBS.payload == 0xFB6E20181008
    assert len(DBS) == len(pckt3)


class DisallowedDyBStruct(UnalignedBitStructure):
    field1: int
    field2: int
    field3: int
    payload: int
    _fields = [
        ByteField("field1", 0, 0),  # 1 Byte
        ByteField("field2", 1, 2),  # 2 Bytes
        ByteField("field3", 3, 5),  # 3 Bytes
        DynamicByteField("payload", 6, 2),
        DynamicByteField("payload2", 8, 4),
    ]


class DisallowedDyBStruct2(UnalignedBitStructure):
    field1: int
    field2: int
    field3: int
    payload: int
    _fields = [
        ByteField("field1", 0, 0),  # 1 Byte
        ByteField("field2", 1, 2),  # 2 Bytes
        DynamicByteField("payload", 3, 2),
        ByteField("field3", 5, 8),  # 4 Bytes
    ]


def test_unpleasant_dbf_failure():
    # pylint: disable=unused-variable
    with pytest.raises(Exception) as exc_info:
        DBS_Bad = DisallowedDyBStruct()
    assert (
        exc_info.value.args[0]
        == "The current implementation does not allow for more than one dynamic byte field."
    )

    with pytest.raises(Exception) as exc_info:
        DBS_Bad2 = DisallowedDyBStruct2()
    assert (
        exc_info.value.args[0][-68:]
        == "DynamicByteFields must be the last field in their respective packets"
    )


def test_io_mem_wr():
    addr = 0x0
    data = 0xDEADBEEF
    packet = CxlIoMemWrPacket.create(addr, 4, data=data)
    assert packet.data == data
