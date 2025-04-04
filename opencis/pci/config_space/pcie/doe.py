"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from typing import Optional, TypedDict, List
from enum import IntEnum
from opencis.util.unaligned_bit_structure import (
    BitMaskedBitStructure,
    ShareableByteArray,
    BitField,
    ByteField,
    StructureField,
    DataField,
    FIELD_ATTR,
)
from opencis.pci.component.doe_mailbox import (
    DoeMailboxComponent,
    DoeMailboxProtocolBase,
)


class DoeExtendedCapabilityHeaderOptions(TypedDict):
    next_capability_offset: Optional[int]


class DoeCapabilityHeader(BitMaskedBitStructure):
    def __init__(
        self,
        data: Optional[ShareableByteArray] = None,
        parent_name: Optional[str] = None,
        options: Optional[DoeExtendedCapabilityHeaderOptions] = None,
    ):
        next_capability_offset = 0
        if options:
            next_capability_offset = options.get("next_capability_offset", 0)

        self._fields = [
            BitField("capability_id", 0, 15, FIELD_ATTR.RO, 0x002E),
            BitField("capability_version", 16, 19, FIELD_ATTR.RO, 0x1),
            BitField("next_capability_offset", 20, 31, FIELD_ATTR.RO, next_capability_offset),
        ]

        super().__init__(data, parent_name)


class DoeCapability(BitMaskedBitStructure):
    _fields = [
        BitField("doe_interrupt_support", 0, 0, FIELD_ATTR.HW_INIT),
        BitField("doe_interrupt_message_number", 1, 11, FIELD_ATTR.RO),
        BitField("reserved1", 12, 31, FIELD_ATTR.RESERVED),
    ]


class DoeControl(BitMaskedBitStructure):
    doe_abort: int
    doe_interrupt_enable: int
    doe_go: int

    _fields = [
        BitField("doe_abort", 0, 0, FIELD_ATTR.RW),
        BitField("doe_interrupt_enable", 1, 1, FIELD_ATTR.RW),
        BitField("reserved1", 2, 30, FIELD_ATTR.RESERVED),
        BitField("doe_go", 31, 31, FIELD_ATTR.RW),
    ]


class DoeStatus(BitMaskedBitStructure):
    doe_busy: int
    doe_interrupt_status: int
    doe_error: int
    data_object_ready: int

    _fields = [
        BitField("doe_busy", 0, 0, FIELD_ATTR.RO),
        BitField("doe_interrupt_status", 1, 1, FIELD_ATTR.RW1C),
        BitField("doe_error", 2, 2, FIELD_ATTR.RO),
        BitField("reserved1", 3, 30, FIELD_ATTR.RESERVED),
        BitField("data_object_ready", 31, 31, FIELD_ATTR.RO),
    ]


class DOE_REGISTER_OFFSET(IntEnum):
    HEADER = 0x00
    CAPABILITY = 0x04
    CONTROL = 0x08
    STATUS = 0x0C
    WRITE_DATA_MAILBOX = 0x10
    READ_DATA_MAILBOX = 0x14
    RESERVED_START = 0x18
    RESERVED_END = 0x1F


class DoeExtendedCapabilityOptions(TypedDict):
    header: Optional[DoeExtendedCapabilityHeaderOptions]
    protocols: Optional[List[DoeMailboxProtocolBase]]


class DoeExtendedCapability(BitMaskedBitStructure):
    capability_header: DoeCapabilityHeader
    doe_capability: DoeCapability
    doe_control: DoeControl
    doe_status: DoeStatus

    def __init__(
        self,
        data: Optional[ShareableByteArray] = None,
        parent_name: Optional[str] = None,
        options: Optional[DoeExtendedCapabilityOptions] = None,
    ):
        header_options = None
        protocols: List[DoeMailboxProtocolBase] = []
        if options:
            header_options = options.get("header")
            protocols = options.get("protocols")

        self._mailbox_component = DoeMailboxComponent(protocols=protocols)

        self._fields = [
            StructureField(
                "capability_header",
                DOE_REGISTER_OFFSET.HEADER,
                DOE_REGISTER_OFFSET.HEADER + 3,
                DoeCapabilityHeader,
                options=header_options,
            ),
            StructureField(
                "doe_capability",
                DOE_REGISTER_OFFSET.CAPABILITY,
                DOE_REGISTER_OFFSET.CAPABILITY + 3,
                DoeCapability,
            ),
            StructureField(
                "doe_control",
                DOE_REGISTER_OFFSET.CONTROL,
                DOE_REGISTER_OFFSET.CONTROL + 3,
                DoeControl,
            ),
            StructureField(
                "doe_status",
                DOE_REGISTER_OFFSET.STATUS,
                DOE_REGISTER_OFFSET.STATUS + 3,
                DoeStatus,
            ),
            ByteField(
                "doe_write_data_mailbox",
                DOE_REGISTER_OFFSET.WRITE_DATA_MAILBOX,
                DOE_REGISTER_OFFSET.WRITE_DATA_MAILBOX + 3,
                attribute=FIELD_ATTR.RW,
            ),
            ByteField(
                "doe_read_data_mailbox",
                DOE_REGISTER_OFFSET.READ_DATA_MAILBOX,
                DOE_REGISTER_OFFSET.READ_DATA_MAILBOX + 3,
                attribute=FIELD_ATTR.RW,
            ),
            ByteField(
                "reserved1",
                DOE_REGISTER_OFFSET.RESERVED_START,
                DOE_REGISTER_OFFSET.RESERVED_END,
                attribute=FIELD_ATTR.RESERVED,
            ),
        ]

        super().__init__(data, parent_name)

    @staticmethod
    def get_size(fields: List[DataField] | None = None) -> int:
        return DOE_REGISTER_OFFSET.RESERVED_END + 1

    def write_bytes(self, start_offset: int, end_offset: int, value: int):
        match start_offset:
            case DOE_REGISTER_OFFSET.CONTROL:
                super().write_bytes(start_offset, end_offset, value)
                if self.doe_control.doe_abort:
                    self._mailbox_component.abort()
                    self.doe_control.doe_abort = 0
                elif self.doe_control.doe_go:
                    self._mailbox_component.go()
                    self.doe_control.doe_go = 0
            case DOE_REGISTER_OFFSET.STATUS:
                if self.doe_status.doe_interrupt_status == 1:
                    self.doe_status.doe_interrupt_status = 0
            case DOE_REGISTER_OFFSET.WRITE_DATA_MAILBOX:
                self._mailbox_component.write_next_data(value)
            case DOE_REGISTER_OFFSET.READ_DATA_MAILBOX:
                self._mailbox_component.request_next_data()

    def read_bytes(self, start_offset: int, end_offset: int) -> int:
        if start_offset >= DOE_REGISTER_OFFSET.HEADER and end_offset < DOE_REGISTER_OFFSET.STATUS:
            return super().read_bytes(start_offset, end_offset)

        if (
            start_offset >= DOE_REGISTER_OFFSET.STATUS
            and end_offset < DOE_REGISTER_OFFSET.WRITE_DATA_MAILBOX
        ):
            status = self._mailbox_component.get_status()
            self.doe_status.write_fields_from_dict(status)
            return super().read_bytes(start_offset, end_offset)

        if (
            start_offset >= DOE_REGISTER_OFFSET.WRITE_DATA_MAILBOX
            and end_offset < DOE_REGISTER_OFFSET.READ_DATA_MAILBOX
        ):
            return 0

        if start_offset >= DOE_REGISTER_OFFSET.READ_DATA_MAILBOX:
            return self._mailbox_component.read_next_data()

        return 0
