"""
 Copyright (c) 2024, Eeum, Inc.

 This software is licensed under the terms of the Revised BSD License.
 See LICENSE for details.
"""

from dataclasses import dataclass, field

from opencis.cxl.component.cci_executor import (
    CciBackgroundCommand,
    CciRequest,
    CciResponse,
    ProgressCallback,
)
from opencis.cxl.component.virtual_switch_manager import VirtualSwitchManager
from opencis.cxl.cci.common import CCI_FM_API_COMMAND_OPCODE, CCI_RETURN_CODE
from opencis.util.logger import logger

"""

The following dataclass is genearted by ChatGPT (GPT-4)

https://chat.openai.com/share/ee6dbdd9-c8d3-466e-b1ee-1d332b5b0ac2

"""


# pylint: disable=duplicate-code


@dataclass
class UnbindVppbRequestPayload:
    vcs_id: int = field(default=0)
    vppb_id: int = field(default=0)
    unbind_option: int = field(default=0)

    @classmethod
    def parse(cls, data: bytes) -> "UnbindVppbRequestPayload":
        if len(data) < 3:
            raise ValueError("Data provided is too short to parse.")

        vcs_id, vppb_id = data[0], data[1]
        unbind_option = data[2] & 0x0F  # Masking higher nibble to get Bits[3:0]

        return cls(
            vcs_id=vcs_id,
            vppb_id=vppb_id,
            unbind_option=unbind_option,
        )

    def dump(self) -> bytes:
        buffer = bytearray(3)
        buffer[0] = self.vcs_id & 0xFF
        buffer[1] = self.vppb_id & 0xFF
        buffer[2] = self.unbind_option & 0x0F  # Ensuring that Bits[7:4] are 0

        return bytes(buffer)

    def get_pretty_print(self) -> str:
        return (
            f"- Virtual CXL Switch ID: {self.vcs_id}\n"
            f"- vPPB ID: {self.vppb_id}\n"
            f"- Unbind Option: {self.unbind_option}\n"
        )


class UnbindVppbCommand(CciBackgroundCommand):
    OPCODE = CCI_FM_API_COMMAND_OPCODE.UNBIND_VPPB

    def __init__(self, virtual_switch_manager: VirtualSwitchManager):
        super().__init__(self.OPCODE)
        self._virtual_switch_manager = virtual_switch_manager

    async def _execute(self, request: CciRequest, callback: ProgressCallback) -> CciResponse:
        request_payload = self.parse_request_payload(request.payload)
        vcs_id = request_payload.vcs_id
        vppb_id = request_payload.vppb_id
        vcs_count = self._virtual_switch_manager.get_virtual_switch_counts()
        if vcs_id >= vcs_count:
            logger.debug(self._create_message("VCS ID is out of bound"))
            return CciResponse(return_code=CCI_RETURN_CODE.INVALID_INPUT)

        vcs = self._virtual_switch_manager.get_virtual_switch(vcs_id)
        if vppb_id >= vcs.get_vppb_counts():
            logger.debug(self._create_message("vPPB ID is out of bound"))
            return CciResponse(return_code=CCI_RETURN_CODE.INVALID_INPUT)

        if not vcs.is_vppb_bound(vppb_id):
            logger.debug(self._create_message(f"vPPB {vppb_id} is already unbound"))
            return CciResponse(return_code=CCI_RETURN_CODE.INVALID_INPUT)

        await callback(50)

        await vcs.unbind_vppb(vppb_id)
        response = CciResponse()
        return response

    @classmethod
    def create_cci_request(
        cls,
        request: UnbindVppbRequestPayload,
    ) -> CciRequest:
        cci_request = CciRequest()
        cci_request.opcode = cls.OPCODE
        cci_request.payload = request.dump()
        return cci_request

    @staticmethod
    def parse_request_payload(payload: bytes) -> UnbindVppbRequestPayload:
        return UnbindVppbRequestPayload.parse(payload)
