"""
Copyright (c) 2024, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from typing import Dict, TypedDict, Optional
from opencis.util.unaligned_bit_structure import (
    BitMaskedBitStructure,
    BitField,
    ByteField,
    StructureField,
    FIELD_ATTR,
    ShareableByteArray,
)
from opencis.cxl.component.cxl_component import CxlDeviceComponent
from opencis.cxl.features.event_manager import EventStatus


class DeviceStatusRegistersOptions(TypedDict):
    cxl_device_component: CxlDeviceComponent


class EventStatusRegister(BitMaskedBitStructure):
    informational_event_log: int
    warning_event_log: int
    failure_event_log: int
    fatal_event_log: int
    dynamic_capacity_event_log: int

    _fields = [
        BitField("informational_event_log", 0, 0, FIELD_ATTR.RO),
        BitField("warning_event_log", 1, 1, FIELD_ATTR.RO),
        BitField("failure_event_log", 2, 2, FIELD_ATTR.RO),
        BitField("fatal_event_log", 3, 3, FIELD_ATTR.RO),
        BitField("dynamic_capacity_event_log", 4, 4, FIELD_ATTR.RO),
        BitField("reserved1", 5, 63, FIELD_ATTR.RESERVED),
    ]

    def __init__(
        self,
        data: Optional[ShareableByteArray] = None,
        parent_name: Optional[str] = None,
        options: Optional[DeviceStatusRegistersOptions] = None,
    ):
        if not options:
            raise Exception("options is required")

        self.event_manager = options["cxl_device_component"].get_event_manager()

        super().__init__(data, parent_name)

    def read_bytes(self, start_offset: int, end_offset: int) -> int:
        status: EventStatus = self.event_manager.get_status()
        self.write_fields_from_dict(status)
        return super().read_bytes(start_offset, end_offset)


class DeviceStatusRegisters(BitMaskedBitStructure):
    event_status: EventStatusRegister

    def __init__(
        self,
        data: Optional[ShareableByteArray] = None,
        parent_name: Optional[str] = None,
        options: Optional[DeviceStatusRegistersOptions] = None,
    ):
        if not options:
            raise Exception("options is required")

        self._fields = [
            StructureField("event_status", 0, 7, EventStatusRegister, options=options),
            ByteField(
                "reserved1", 0x08, 0x0F, attribute=FIELD_ATTR.RESERVED
            ),  # Extended reserved bits to 0x0F to make the register aligned to 0x10 boudnary
        ]

        super().__init__(data, parent_name)

    @staticmethod
    def get_size_from_options(options: Dict | None = None) -> int:
        return 16
