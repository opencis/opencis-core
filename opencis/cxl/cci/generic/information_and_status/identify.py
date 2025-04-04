"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import ClassVar, Optional
from opencis.pci.component.pci import EEUM_VID
from opencis.cxl.cci.common import (
    CCI_GENERIC_COMMAND_OPCODE,
)
from opencis.cxl.component.cci_executor import (
    CciRequest,
    CciResponse,
    CciForegroundCommand,
)


class IdentifyComponentType(Enum):
    SWITCH = 0x00
    TYPE3 = 0x03
    GFD = 0x04


@dataclass
class IdentifyResponsePayload:
    structure_size: ClassVar[int] = 18  # Fixed structure size

    vendor_id: int = field(default=EEUM_VID, metadata={"offset": 0, "length": 2})
    device_id: int = field(default=0, metadata={"offset": 2, "length": 2})
    sub_system_vendor_id: int = field(default=0, metadata={"offset": 4, "length": 2})
    sub_system_id: int = field(default=0, metadata={"offset": 6, "length": 2})
    serial_number: int = field(default=0, metadata={"offset": 8, "length": 8})
    max_supported_msg_size: int = field(default=10, metadata={"offset": 16, "length": 1})
    component_type: IdentifyComponentType = field(default=0, metadata={"offset": 17, "length": 1})

    @classmethod
    def parse(cls, data: bytes):
        if len(data) != cls.structure_size:
            raise ValueError("Provided bytes object does not match the expected data size.")
        vendor_id = int.from_bytes(data[0:2], "little")
        device_id = int.from_bytes(data[2:4], "little")
        sub_system_vendor_id = int.from_bytes(data[4:6], "little")
        sub_system_id = int.from_bytes(data[6:8], "little")
        serial_number = int.from_bytes(data[8:16], "little")
        max_supported_msg_size = int.from_bytes(data[16:17], "little")
        component_type = int.from_bytes(data[17:18], "little")
        return cls(
            vendor_id,
            device_id,
            sub_system_vendor_id,
            sub_system_id,
            serial_number,
            max_supported_msg_size,
            IdentifyComponentType(component_type),
        )

    def dump(self) -> bytes:
        data = bytearray(self.structure_size)
        data[0:2] = self.vendor_id.to_bytes(2, "little")
        data[2:4] = self.device_id.to_bytes(2, "little")
        data[4:6] = self.sub_system_vendor_id.to_bytes(2, "little")
        data[6:8] = self.sub_system_id.to_bytes(2, "little")
        data[8:16] = self.serial_number.to_bytes(2, "little")
        data[16:17] = self.max_supported_msg_size.to_bytes(1, "little")
        data[17:18] = self.component_type.value.to_bytes(1, "little")
        return bytes(data)

    def get_pretty_print(self) -> str:
        return (
            f"- Identify:\n"
            f"- Vendor ID: 0x{self.vendor_id:04X}\n"
            f"- Device ID: 0x{self.device_id:04X}\n"
            f"- Subsystem Vendor ID: 0x{self.sub_system_vendor_id:04X}\n"
            f"- Subsystem ID: 0x{self.sub_system_id:04X}\n"
            f"- Serial Number: 0x{self.serial_number:016X}\n"
            f"- Max Supported Message Size: 2^{self.max_supported_msg_size} Bytes\n"
            f"- Component Type: {self.component_type.name}\n"
        )


class IdentifyCommand(CciForegroundCommand):
    OPCODE = CCI_GENERIC_COMMAND_OPCODE.IDENTIFY

    def __init__(self, dev_info: IdentifyResponsePayload, label: Optional[str] = None):
        super().__init__(self.OPCODE, label=label)
        self._dev_info = dev_info

    async def _execute(self, _: CciRequest) -> CciResponse:
        payload = self._dev_info.dump()
        return CciResponse(payload=payload)

    @classmethod
    def create_cci_request(cls) -> CciRequest:
        return CciRequest(opcode=cls.OPCODE)

    @staticmethod
    def parse_response_payload(
        payload: bytes,
    ) -> IdentifyResponsePayload:
        return IdentifyResponsePayload.parse(payload)
