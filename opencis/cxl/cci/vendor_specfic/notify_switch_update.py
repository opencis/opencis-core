"""
 Copyright (c) 2024, Eeum, Inc.

 This software is licensed under the terms of the Revised BSD License.
 See LICENSE for details.
"""

from dataclasses import dataclass, field, fields
import struct
from typing import ClassVar, List, Tuple

from opencis.cxl.component.virtual_switch.virtual_switch import (
    PPB_BINDING_STATUS,
)
from opencis.cxl.component.cci_executor import CciRequest
from opencis.cxl.cci.common import CCI_VENDOR_SPECIFIC_OPCODE


@dataclass
class NotifySwitchUpdateRequestPayload:
    OPCODE: ClassVar[int] = CCI_VENDOR_SPECIFIC_OPCODE.NOTIFY_SWITCH_UPDATE

    # Class constants for the struct format
    _STRUCT_FORMAT: ClassVar[str] = "BBB"  # Little-endian, 1 byte integer x 3
    _FIELD_SIZES: ClassVar[List[Tuple[str, int]]] = [
        ("vcs_id", 1),  # 1 byte
        ("vppb_id", 1),  # 1 byte
        ("binding_status", 1),  # 1 byte
    ]

    # Fields
    vcs_id: int = field(default=0, metadata={"size": 1})
    vppb_id: int = field(default=0, metadata={"size": 1})
    binding_status: PPB_BINDING_STATUS = field(
        default=PPB_BINDING_STATUS.UNBOUND, metadata={"size": 1}
    )

    @classmethod
    def parse(cls, data: bytes):
        expected_size = sum(size for _, size in cls._FIELD_SIZES)
        if len(data) != expected_size:
            raise ValueError(
                f"Data size does not match the expected struct size of {expected_size} bytes"
            )

        # Unpack the data using the struct format, then use the first two bytes as is
        # and convert the third byte to the PPB_BINDING_STATUS enum
        values = struct.unpack(cls._STRUCT_FORMAT, data)
        values = values[0], values[1], PPB_BINDING_STATUS(values[2])
        return cls(*values)

    def dump(self) -> bytes:
        # Convert the binding_status enum to its integer value before packing
        values = (self.vcs_id, self.vppb_id, int(self.binding_status))
        return struct.pack(self._STRUCT_FORMAT, *values)

    def get_pretty_print(self):
        field_values = {f.name: getattr(self, f.name) for f in fields(self)}
        # Special handling for enum to print its name instead of the value
        field_values["binding_status"] = self.binding_status.name
        return "\n".join(f"{name}: {value}" for name, value in field_values.items())

    def create_request(self) -> CciRequest:
        payload = self.dump()
        request = CciRequest(opcode=self.OPCODE, payload=payload)
        return request
