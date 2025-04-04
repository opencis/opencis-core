"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from opencis.pci.config_space.pcie.doe import DoeStatus
from opencis.cxl.config_space.doe.doe import (
    DoeExtendedCapability,
    CxlDoeExtendedCapability,
)
from opencis.cxl.config_space.doe.doe_table_access import (
    DoeTableAccessRequest,
    DoeTableAccessResponse,
    DoeTableAccessResponseOptions,
    DOE_CXL_VENDOR_ID,
    DOE_CXL_OBJECT_TYPE_TABLE_ACCESS,
)
from opencis.cxl.config_space.doe.cdat import CdatHeader
from opencis.pci.config_space.pcie.doe import (
    DOE_REGISTER_OFFSET,
)
from opencis.util.number_const import DWORD_BYTES


def read_doe_status(doe: DoeExtendedCapability) -> DoeStatus:
    doe.read_bytes(DOE_REGISTER_OFFSET.STATUS, DOE_REGISTER_OFFSET.STATUS + DWORD_BYTES - 1)
    return doe.doe_status


def test_doe_table_access():
    # pylint: disable=duplicate-code
    doe = CxlDoeExtendedCapability()

    request = DoeTableAccessRequest()
    request.header.vendor_id = DOE_CXL_VENDOR_ID
    request.header.data_object_type = DOE_CXL_OBJECT_TYPE_TABLE_ACCESS
    request.header.length = len(request) // DWORD_BYTES

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

    options: DoeTableAccessResponseOptions = {"structure_size": len(CdatHeader())}
    response = DoeTableAccessResponse(options=options)

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
    assert response.header.vendor_id == DOE_CXL_VENDOR_ID
    assert response.header.data_object_type == DOE_CXL_OBJECT_TYPE_TABLE_ACCESS
    assert response.header.length == len(response) // DWORD_BYTES
    assert response.entry_handle == 0xFFFF
