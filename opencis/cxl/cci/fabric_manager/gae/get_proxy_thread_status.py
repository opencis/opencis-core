"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.

Get Proxy Thread Status — Opcode 580Ah
Section 7.7.14.11, CXL Specification Rev 4.0 Version 1.0

Queries the completion status of a proxy thread started by Proxy GFD
Management Command (5809h).

Input Payload:
  Byte 0x00  len=2   Proxy Thread ID

Output Payload:
  Byte 0x00  len=2   Proxy Thread ID (echoed)
  Byte 0x02  len=1   Status:
                       Bit 0: Completed (1 = done)
                       Bits[7:1]: Reserved
  Byte 0x03  len=1   Reserved
  Byte 0x04  len=2   GFD Return Code (valid only when Completed=1)
  Byte 0x06  len=2   Reserved
  Byte 0x08  varies  GFD Response Payload (present only when Completed=1)

Return codes: Success, Unsupported, Invalid Input
"""

from dataclasses import dataclass
from struct import pack, unpack_from

from opencis.cxl.cci.common import CCI_GAE_COMMAND_OPCODE, CCI_RETURN_CODE
from opencis.cxl.component.cci_executor import CciRequest, CciResponse, CciForegroundCommand
from opencis.cxl.component.gae_manager import GaeManager
from opencis.util.logger import logger


# ---------------------------------------------------------------------------
# Wire-format structures
# ---------------------------------------------------------------------------


@dataclass
class GetProxyThreadStatusRequestPayload:
    thread_id: int = 0

    PAYLOAD_SIZE = 2

    def dump(self) -> bytes:
        return pack("<H", self.thread_id)

    @classmethod
    def parse(cls, data: bytes) -> "GetProxyThreadStatusRequestPayload":
        if len(data) < cls.PAYLOAD_SIZE:
            raise ValueError("GetProxyThreadStatusRequestPayload: need 2 bytes")
        return cls(thread_id=unpack_from("<H", data, 0)[0])


@dataclass
class GetProxyThreadStatusResponsePayload:
    """
    Output payload for Get Proxy Thread Status.

    gfd_return_code is valid only when completed=True.
    gfd_response_payload contains the raw bytes returned by the GFD
    (empty if not yet completed).
    """
    thread_id: int = 0
    completed: bool = False
    gfd_return_code: int = 0
    gfd_response_payload: bytes = b""

    HEADER_SIZE = 8

    def dump(self) -> bytes:
        header = bytearray(self.HEADER_SIZE)
        header[0x00:0x02] = pack("<H", self.thread_id)
        header[0x02] = 0x01 if self.completed else 0x00
        # 0x03 reserved
        header[0x04:0x06] = pack("<H", self.gfd_return_code)
        # 0x06-0x07 reserved
        return bytes(header) + self.gfd_response_payload

    @classmethod
    def parse(cls, data: bytes) -> "GetProxyThreadStatusResponsePayload":
        if len(data) < cls.HEADER_SIZE:
            raise ValueError(
                f"GetProxyThreadStatusResponsePayload: need {cls.HEADER_SIZE} bytes"
            )
        thread_id = unpack_from("<H", data, 0x00)[0]
        completed = bool(data[0x02] & 0x01)
        gfd_rc = unpack_from("<H", data, 0x04)[0]
        gfd_payload = bytes(data[cls.HEADER_SIZE:])
        return cls(
            thread_id=thread_id,
            completed=completed,
            gfd_return_code=gfd_rc,
            gfd_response_payload=gfd_payload,
        )

    def get_pretty_print(self) -> str:
        return (
            f"- Thread ID:     {self.thread_id}\n"
            f"- Completed:     {self.completed}\n"
            f"- GFD RC:        {self.gfd_return_code:#06x}\n"
            f"- Response bytes: {len(self.gfd_response_payload)}"
        )


# ---------------------------------------------------------------------------
# Command handler
# ---------------------------------------------------------------------------


class GetProxyThreadStatusCommand(CciForegroundCommand):
    """
    CCI foreground command for Get Proxy Thread Status (Opcode 580Ah).

    Looks up the proxy thread in GaeManager and returns its current state.
    """

    OPCODE = CCI_GAE_COMMAND_OPCODE.GET_PROXY_THREAD_STATUS

    def __init__(self, gae_manager: GaeManager):
        super().__init__(self.OPCODE)
        self._gae_manager = gae_manager

    async def _execute(self, request: CciRequest) -> CciResponse:
        try:
            req_payload = GetProxyThreadStatusRequestPayload.parse(
                request.payload or b"\x00\x00"
            )
        except ValueError as e:
            logger.error(self._create_message(f"parse error: {e}"))
            return CciResponse(return_code=CCI_RETURN_CODE.INVALID_INPUT)

        entry = self._gae_manager.get_proxy_status(req_payload.thread_id)
        if entry is None:
            logger.error(
                self._create_message(f"thread {req_payload.thread_id} not found")
            )
            return CciResponse(return_code=CCI_RETURN_CODE.INVALID_INPUT)

        gfd_resp_bytes = b""
        if entry.completed and entry.response is not None:
            gfd_resp_bytes = entry.response.payload or b""

        resp_payload = GetProxyThreadStatusResponsePayload(
            thread_id=req_payload.thread_id,
            completed=entry.completed,
            gfd_return_code=entry.return_code,
            gfd_response_payload=gfd_resp_bytes,
        )
        response = CciResponse()
        response.payload = resp_payload.dump()
        return response

    @staticmethod
    def create_cci_request(thread_id: int) -> CciRequest:
        req = CciRequest()
        req.opcode = GetProxyThreadStatusCommand.OPCODE
        req.payload = GetProxyThreadStatusRequestPayload(thread_id=thread_id).dump()
        return req

    @staticmethod
    def parse_response_payload(data: bytes) -> GetProxyThreadStatusResponsePayload:
        return GetProxyThreadStatusResponsePayload.parse(data)
