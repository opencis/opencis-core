"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.

Get PID Access Vectors — Opcode 5802h
Section 7.7.14.3, CXL Specification Rev 4.0 Version 1.0

Returns the Global Memory Vector (GMV) and Valid Target Vector (VTV)
for a given PID.  The GMV is a 64-bit bitmask where each bit corresponds
to a VCS that has G-FAM access to the memory region identified by the PID.
The VTV is a bitmask of vPPBs that are valid routing targets.

For a simple-device GFD (no G-FAM) both vectors are zero.

Input Payload (Table 7-164):
  Byte 0x00  len=2   PID (Bits[11:0], upper bits reserved)

Output Payload (Table 7-165):
  Byte 0x00  len=8   Global Memory Vector (GMV) — bitmask by VCS ID
  Byte 0x08  len=8   Valid Target Vector (VTV) — bitmask by vPPB index
  Byte 0x10  len=2   PID
  Byte 0x12  len=2   Reserved

Return codes: Success, Unsupported, Invalid Input
"""

from dataclasses import dataclass
from struct import pack, unpack_from

from opencis.cxl.cci.common import CCI_GAE_COMMAND_OPCODE
from opencis.cxl.component.cci_executor import CciRequest, CciResponse, CciForegroundCommand
from opencis.cxl.component.gae_manager import GaeManager


# ---------------------------------------------------------------------------
# Wire-format structures
# ---------------------------------------------------------------------------


@dataclass
class GetPidAccessVectorsRequestPayload:
    """Input payload for Get PID Access Vectors (Table 7-164)."""
    pid: int = 0

    PAYLOAD_SIZE = 2

    def dump(self) -> bytes:
        data = bytearray(self.PAYLOAD_SIZE)
        data[0:2] = pack("<H", self.pid & 0x0FFF)
        return bytes(data)

    @classmethod
    def parse(cls, data: bytes) -> "GetPidAccessVectorsRequestPayload":
        if len(data) < cls.PAYLOAD_SIZE:
            raise ValueError("GetPidAccessVectorsRequestPayload: need 2 bytes")
        pid = unpack_from("<H", data, 0)[0] & 0x0FFF
        return cls(pid=pid)


@dataclass
class GetPidAccessVectorsResponsePayload:
    """
    Output payload for Get PID Access Vectors (Table 7-165).

    gmv (Global Memory Vector):  64-bit bitmask, bit i = VCS i has G-FAM access.
    vtv (Valid Target Vector):    64-bit bitmask, bit i = vPPB i is valid target.
    pid:                          The requested PID echoed back.

    For a simple-device GFD both vectors are always zero.
    """
    gmv: int = 0   # 8 bytes
    vtv: int = 0   # 8 bytes
    pid: int = 0   # 2 bytes

    PAYLOAD_SIZE = 20  # 8+8+2+2 (last 2 reserved)

    def dump(self) -> bytes:
        data = bytearray(self.PAYLOAD_SIZE)
        data[0x00:0x08] = self.gmv.to_bytes(8, "little")
        data[0x08:0x10] = self.vtv.to_bytes(8, "little")
        data[0x10:0x12] = pack("<H", self.pid & 0x0FFF)
        # 0x12-0x13 reserved
        return bytes(data)

    @classmethod
    def parse(cls, data: bytes) -> "GetPidAccessVectorsResponsePayload":
        if len(data) < cls.PAYLOAD_SIZE:
            raise ValueError(
                f"GetPidAccessVectorsResponsePayload: need {cls.PAYLOAD_SIZE} bytes"
            )
        gmv = int.from_bytes(data[0x00:0x08], "little")
        vtv = int.from_bytes(data[0x08:0x10], "little")
        pid = unpack_from("<H", data, 0x10)[0] & 0x0FFF
        return cls(gmv=gmv, vtv=vtv, pid=pid)

    def get_pretty_print(self) -> str:
        return (
            f"- PID:  {self.pid:#05x}\n"
            f"- GMV:  {self.gmv:#018x}\n"
            f"- VTV:  {self.vtv:#018x}"
        )


# ---------------------------------------------------------------------------
# Command handler
# ---------------------------------------------------------------------------


class GetPidAccessVectorsCommand(CciForegroundCommand):
    """
    CCI foreground command for Get PID Access Vectors (Opcode 5802h).

    For a simple-device GFD the GAE has no G-FAM vPPBs so both GMV and
    VTV are always 0.  The command is still implemented so the FM/host
    can query without receiving UNSUPPORTED.
    """

    OPCODE = CCI_GAE_COMMAND_OPCODE.GET_PID_ACCESS_VECTORS

    def __init__(self, gae_manager: GaeManager):
        super().__init__(self.OPCODE)
        self._gae_manager = gae_manager

    async def _execute(self, request: CciRequest) -> CciResponse:
        try:
            req_payload = GetPidAccessVectorsRequestPayload.parse(request.payload or b"\x00\x00")
        except ValueError:
            req_payload = GetPidAccessVectorsRequestPayload()

        # For a simple device: no G-FAM, so GMV=0, VTV=0.
        payload = GetPidAccessVectorsResponsePayload(pid=req_payload.pid)
        response = CciResponse()
        response.payload = payload.dump()
        return response

    @staticmethod
    def create_cci_request(pid: int = 0) -> CciRequest:
        req = CciRequest()
        req.opcode = GetPidAccessVectorsCommand.OPCODE
        req.payload = GetPidAccessVectorsRequestPayload(pid=pid).dump()
        return req

    @staticmethod
    def parse_response_payload(data: bytes) -> GetPidAccessVectorsResponsePayload:
        return GetPidAccessVectorsResponsePayload.parse(data)
