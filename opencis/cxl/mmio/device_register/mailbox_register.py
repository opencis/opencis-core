"""
 Copyright (c) 2024, Eeum, Inc.

 This software is licensed under the terms of the Revised BSD License.
 See LICENSE for details.
"""

from typing import TypedDict, Optional
from opencis.util.unaligned_bit_structure import (
    BitMaskedBitStructure,
    BitField,
    ByteField,
    StructureField,
    FIELD_ATTR,
    ShareableByteArray,
)
from opencis.cxl.features.mailbox import (
    CxlMailbox,
)


MIN_PAYLOAD_SIZE = 8  # 256
MAX_PAYLOAD_SIZE = 20  # 1MB

# =======================================================================
# TODO: Support setter and getter per each BitMaskedBitStructure to avoid
# overriding read_bytes and write_bytes manually
# =======================================================================


class MailboxRegisterOptions(TypedDict):
    cxl_mailbox: Optional[CxlMailbox]


class MailboxCapabilitiesRegister(BitMaskedBitStructure):
    payload_size: int
    mb_doorbell_interrupt_capable: int
    background_command_complete_interrupt_capable: int
    interrupt_message_number: int
    mailbox_ready_time: int
    type: int

    _fields = [
        BitField("payload_size", 0, 4, FIELD_ATTR.RO, MIN_PAYLOAD_SIZE),
        BitField("mb_doorbell_interrupt_capable", 5, 5, FIELD_ATTR.RO),
        BitField("background_command_complete_interrupt_capable", 6, 6, FIELD_ATTR.RO),
        BitField("interrupt_message_number", 7, 10, FIELD_ATTR.RO),
        BitField("mailbox_ready_time", 11, 18, FIELD_ATTR.RO),
        BitField("type", 19, 22, FIELD_ATTR.RO),
        BitField("reserved1", 23, 31, FIELD_ATTR.RESERVED),
    ]

    def __init__(
        self,
        data: Optional[ShareableByteArray] = None,
        parent_name: Optional[str] = None,
        options: Optional[MailboxRegisterOptions] = None,
    ):
        if not options:
            options = MailboxRegisterOptions()

        self.cxl_mailbox = options.get("cxl_mailbox")

        super().__init__(data, parent_name)

    def read_bytes(self, start_offset: int, end_offset: int) -> int:
        if self.cxl_mailbox:
            cap = self.cxl_mailbox.get_capabilities()
            self.write_fields_from_dict(cap)
        return super().read_bytes(start_offset, end_offset)


class MailboxControlRegister(BitMaskedBitStructure):
    doorbell: int
    mb_doorbell_interrupt: int
    background_command_complete_interrupt: int

    _fields = [
        BitField("doorbell", 0, 0, FIELD_ATTR.RW),
        BitField("mb_doorbell_interrupt", 1, 1, FIELD_ATTR.RW),
        BitField("background_command_complete_interrupt", 2, 2, FIELD_ATTR.RW),
        BitField("reserved1", 3, 31, FIELD_ATTR.RESERVED),
    ]

    def __init__(
        self,
        data: Optional[ShareableByteArray] = None,
        parent_name: Optional[str] = None,
        options: Optional[MailboxRegisterOptions] = None,
    ):
        if not options:
            options = MailboxRegisterOptions()

        self.cxl_mailbox = options.get("cxl_mailbox")

        super().__init__(data, parent_name)

    def read_bytes(self, start_offset: int, end_offset: int) -> int:
        if self.cxl_mailbox:
            control = self.cxl_mailbox.get_control()
            self.write_fields_from_dict(control)
        return super().read_bytes(start_offset, end_offset)

    def write_bytes(self, start_offset: int, end_offset: int, value: int):
        super().write_bytes(start_offset, end_offset, value)
        if self.cxl_mailbox:
            control = self.read_fields_to_dict()
            self.cxl_mailbox.set_control(control)


class MailboxCommandRegister(BitMaskedBitStructure):
    command_opcode: int
    payload_length: int

    _fields = [
        BitField("command_opcode", 0, 15, FIELD_ATTR.RW),
        BitField("payload_length", 16, 36, FIELD_ATTR.RW),
        BitField("reserved1", 37, 63, FIELD_ATTR.RESERVED),
    ]

    def __init__(
        self,
        data: Optional[ShareableByteArray] = None,
        parent_name: Optional[str] = None,
        options: Optional[MailboxRegisterOptions] = None,
    ):
        if not options:
            options = MailboxRegisterOptions()

        self.cxl_mailbox = options.get("cxl_mailbox")

        super().__init__(data, parent_name)

    def write_bytes(self, start_offset: int, end_offset: int, value: int):
        super().write_bytes(start_offset, end_offset, value)
        if self.cxl_mailbox:
            command = self.read_fields_to_dict()
            self.cxl_mailbox.set_command(command)

    def read_bytes(self, start_offset: int, end_offset: int) -> int:
        if self.cxl_mailbox:
            command = self.cxl_mailbox.command
            self.write_fields_from_dict(command)
        return super().read_bytes(start_offset, end_offset)


class MailboxStatusRegister(BitMaskedBitStructure):
    background_operation: int
    return_code: int
    vendor_specific_extended_status: int

    _fields = [
        BitField("background_operation", 0, 0, FIELD_ATTR.RO),
        BitField("reserved1", 1, 31, FIELD_ATTR.RESERVED),
        BitField("return_code", 32, 47, FIELD_ATTR.RO),
        BitField("vendor_specific_extended_status", 48, 63, FIELD_ATTR.RO),
    ]

    def __init__(
        self,
        data: Optional[ShareableByteArray] = None,
        parent_name: Optional[str] = None,
        options: Optional[MailboxRegisterOptions] = None,
    ):
        if not options:
            options = MailboxRegisterOptions()

        self.cxl_mailbox = options.get("cxl_mailbox")

        super().__init__(data, parent_name)

    def read_bytes(self, start_offset: int, end_offset: int) -> int:
        if self.cxl_mailbox:
            status = self.cxl_mailbox.status
            self.write_fields_from_dict(status)
        return super().read_bytes(start_offset, end_offset)


class MailboxBackgroundCommandStatusRegister(BitMaskedBitStructure):
    command_opcode: int
    percentage_complete: int
    return_code: int
    vendor_specific_extended_status: int

    _fields = [
        BitField("command_opcode", 0, 15, FIELD_ATTR.RO),
        BitField("percentage_complete", 16, 22, FIELD_ATTR.RO),
        BitField("reserved1", 23, 31, FIELD_ATTR.RESERVED),
        BitField("return_code", 32, 47, FIELD_ATTR.RO),
        BitField("vendor_specific_extended_status", 48, 63, FIELD_ATTR.RO),
    ]

    def __init__(
        self,
        data: Optional[ShareableByteArray] = None,
        parent_name: Optional[str] = None,
        options: Optional[MailboxRegisterOptions] = None,
    ):
        if not options:
            options = MailboxRegisterOptions()

        self.cxl_mailbox = options.get("cxl_mailbox")

        super().__init__(data, parent_name)

    def read_bytes(self, start_offset: int, end_offset: int) -> int:
        if self.cxl_mailbox:
            status = self.cxl_mailbox.background_command_status
            self.write_fields_from_dict(status)
        return super().read_bytes(start_offset, end_offset)


class MailboxCommandPayloadsRegisters(BitMaskedBitStructure):
    def __init__(
        self,
        data: Optional[ShareableByteArray] = None,
        parent_name: Optional[str] = None,
        options: Optional[MailboxRegisterOptions] = None,
    ):
        if not options:
            options = MailboxRegisterOptions()

        payload_size = MailboxCommandPayloadsRegisters.get_size_from_options(options)
        self._fields = [ByteField("payload", 0, payload_size - 1, attribute=FIELD_ATTR.RW)]

        self.cxl_mailbox = options.get("cxl_mailbox")

        super().__init__(data, parent_name)

    def read_bytes(self, start_offset: int, end_offset: int) -> int:
        if self.cxl_mailbox:
            value = self.cxl_mailbox.payloads.read_bytes(start_offset, end_offset)
            self._data.write_bytes(start_offset, end_offset, value)
        return super().read_bytes(start_offset, end_offset)

    def write_bytes(self, start_offset: int, end_offset: int, value: int):
        super().write_bytes(start_offset, end_offset, value)
        if self.cxl_mailbox:
            self.cxl_mailbox.payloads.write_bytes(start_offset, end_offset, value)

    @staticmethod
    def get_size_from_options(
        options: Optional[MailboxRegisterOptions] = None,
    ):
        if not options:
            options = MailboxRegisterOptions()

        cxl_mailbox = options.get("cxl_mailbox")
        payload_size = MIN_PAYLOAD_SIZE
        if cxl_mailbox:
            capabilities = cxl_mailbox.get_capabilities()
            payload_size = capabilities["payload_size"]

        return 1 << payload_size


class MailboxRegister(BitMaskedBitStructure):
    capabilities: MailboxCapabilitiesRegister
    control: MailboxControlRegister
    command: MailboxCommandRegister
    status: MailboxStatusRegister
    background_command_status: MailboxBackgroundCommandStatusRegister
    command_payload: MailboxCommandPayloadsRegisters

    def __init__(
        self,
        data: Optional[ShareableByteArray] = None,
        parent_name: Optional[str] = None,
        options: Optional[MailboxRegisterOptions] = None,
    ):
        if not options:
            options = MailboxRegisterOptions()

        size = MailboxRegister.get_size_from_options(options)

        self._fields = [
            StructureField(
                "capabilities",
                0x00,
                0x03,
                MailboxCapabilitiesRegister,
                options=options,
            ),
            StructureField(
                "control",
                0x04,
                0x07,
                MailboxControlRegister,
                options=options,
            ),
            StructureField(
                "command",
                0x08,
                0x0F,
                MailboxCommandRegister,
                options=options,
            ),
            StructureField(
                "status",
                0x10,
                0x17,
                MailboxStatusRegister,
                options=options,
            ),
            StructureField(
                "background_command_status",
                0x18,
                0x1F,
                MailboxBackgroundCommandStatusRegister,
                options=options,
            ),
            StructureField(
                "command_payload",
                0x20,
                size - 1,
                MailboxCommandPayloadsRegisters,
                options=options,
            ),
        ]

        super().__init__(data, parent_name)

    @staticmethod
    def get_size_from_options(
        options: Optional[MailboxRegisterOptions] = None,
    ):
        if not options:
            options = MailboxRegisterOptions()

        payload_size = MailboxCommandPayloadsRegisters.get_size_from_options(options)
        return 0x20 + payload_size
