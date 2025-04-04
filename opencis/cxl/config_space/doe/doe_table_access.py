"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from enum import IntEnum
from typing import Optional, TypedDict, List, cast

from opencis.util.logger import logger
from opencis.pci.component.doe_mailbox import (
    DoeMailboxProtocolBase,
    DoeObjectHeader,
    DoeMailboxContext,
)
from opencis.util.unaligned_bit_structure import (
    ShareableByteArray,
    UnalignedBitStructure,
    ByteField,
    StructureField,
)
from opencis.cxl.config_space.doe.cdat import CDAT_ENTRY, CdatHeader
from opencis.util.number_const import DWORD_BYTES

DOE_CXL_VENDOR_ID = 0x1E98
DOE_CXL_OBJECT_TYPE_TABLE_ACCESS = 0x02


class DOE_TABLE_ACCESS_REQUEST_CODE(IntEnum):
    READ_ENTRY = 0


class DOE_TABLE_TYPE(IntEnum):
    CDAT = 0


class DoeTableAccessRequest(UnalignedBitStructure):
    header: DoeObjectHeader
    table_access_request_code: int
    table_type: int
    entry_handle: int

    _fields = [
        StructureField("header", 0, 7, DoeObjectHeader),
        ByteField("table_access_request_code", 8, 8),
        ByteField("table_type", 9, 9),
        ByteField("entry_handle", 0xA, 0xB),
    ]


class DoeTableAccessResponseOptions(TypedDict):
    structure_size: int


class DoeTableAccessResponse(UnalignedBitStructure):
    header: DoeObjectHeader
    table_access_request_code: int
    table_type: int
    entry_handle: int
    structure: int

    def __init__(
        self,
        data: Optional[ShareableByteArray] = None,
        parent_name: Optional[str] = None,
        options: Optional[DoeTableAccessResponseOptions] = None,
    ):
        structure_size = 1
        if options:
            structure_size = options.get("structure_size", structure_size)

        self._fields = [
            StructureField("header", 0, 7, DoeObjectHeader),
            ByteField(
                "table_access_request_code",
                8,
                8,
                default=DOE_TABLE_ACCESS_REQUEST_CODE.READ_ENTRY,
            ),
            ByteField("table_type", 9, 9, default=DOE_TABLE_TYPE.CDAT),
            ByteField("entry_handle", 0xA, 0xB),
            ByteField("structure", 0xC, 0xC + structure_size - 1),
        ]

        super().__init__(data, parent_name)


class DoeTableAccessProtocol(DoeMailboxProtocolBase):
    vendor_id = DOE_CXL_VENDOR_ID
    data_object_type = DOE_CXL_OBJECT_TYPE_TABLE_ACCESS
    name = "DOE Table Access"
    req_dwords = 3

    def __init__(self, entries: List[CDAT_ENTRY]):
        self._entries = []

        # TODO: Calculate checksum
        cdat_header = CdatHeader()
        cdat_header.length = len(cdat_header)
        self._entries.append(cdat_header)
        for entry in entries:
            cdat_header.length += entry.length
            self._entries.append(entry)

    def process_request(self, mailbox_context: DoeMailboxContext) -> bool:
        logger.debug("[DOE] Processing DOE Table Access")
        if mailbox_context.write_mailbox_len != self.req_dwords:
            logger.warning(
                f"[DOE] Table Access: Invalid request size, " f"{mailbox_context.write_mailbox_len}"
            )
            return False

        request = DoeTableAccessRequest()
        request.reset(bytes(mailbox_context.write_mailbox)[0 : len(request)])

        request_code = request.table_access_request_code
        table_type = request.table_type
        entry_handle = request.entry_handle

        if request_code != DOE_TABLE_ACCESS_REQUEST_CODE.READ_ENTRY:
            logger.warning("[DOE] Table Access: Invalid request code, {request_code}")
            return False

        if table_type != DOE_TABLE_TYPE.CDAT:
            logger.warning("[DOE] Table Access: Invalid table type, {table_type}")
            return False

        if entry_handle >= len(self._entries):
            logger.warning("[DOE] Table Access: Invalid entry handle, {entry_handle}")
            return False

        entry = cast(UnalignedBitStructure, self._entries[entry_handle])
        structure_size = len(entry)

        options: DoeTableAccessResponseOptions = {"structure_size": structure_size}
        response = DoeTableAccessResponse(options=options)
        is_last_entry = entry_handle == len(self._entries) - 1
        response.entry_handle = 0xFFFF if is_last_entry else entry_handle + 1
        response.header.vendor_id = DOE_CXL_VENDOR_ID
        response.header.data_object_type = DOE_CXL_OBJECT_TYPE_TABLE_ACCESS
        response.header.length = len(response) // DWORD_BYTES
        response.structure = int(entry)

        mailbox_context.read_mailbox.copy_from(response)
        mailbox_context.read_mailbox_len = response.header.length

        logger.debug(f"[DOE] Table Access: Response Length (DWORD) = {response.header.length}")

        return True
