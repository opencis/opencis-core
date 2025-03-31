"""
Copyright (c) 2024, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from enum import IntEnum, Enum, auto
from typing import List

from opencis.util.unaligned_bit_structure import (
    UnalignedBitStructure,
    ShareableByteArray,
    BitField,
    ByteField,
    StructureField,
)
from opencis.cxl.features.mailbox import CxlMailboxCommandBase


def uuid_str_to_int(uuid_str):
    raw_uuid = uuid_str.replace("-", "")
    splitted_uuid = [raw_uuid[i : i + 2] for i in range(0, len(raw_uuid), 2)]
    splitted_uuid.reverse()
    reversed_uuid = "".join(splitted_uuid)
    return int(reversed_uuid, 16)


class LOG_IDENTIFIER(IntEnum):
    COMMAND_EFFECTS_LOG = uuid_str_to_int("0da9c0b5-bf41-4b78-8f79-96b1623b3f17")
    VENDOR_DEBUG_LOG = uuid_str_to_int("5e1819d9-11a9-400c-811f-d60719403d86")
    COMPONENT_STATE_DUMP = uuid_str_to_int("b3fab4cf-01b6-4332-943e-5e9962f23567")


class CommandEffectsLogEntry(UnalignedBitStructure):
    opcode: int

    _fields = [
        BitField("opcode", 0x00, 0x0F),
        BitField("configuration_change_after_cold_reset", 0x10, 0x10),
        BitField("immediate_configuration_change", 0x11, 0x11),
        BitField("immediate_data_change", 0x12, 0x12),
        BitField("immediate_policy_change", 0x13, 0x13),
        BitField("immediate_log_change", 0x14, 0x14),
        BitField("security_state_change", 0x15, 0x15),
        BitField("background_operation", 0x16, 0x16),
        BitField("secondary_mailbox_supported", 0x17, 0x17),
        BitField("reserved1", 0x18, 0x1F),
    ]


class CommandEffectsLog(UnalignedBitStructure):
    def __init__(self, entries: List[CommandEffectsLogEntry]):
        self._fields = []
        entry_id = 1
        entry_size = CommandEffectsLogEntry.get_size()
        offset = 0
        for entry in entries:
            self._fields.append(
                StructureField(
                    f"command{entry_id}_entry",
                    offset,
                    offset + entry_size - 1,
                    CommandEffectsLogEntry,
                    default=int(entry),
                )
            )
            entry_id += 1
            offset += entry_size

        super().__init__()

    @staticmethod
    def get_size(fields, entries: List[CommandEffectsLogEntry] = None):
        return len(entries) * CommandEffectsLogEntry.get_size()


class SupportedLogEntry(UnalignedBitStructure):
    log_identifier: int
    log_size: int

    _fields = [
        ByteField("log_identifier", 0x00, 0x0F),
        ByteField("log_size", 0x10, 0x13),
    ]


class GET_LOG_STATUS(Enum):
    OK = auto()
    INVALID_LOG_ID = auto()
    INVALID_OFFSET_OR_LENGTH = auto()


class LogManager:
    def __init__(self):
        self.command_effects_log = None

    def set_command_effects_log(self, commands: List[CxlMailboxCommandBase]):
        cel_entries: List[CommandEffectsLogEntry] = []
        for command in commands:
            entry = CommandEffectsLogEntry()
            entry.opcode = command.get_opcode()
            cel_entries.append(entry)
        self.command_effects_log = CommandEffectsLog(entries=cel_entries)

    def get_logs(
        self, log_identifier: int, offset: int, buffer: ShareableByteArray
    ) -> GET_LOG_STATUS:
        if log_identifier != LOG_IDENTIFIER.COMMAND_EFFECTS_LOG:
            return GET_LOG_STATUS.INVALID_LOG_ID

        if offset + len(buffer) > len(self.command_effects_log):
            return GET_LOG_STATUS.INVALID_OFFSET_OR_LENGTH

        buffer.copy_from(bytes(self.command_effects_log)[offset:])

        return GET_LOG_STATUS.OK

    def get_supported_logs(self) -> List[SupportedLogEntry]:
        supported_logs = []
        # NOTE: Only command effects log is supported at the moment.
        if self.command_effects_log:
            cel_entry = SupportedLogEntry()
            cel_entry.log_identifier = LOG_IDENTIFIER.COMMAND_EFFECTS_LOG
            cel_entry.log_size = len(self.command_effects_log)
            supported_logs.append(cel_entry)
        return supported_logs
