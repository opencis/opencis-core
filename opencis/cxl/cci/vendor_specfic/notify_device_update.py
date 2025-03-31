"""
Copyright (c) 2024, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from dataclasses import dataclass
from typing import ClassVar
from opencis.cxl.component.cci_executor import CciRequest
from opencis.cxl.cci.common import CCI_VENDOR_SPECIFIC_OPCODE


@dataclass
class NotifyDeviceUpdateRequestPayload:
    OPCODE: ClassVar[int] = CCI_VENDOR_SPECIFIC_OPCODE.NOTIFY_DEVICE_UPDATE

    def create_request(self) -> CciRequest:
        request = CciRequest(opcode=self.OPCODE)
        return request
