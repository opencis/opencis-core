"""
Copyright (c) 2024-2025, Eeum, Inc.

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
from opencis.cxl.component.cxl_memory_device_component import (
    CxlMemoryDeviceComponent,
    MemoryDeviceStatus,
    MEDIA_STATUS,
    RESET_REQUEST,
)


class MemoryDeviceStatusRegistersOptions(TypedDict):
    cxl_memory_device_component: CxlMemoryDeviceComponent


class MemoryDeviceStatusRegister(BitMaskedBitStructure):
    device_fatal: int
    fw_halt: int
    media_status: MEDIA_STATUS
    mailbox_interfaces_ready: RESET_REQUEST
    reset_needed: int

    _fields = [
        BitField("device_fatal", 0, 0, FIELD_ATTR.RO),
        BitField("fw_halt", 1, 1, FIELD_ATTR.RO),
        BitField("media_status", 2, 3, FIELD_ATTR.RO),
        BitField("mailbox_interfaces_ready", 4, 4, FIELD_ATTR.RO),
        BitField("reset_needed", 5, 7, FIELD_ATTR.RO),
        BitField("reserved", 8, 63, FIELD_ATTR.RESERVED),
    ]

    def __init__(
        self,
        data: Optional[ShareableByteArray] = None,
        parent_name: Optional[str] = None,
        options: Optional[MemoryDeviceStatusRegistersOptions] = None,
    ):
        if not options:
            raise Exception("options is required")

        self.cxl_memory_device_component = options["cxl_memory_device_component"]

        super().__init__(data, parent_name)

    def read_bytes(self, start_offset: int, end_offset: int) -> int:
        status: MemoryDeviceStatus = self.cxl_memory_device_component.get_status()
        self.write_fields_from_dict(status)
        return super().read_bytes(start_offset, end_offset)


class MemoryDeviceStatusRegisters(BitMaskedBitStructure):
    status: MemoryDeviceStatusRegister

    def __init__(
        self,
        data: Optional[ShareableByteArray] = None,
        parent_name: Optional[str] = None,
        options: Optional[MemoryDeviceStatusRegistersOptions] = None,
    ):
        if not options:
            raise Exception("options is required")

        self._fields = [
            StructureField("status", 0x00, 0x07, MemoryDeviceStatusRegister, options=options),
            ByteField(
                "reserved1", 0x08, 0x0F, attribute=FIELD_ATTR.RESERVED
            ),  # Extended reserved bits to 0x0F to make the register aligned to 0x10 boudnary
        ]

        super().__init__(data, parent_name)

    @staticmethod
    def get_size_from_options(options: Dict | None = None) -> int:
        return 16
