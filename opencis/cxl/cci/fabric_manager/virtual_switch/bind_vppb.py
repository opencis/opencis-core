"""
 Copyright (c) 2024, Eeum, Inc.

 This software is licensed under the terms of the Revised BSD License.
 See LICENSE for details.
"""

from dataclasses import dataclass
from struct import pack, unpack

from opencis.cxl.component.cci_executor import (
    CciBackgroundCommand,
    CciRequest,
    CciResponse,
    ProgressCallback,
)
from opencis.cxl.component.virtual_switch_manager import VirtualSwitchManager
from opencis.cxl.component.physical_port_manager import (
    PhysicalPortManager,
    CXL_COMPONENT_TYPE,
)
from opencis.cxl.cci.common import CCI_FM_API_COMMAND_OPCODE, CCI_RETURN_CODE
from opencis.util.logger import logger

"""

The following dataclass is genearted by ChatGPT (GPT-4)

https://chat.openai.com/share/470bd62a-eaa4-4218-aa3e-4353276a16fd

"""

# pylint: disable=duplicate-code


@dataclass
class BindVppbRequestPayload:
    vcs_id: int
    vppb_id: int
    physical_port_id: int
    ld_id: int = 0

    @classmethod
    def parse(cls, data: bytes):
        vcs_id, vppb_id, physical_port_id = unpack("<BBB", data[:3])
        ld_id = unpack("<H", data[4:6])[0]
        return cls(vcs_id, vppb_id, physical_port_id, ld_id)

    def dump(self):
        data = bytearray(6)
        data[0] = self.vcs_id
        data[1] = self.vppb_id
        data[2] = self.physical_port_id
        # byte 3 (reserved) is already 0
        data[4:6] = pack("<H", self.ld_id)
        return bytes(data)

    def get_pretty_print(self):
        return (
            f"- VCS_ID: {self.vcs_id}\n"
            f"- VPPB_ID: {self.vppb_id}\n"
            f"- PHYSICAL_PORT_ID: {self.physical_port_id}\n"
            f"- LD_ID: {self.ld_id:#06x}"
        )


class BindVppbCommand(CciBackgroundCommand):
    OPCODE = CCI_FM_API_COMMAND_OPCODE.BIND_VPPB

    def __init__(
        self,
        physical_port_manager: PhysicalPortManager,
        virtual_switch_manager: VirtualSwitchManager,
    ):
        super().__init__(self.OPCODE)
        self._physical_port_manager = physical_port_manager
        self._virtual_switch_manager = virtual_switch_manager

    async def _execute(self, request: CciRequest, callback: ProgressCallback) -> CciResponse:
        request_payload = self.parse_request_payload(request.payload)
        vcs_id = request_payload.vcs_id
        vppb_id = request_payload.vppb_id
        port_id = request_payload.physical_port_id
        ld_id = request_payload.ld_id

        vcs_count = self._virtual_switch_manager.get_virtual_switch_counts()
        if vcs_id >= vcs_count:
            logger.error(self._create_message("VCS ID is out of bound"))
            return CciResponse(return_code=CCI_RETURN_CODE.INVALID_INPUT)

        port_count = self._physical_port_manager.get_port_counts()
        if port_id >= port_count:
            logger.error(self._create_message("Physical Port ID is out of bound"))
            return CciResponse(return_code=CCI_RETURN_CODE.INVALID_INPUT)

        port_device = self._physical_port_manager.get_port_device(port_id)
        if port_device.get_device_type() != CXL_COMPONENT_TYPE.DSP:
            logger.error(self._create_message("Only DSP port can bind to vPPB"))
            return CciResponse(return_code=CCI_RETURN_CODE.INVALID_INPUT)

        vcs = self._virtual_switch_manager.get_virtual_switch(vcs_id)
        if vppb_id >= vcs.get_vppb_counts():
            logger.error(self._create_message("vPPB ID is out of bound"))
            return CciResponse(return_code=CCI_RETURN_CODE.INVALID_INPUT)

        if vcs.is_vppb_bound(vppb_id):
            logger.error(self._create_message(f"vPPB {vppb_id} is already bound"))
            return CciResponse(return_code=CCI_RETURN_CODE.INVALID_INPUT)

        await callback(50)
        await vcs.bind_vppb(port_id, vppb_id, ld_id)
        response = CciResponse()
        return response

    @classmethod
    def create_cci_request(
        cls,
        request: BindVppbRequestPayload,
    ) -> CciRequest:
        cci_request = CciRequest()
        cci_request.opcode = cls.OPCODE
        cci_request.payload = request.dump()
        return cci_request

    @staticmethod
    def parse_request_payload(payload: bytes) -> BindVppbRequestPayload:
        return BindVppbRequestPayload.parse(payload)
