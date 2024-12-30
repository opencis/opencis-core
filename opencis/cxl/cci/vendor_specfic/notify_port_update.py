"""
 Copyright (c) 2024, Eeum, Inc.

 This software is licensed under the terms of the Revised BSD License.
 See LICENSE for details.
"""

from dataclasses import dataclass, field, fields
from typing import ClassVar, List, Tuple
import struct
from opencis.cxl.component.cci_executor import CciRequest
from opencis.cxl.cci.common import CCI_VENDOR_SPECIFIC_OPCODE

# pylint: disable=duplicate-code


@dataclass
class NotifyPortUpdateRequestPayload:
    OPCODE: ClassVar[int] = CCI_VENDOR_SPECIFIC_OPCODE.NOTIFY_PORT_UPDATE

    # Class constants for the struct format
    _STRUCT_FORMAT: ClassVar[str] = "BB"  # Little-endian, 1 byte integer x 2
    _FIELD_SIZES: ClassVar[List[Tuple[str, int]]] = [
        ("port_id", 1),  # 1 byte
        ("connected", 1),  # 1 byte
    ]

    # Fields
    port_id: int = field(default=0, metadata={"size": 1})
    connected: int = field(default=0, metadata={"size": 1})

    @classmethod
    def parse(cls, data: bytes):
        expected_size = sum(size for _, size in cls._FIELD_SIZES)
        if len(data) != expected_size:
            raise ValueError(
                f"Data size does not match the expected struct size of {expected_size} bytes"
            )

        values = struct.unpack(cls._STRUCT_FORMAT, data)
        return cls(*values)

    def dump(self) -> bytes:
        values = (self.port_id, self.connected)
        return struct.pack(self._STRUCT_FORMAT, *values)

    def get_pretty_print(self):
        field_values = {f.name: getattr(self, f.name) for f in fields(self)}
        return "\n".join(f"{name}: {value}" for name, value in field_values.items())

    def create_request(self) -> CciRequest:
        payload = self.dump()
        request = CciRequest(opcode=self.OPCODE, payload=payload)
        return request
