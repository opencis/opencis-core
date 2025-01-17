"""
 Copyright (c) 2024, Eeum, Inc.

 This software is licensed under the terms of the Revised BSD License.
 See LICENSE for details.
"""

from typing import List

from opencis.cxl.features.mailbox import (
    CxlMailboxContext,
    CxlMailboxCommandBase,
    MAILBOX_RETURN_CODE,
)
from opencis.util.unaligned_bit_structure import (
    ShareableByteArray,
    UnalignedBitStructure,
    ByteField,
    StructureField,
    FIELD_ATTR,
)
from opencis.cxl.features.log_manager import (
    GET_LOG_STATUS,
    SupportedLogEntry,
    LogManager,
)

#
#   GetEventRecordsInput command (Opcode 0400h)
#


class GetSupportedLogsOutput(UnalignedBitStructure):
    number_of_supported_log_entries: int

    def __init__(self, data: ShareableByteArray, entries: List[SupportedLogEntry]):
        self._fields = [
            ByteField("number_of_supported_log_entries", 0x00, 0x01, default=len(entries)),
            ByteField("reserved1", 0x02, 0x07, attribute=FIELD_ATTR.RESERVED),
        ]

        if entries:
            offset = 0x08
            entry_size = SupportedLogEntry.get_size()
            entry_index = 0
            for entry in entries:
                self._fields.append(
                    StructureField(
                        f"supported_log_entry{entry_index}",
                        offset,
                        offset + entry_size - 1,
                        SupportedLogEntry,
                        default=int(entry),
                    )
                )
                entry_index += 1
                offset += entry_size

        super().__init__(data)

    @staticmethod
    def get_size(entries: List[SupportedLogEntry]):
        # pylint: disable=arguments-renamed
        return 0x08 + len(entries) * SupportedLogEntry.get_size()


class GetSupportedLogs(CxlMailboxCommandBase):
    def __init__(self, log_manager: LogManager) -> None:
        super().__init__(0x0400)
        self.log_manager = log_manager

    def process(self, context: CxlMailboxContext) -> bool:
        payload_length = context.command["payload_length"]

        if payload_length != 0:
            context.status["return_code"] = MAILBOX_RETURN_CODE.INVALID_INPUT
            return True

        supported_logs = self.log_manager.get_supported_logs()
        output_length = GetSupportedLogsOutput.get_size(supported_logs)
        output_buffer = context.payloads.create_shared(output_length)
        GetSupportedLogsOutput(output_buffer, supported_logs)
        context.command["payload_length"] = output_length
        return True


#
#   GetEventRecordsInput command (Opcode 0401h)
#


class GetLogInput(UnalignedBitStructure):
    log_identifier: int
    offset: int
    length: int

    _fields = [
        ByteField("log_identifier", 0x00, 0x0F),
        ByteField("offset", 0x10, 0x13),
        ByteField("length", 0x14, 0x17),
    ]


class GetLog(CxlMailboxCommandBase):
    def __init__(self, log_manager: LogManager) -> None:
        super().__init__(0x0401)
        self.log_manager = log_manager

    def process(self, context: CxlMailboxContext) -> bool:
        payload_length = context.command["payload_length"]

        if payload_length != GetLogInput.get_size():
            context.status["return_code"] = MAILBOX_RETURN_CODE.INVALID_INPUT
            return True

        input_buffer = context.payloads.create_shared(payload_length)
        input = GetLogInput(input_buffer)

        # TODO: check if input.length is less than payloads size.
        output_length = input.length
        output_buffer = context.payloads.create_shared(output_length)

        status = self.log_manager.get_logs(input.log_identifier, input.offset, output_buffer)
        if status == GET_LOG_STATUS.INVALID_LOG_ID:
            context.status["return_code"] = MAILBOX_RETURN_CODE.INVALID_LOG
            return True
        if status == GET_LOG_STATUS.INVALID_OFFSET_OR_LENGTH:
            context.status["return_code"] = MAILBOX_RETURN_CODE.INVALID_INPUT
            return True

        context.command["payload_length"] = output_length
        return True
