"""
 Copyright (c) 2024, Eeum, Inc.

 This software is licensed under the terms of the Revised BSD License.
 See LICENSE for details.
"""

from enum import IntEnum
from typing import List

from opencis.cxl.features.mailbox import (
    CxlMailboxContext,
    CxlMailboxCommandBase,
    MAILBOX_RETURN_CODE,
)
from opencis.cxl.features.event_manager import EventManager
from opencis.util.unaligned_bit_structure import (
    UnalignedBitStructure,
    ByteField,
)


class EVENT_LOG_TYPE(IntEnum):
    INFORMATIONAL_EVENT_LOG = 0x00
    WARNING_EVENT_LOG = 0x01
    FAILURE_EVENT_LOG = 0x02
    FATAL_EVENT_LOG = 0x03
    DYNAMIC_CAPACITY_EVENT_LOG = 0x04
    RESERVED = 0x05


EVENT_RECORD_SIZE = 0x80


class CommonEventRecord(UnalignedBitStructure):
    _fields = [
        ByteField("event_record_identify", 0x00, 0x0F),
        ByteField("event_record_length", 0x10, 0x11),
        ByteField("event_record_flags", 0x11, 0x13),
        ByteField("event_record_handle", 0x14, 0x15),
        ByteField("related_event_record_handle", 0x16, 0x17),
        ByteField("event_record_timestamp", 0x18, 0x1F),
        ByteField("maintenance_operation_class", 0x20, 0x20),
        ByteField("reserved1", 0x21, 0x2F),
    ]


#
#   GetEventRecordsInput command (Opcode 0100h)
#


class GetEventRecordsInput(UnalignedBitStructure):
    event_log: int

    _fields = [ByteField("event_log", 0x00, 0x00)]


class GetEventRecordsOutput(UnalignedBitStructure):
    flags: int
    overflow_error_count: int
    first_overflow_error_timestamp: int
    last_overflow_error_timestamp: int
    event_record_count: int

    def __init__(self, event_records: List[bytes]):
        self._fields = [
            ByteField("flags", 0x00, 0x00),
            ByteField("reserved1", 0x01, 0x01),
            ByteField("overflow_error_count", 0x02, 0x03),
            ByteField("first_overflow_error_timestamp", 0x04, 0x0B),
            ByteField("last_overflow_error_timestamp", 0x0C, 0x13),
            ByteField("event_record_count", 0x14, 0x15, default=len(event_records)),
            ByteField("reserved2", 0x16, 0x1F),
        ]
        if len(event_records) > 0:
            # TODO: CCI: Implement returning event records
            pass
        super().__init__()

    @staticmethod
    def get_size(event_records: List[bytes]):
        # pylint: disable=arguments-renamed
        return 0x20 + EVENT_RECORD_SIZE * len(event_records)


class GetEventRecords(CxlMailboxCommandBase):
    def __init__(self, event_manager: EventManager):
        super().__init__(0x0100)
        self.event_manager = event_manager

    def process(self, context: CxlMailboxContext) -> bool:
        payload_length = context.command["payload_length"]

        if payload_length != GetEventRecordsInput.get_size():
            context.status["return_code"] = MAILBOX_RETURN_CODE.INVALID_INPUT
            return True

        input_buffer = context.payloads.create_shared(payload_length)
        input = GetEventRecordsInput(input_buffer)

        if input.event_log >= EVENT_LOG_TYPE.RESERVED:
            context.status["return_code"] = MAILBOX_RETURN_CODE.INVALID_INPUT
            return True

        # TODO: Implement getting event records
        event_records = []
        output_bytes = bytes(GetEventRecordsOutput(event_records))
        context.payloads.copy_from(output_bytes)
        context.command["payload_length"] = len(output_bytes)
        return True


#
#   ClearEventRecords command (Opcode 0101h)
#

EVENT_RECORD_HANDLE_SIZE = 0x02


class ClearEventRecordsInputCommon(UnalignedBitStructure):
    event_log: int
    clear_event_flags: int
    number_of_event_record_handles: int

    _fields = [
        ByteField("event_log", 0x00, 0x00),
        ByteField("clear_event_flags", 0x01, 0x01),
        ByteField("number_of_event_record_handles", 0x02, 0x02),
        ByteField("reserved1", 0x03, 0x03),
    ]


class ClearEventRecords(CxlMailboxCommandBase):
    def __init__(self, event_manager: EventManager):
        super().__init__(0x0101)
        self.event_manager = event_manager

    def process(self, context: CxlMailboxContext) -> bool:
        payload_length = context.command["payload_length"]

        if payload_length < ClearEventRecordsInputCommon.get_size():
            context.status["return_code"] = MAILBOX_RETURN_CODE.INVALID_INPUT
            return True

        input_buffer = context.payloads.create_shared(payload_length)
        input_common = ClearEventRecordsInputCommon(input_buffer)

        if input_common.clear_event_flags == 0x00:
            event_record_handle_count = input_common.number_of_event_record_handles
            expected_total_input_size = (
                len(input_common) + EVENT_RECORD_HANDLE_SIZE * event_record_handle_count
            )
            if expected_total_input_size != payload_length:
                context.status["return_code"] = MAILBOX_RETURN_CODE.INVALID_INPUT
                return True

            # TODO: Clear event records based on requested handle
            # self.event_log_manager.clear(type, handles)
        else:
            pass
            # TODO: Clear all event records
            # self.event_log_manager.clear(type)

        context.status["return_code"] = MAILBOX_RETURN_CODE.SUCCESS
        context.command["payload_length"] = 0
        return True


class INTERRUPT_MODE(IntEnum):
    NO_INTERRUPTS = 0b00
    MSI_OR_MSIX = 0b01
    FW_INTERRUPT = 0b10
    RESERVED = 0b11


#
#   GetEventInterruptPolicy command (Opcode 0102h)
#


class EventInterruptPolicyVersion1(UnalignedBitStructure):
    informational_event_log_interrupt_settings: int
    warning_event_log_interrupt_settings: int
    failure_event_log_interrupt_settings: int
    fatal_event_log_interrupt_settings: int

    _fields = [
        ByteField("informational_event_log_interrupt_settings", 0x00, 0x00),
        ByteField("warning_event_log_interrupt_settings", 0x01, 0x01),
        ByteField("failure_event_log_interrupt_settings", 0x02, 0x02),
        ByteField("fatal_event_log_interrupt_settings", 0x03, 0x03),
    ]


class EventInterruptPolicyVersion2(UnalignedBitStructure):
    informational_event_log_interrupt_settings: int
    warning_event_log_interrupt_settings: int
    failure_event_log_interrupt_settings: int
    fatal_event_log_interrupt_settings: int
    dynamic_capacity_event_log_interrupt_settings: int

    _fields = [
        ByteField("informational_event_log_interrupt_settings", 0x00, 0x00),
        ByteField("warning_event_log_interrupt_settings", 0x01, 0x01),
        ByteField("failure_event_log_interrupt_settings", 0x02, 0x02),
        ByteField("fatal_event_log_interrupt_settings", 0x03, 0x03),
        ByteField("dynamic_capacity_event_log_interrupt_settings", 0x04, 0x04),
    ]


class GetEventInterruptPolicy(CxlMailboxCommandBase):
    def __init__(self, event_manager: EventManager):
        super().__init__(0x0102)
        self.event_manager = event_manager

    def process(self, context: CxlMailboxContext) -> bool:
        payload_length = context.command["payload_length"]

        if payload_length != 0:
            context.status["return_code"] = MAILBOX_RETURN_CODE.INVALID_INPUT
            return True

        output_length = EventInterruptPolicyVersion2.get_size()
        output_buffer = context.payloads.create_shared(output_length)
        output = EventInterruptPolicyVersion2(output_buffer)

        interrupt_policy = self.event_manager.get_interrupt_policy()
        output.write_fields_from_dict(interrupt_policy)
        context.command["payload_length"] = output_length
        return True


#
#   SetEventInterruptPolicy command (Opcode 0103h)
#


class SetEventInterruptPolicy(CxlMailboxCommandBase):
    def __init__(self, event_manager: EventManager):
        super().__init__(0x0103)
        self.event_manager = event_manager

    def process(self, context: CxlMailboxContext) -> bool:
        payload_length = context.command["payload_length"]

        supported_policies: List[UnalignedBitStructure] = [
            EventInterruptPolicyVersion1,
            EventInterruptPolicyVersion2,
        ]

        policy_class = None
        for policy in supported_policies:
            if payload_length == policy.get_size():
                policy_class = policy

        if not policy_class:
            context.status["return_code"] = MAILBOX_RETURN_CODE.INVALID_INPUT
            return True

        input_buffer = context.payloads.create_shared(payload_length)
        input: UnalignedBitStructure = policy_class(input_buffer)
        interrupt_policy = input.read_fields_to_dict()
        self.event_manager.set_interrupt_policy(interrupt_policy)
        context.command["payload_length"] = 0
        return True
