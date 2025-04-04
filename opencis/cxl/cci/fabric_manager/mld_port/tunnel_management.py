"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from typing import List, Optional, cast
from opencis.cxl.component.cxl_connection import CxlConnection
from opencis.cxl.cci.common import (
    CCI_FM_API_COMMAND_OPCODE,
)
from opencis.cxl.component.cci_executor import (
    CciRequest,
    CciResponse,
    CciForegroundCommand,
)
from opencis.cxl.device.cxl_type3_device import CxlType3Device
from opencis.cxl.transport.transaction import CciMessagePacket
from opencis.cxl.cci.common import TunnelManagementRequestPayload, TunnelManagementResponsePayload


class TunnelManagementCommand(CciForegroundCommand):
    OPCODE = CCI_FM_API_COMMAND_OPCODE.TUNNEL_MANAGEMENT_COMMAND

    def __init__(
        self,
        label: Optional[str] = None,
        cxl_type3_devices: List[CxlType3Device] = None,
        cxl_connections: List[CxlConnection] = None,
    ):
        super().__init__(self.OPCODE, label=label)
        if cxl_type3_devices is None:
            cxl_type3_devices = []
        if cxl_connections is None:
            cxl_connections = []
        self._cxl_type3_devices = cxl_type3_devices
        self._cxl_connections = cxl_connections

    async def _execute(self, request: CciRequest) -> CciResponse:
        request_payload = self.parse_request_payload(request.payload)
        port_or_ld_id = request_payload.port_or_ld_id

        real_payload = request_payload.command_payload
        connection = self._cxl_connections[port_or_ld_id]

        await connection.cci_fifo.host_to_target.put(cast(CciMessagePacket, real_payload))

        dev_response: CciMessagePacket = await connection.cci_fifo.target_to_host.get()

        payload = TunnelManagementResponsePayload(
            dev_response.get_size(), payload=bytes(CciMessagePacket)
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
