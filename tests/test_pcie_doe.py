"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from opencis.pci.config_space.pcie.doe import (
    DoeExtendedCapability,
    DoeStatus,
    DOE_REGISTER_OFFSET,
)
from opencis.pci.component.doe_mailbox import (
    DoeDiscoveryRequest,
    DoeDiscoveryResponse,
)
from opencis.util.number_const import DWORD_BYTES


def read_doe_status(doe: DoeExtendedCapability) -> DoeStatus:
    doe.read_bytes(DOE_REGISTER_OFFSET.STATUS, DOE_REGISTER_OFFSET.STATUS + DWORD_BYTES - 1)
    return doe.doe_status


def test_doe_header_read():
    doe = DoeExtendedCapability()
    data = doe.read_bytes(DOE_REGISTER_OFFSET.HEADER, DOE_REGISTER_OFFSET.HEADER + DWORD_BYTES - 1)
    assert data == 0x0001002E


def test_doe_capability_read():
    doe = DoeExtendedCapability()
    data = doe.read_bytes(
        DOE_REGISTER_OFFSET.CAPABILITY, DOE_REGISTER_OFFSET.CAPABILITY + DWORD_BYTES - 1
    )
    assert data == 0x00000000


def test_doe_control_read():
    doe = DoeExtendedCapability()
    data = doe.read_bytes(
        DOE_REGISTER_OFFSET.CONTROL, DOE_REGISTER_OFFSET.CONTROL + DWORD_BYTES - 1
    )
    assert data == 0x00000000


def test_doe_status_read():
    doe = DoeExtendedCapability()
    data = doe.read_bytes(DOE_REGISTER_OFFSET.STATUS, DOE_REGISTER_OFFSET.STATUS + DWORD_BYTES - 1)
    assert data == 0x00000000


def test_doe_invalid_read_mailbox_write():
    doe = DoeExtendedCapability()
    doe.write_bytes(
        DOE_REGISTER_OFFSET.READ_DATA_MAILBOX,
        DOE_REGISTER_OFFSET.READ_DATA_MAILBOX + DWORD_BYTES - 1,
        0x00,
    )
    assert read_doe_status(doe).doe_error == 1
    doe.write_bytes(
        DOE_REGISTER_OFFSET.CONTROL,
        DOE_REGISTER_OFFSET.CONTROL + DWORD_BYTES - 1,
        0x00000001,
    )
    assert read_doe_status(doe).doe_error == 0


def test_doe_discovery():
    doe = DoeExtendedCapability()
    request = DoeDiscoveryRequest()
    request.header.vendor_id = 0x0001
    request.header.data_object_type = 0x00
    request.header.length = 3

    for dword_index in range(3):
        doe.write_bytes(
            DOE_REGISTER_OFFSET.WRITE_DATA_MAILBOX,
            DOE_REGISTER_OFFSET.WRITE_DATA_MAILBOX + DWORD_BYTES - 1,
            request.read_bytes(dword_index * DWORD_BYTES, (dword_index + 1) * DWORD_BYTES - 1),
        )

    doe.write_bytes(
        DOE_REGISTER_OFFSET.CONTROL,
        DOE_REGISTER_OFFSET.CONTROL + DWORD_BYTES - 1,
        0x80000000,
    )
    assert read_doe_status(doe).data_object_ready == 1

    response = DoeDiscoveryResponse()

    offset = 0
    while read_doe_status(doe).data_object_ready == 1:
        data = doe.read_bytes(
            DOE_REGISTER_OFFSET.READ_DATA_MAILBOX,
            DOE_REGISTER_OFFSET.READ_DATA_MAILBOX + DWORD_BYTES - 1,
        )
        response.write_bytes(offset, offset + DWORD_BYTES - 1, data)
        offset += DWORD_BYTES
        doe.write_bytes(
            DOE_REGISTER_OFFSET.READ_DATA_MAILBOX,
            DOE_REGISTER_OFFSET.READ_DATA_MAILBOX + DWORD_BYTES - 1,
            0,
        )
    assert response.header.vendor_id == 0x0001
    assert response.header.data_object_type == 0x00
    assert response.header.length == 3
    assert response.vendor_id == 0x0001
    assert response.data_object_type == 0x00
    assert response.next_index == 0


def test_doe_discovery_invalid_index():
    doe = DoeExtendedCapability()
    request = DoeDiscoveryRequest()
    request.header.vendor_id = 0x0001
    request.header.data_object_type = 0x00
    request.header.length = 3
    request.index = 1

    for dword_index in range(3):
        doe.write_bytes(
            DOE_REGISTER_OFFSET.WRITE_DATA_MAILBOX,
            DOE_REGISTER_OFFSET.WRITE_DATA_MAILBOX + DWORD_BYTES - 1,
            request.read_bytes(dword_index * DWORD_BYTES, (dword_index + 1) * DWORD_BYTES - 1),
        )

    doe.write_bytes(
        DOE_REGISTER_OFFSET.CONTROL,
        DOE_REGISTER_OFFSET.CONTROL + DWORD_BYTES - 1,
        0x80000000,
    )
    assert read_doe_status(doe).data_object_ready == 1

    response = DoeDiscoveryResponse()

    offset = 0
    while read_doe_status(doe).data_object_ready == 1:
        data = doe.read_bytes(
            DOE_REGISTER_OFFSET.READ_DATA_MAILBOX,
            DOE_REGISTER_OFFSET.READ_DATA_MAILBOX + DWORD_BYTES - 1,
        )
        response.write_bytes(offset, offset + DWORD_BYTES - 1, data)
        offset += DWORD_BYTES
        doe.write_bytes(
            DOE_REGISTER_OFFSET.READ_DATA_MAILBOX,
            DOE_REGISTER_OFFSET.READ_DATA_MAILBOX + DWORD_BYTES - 1,
            0,
        )
    assert response.header.vendor_id == 0x0001
    assert response.header.data_object_type == 0x00
    assert response.header.length == 3
    assert response.vendor_id == 0xFFFF
    assert response.data_object_type == 0xFF
    assert response.next_index == 0


def test_doe_discovery_invalid_request_object():
    doe = DoeExtendedCapability()
    request = DoeDiscoveryRequest()
    request.header.vendor_id = 0x0001
    request.header.data_object_type = 0x00
    request.header.length = 3
    request.index = 1

    for dword_index in range(2):
        doe.write_bytes(
            DOE_REGISTER_OFFSET.WRITE_DATA_MAILBOX,
            DOE_REGISTER_OFFSET.WRITE_DATA_MAILBOX + DWORD_BYTES - 1,
            request.read_bytes(dword_index * DWORD_BYTES, (dword_index + 1) * DWORD_BYTES - 1),
        )

    doe.write_bytes(
        DOE_REGISTER_OFFSET.CONTROL,
        DOE_REGISTER_OFFSET.CONTROL + DWORD_BYTES - 1,
        0x80000000,
    )
    assert read_doe_status(doe).data_object_ready == 0
