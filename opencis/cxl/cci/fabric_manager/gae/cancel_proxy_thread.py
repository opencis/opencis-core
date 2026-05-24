"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.

Cancel Proxy Thread — Opcode 580Bh
Section 7.7.14.12, CXL Specification Rev 4.0 Version 1.0

Cancels an active proxy thread started by Proxy GFD Management Command.
If the thread has already completed, this is a no-op returning Success.

Input Payload:
  Byte 0x00  len=2   Proxy Thread ID

Output Payload: None

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
class CancelProxyThreadRequestPayload:
    thread_id: int = 0

    PAYLOAD_SIZE = 2

    def dump(self) -> bytes:
        return pack("<H", self.thread_id)

    @classmethod
    def parse(cls, data: bytes) -> "CancelProxyThreadRequestPayload":
        if len(data) < cls.PAYLOAD_SIZE:
            raise ValueError("CancelProxyThreadRequestPayload: need 2 bytes")
        return cls(thread_id=unpack_from("<H", data, 0)[0])


# ---------------------------------------------------------------------------
# Command handler
# ---------------------------------------------------------------------------


class CancelProxyThreadCommand(CciForegroundCommand):
    """
    CCI foreground command for Cancel Proxy Thread (Opcode 580Bh).

    Cancels the asyncio task associated with a proxy thread in GaeManager.
    """

    OPCODE = CCI_GAE_COMMAND_OPCODE.CANCEL_PROXY_THREAD

    def __init__(self, gae_manager: GaeManager):
        super().__init__(self.OPCODE)
        self._gae_manager = gae_manager

    async def _execute(self, request: CciRequest) -> CciResponse:
        try:
            req_payload = CancelProxyThreadRequestPayload.parse(
                request.payload or b"\x00\x00"
            )
        except ValueError as e:
            logger.error(self._create_message(f"parse error: {e}"))
            return CciResponse(return_code=CCI_RETURN_CODE.INVALID_INPUT)

        rc = self._gae_manager.cancel_proxy(req_payload.thread_id)
        return CciResponse(return_code=rc)

    @staticmethod
    def create_cci_request(thread_id: int) -> CciRequest:
        req = CciRequest()
        req.opcode = CancelProxyThreadCommand.OPCODE
        req.payload = CancelProxyThreadRequestPayload(thread_id=thread_id).dump()
        return req
