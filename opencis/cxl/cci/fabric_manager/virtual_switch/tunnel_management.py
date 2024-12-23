"""
 Copyright (c) 2024, Eeum, Inc.

 This software is licensed under the terms of the Revised BSD License.
 See LICENSE for details.
"""

from typing import Optional, cast

from opencis.cxl.component.physical_port_manager import PhysicalPortManager
from opencis.cxl.component.virtual_switch_manager import VirtualSwitchManager
from opencis.cxl.cci.common import (
    CCI_FM_API_COMMAND_OPCODE,
)
from opencis.cxl.component.cci_executor import (
    CciRequest,
    CciResponse,
    CciForegroundCommand,
)
from opencis.cxl.transport.transaction import CciMessagePacket
from opencis.cxl.cci.common import TunnelManagementRequestPayload, TunnelManagementResponsePayload


class TunnelManagementCommand(CciForegroundCommand):
    OPCODE = CCI_FM_API_COMMAND_OPCODE.TUNNEL_MANAGEMENT_COMMAND

    def __init__(
        self,
        physical_port_manager: PhysicalPortManager,
        virtual_switch_manager: VirtualSwitchManager,
        label: Optional[str] = None,
    ):
        super().__init__(self.OPCODE, label=label)
        self._physical_port_manager = physical_port_manager
        self._virtual_switch_manager = virtual_switch_manager

    async def _execute(self, request: CciRequest) -> CciResponse:
        request_payload = self.parse_request_payload(request.payload)
        port_or_ld_id = request_payload.port_or_ld_id
        port_device = self._physical_port_manager.get_port_device(port_or_ld_id)

        real_payload = request_payload.command_payload
        real_payload_packet = cast(CciMessagePacket, real_payload)
        await port_device.get_downstream_connection().cci_fifo.host_to_target.put(
            real_payload_packet
        )

        dev_response: CciMessagePacket = (
            await port_device.get_downstream_connection().cci_fifo.target_to_host.get()
        )

        payload = TunnelManagementResponsePayload(
            dev_response.get_size(), payload=bytes(dev_response)
        )

        return CciResponse(payload=payload)

    @classmethod
    def create_cci_request(cls, request: TunnelManagementRequestPayload) -> CciRequest:
        return CciRequest(opcode=cls.OPCODE, payload=request.dump())

    @staticmethod
    def parse_request_payload(payload: bytes) -> TunnelManagementRequestPayload:
        return TunnelManagementRequestPayload.parse(payload)

    @staticmethod
    def parse_response_payload(
        payload: bytes,
    ) -> TunnelManagementResponsePayload:
        return TunnelManagementResponsePayload.parse(payload)
