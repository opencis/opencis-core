"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.

Get PID Binding — Opcode 5705h
Section 7.7.13.6, CXL Specification Rev 4.0 Version 1.0

Reads the current binding of a Downstream ES PID to an Upstream ES vDSP,
or an Upstream ES USP PID to a Downstream ES vUSP. Also returns HMAT latency
and BW values for generating CDAT information.

Input Payload (Table 7-125):
  Byte 0x00  len=1   Target VCS ID
  Byte 0x01  len=1   Target vPPB index (reserved if binding target is Host ES VCS)

Output Payload (Table 7-126):
  Byte 0x00  len=2   PID (Bits[11:0]); FFFh if unbound
  Byte 0x02  len=2   Reserved
  Byte 0x04  len=8   Latency Entry Base Unit (HMAT)
  Byte 0x0C  len=2   Latency Entry (HMAT)
  Byte 0x0E  len=8   BW Entry Base Unit (HMAT)
  Byte 0x16  len=2   BW Entry (HMAT)
  Total: 0x18 = 24 bytes

Return codes: Success, Unsupported, Invalid Input, Internal Error, Retry Required, Busy
"""

from dataclasses import dataclass
from struct import pack, unpack_from

from opencis.cxl.cci.common import CCI_FM_API_COMMAND_OPCODE, CCI_RETURN_CODE
from opencis.cxl.component.cci_executor import CciRequest, CciResponse, CciForegroundCommand
from opencis.cxl.component.pbr_switch_manager import PbrSwitchManager, PID_UNASSIGNED
from opencis.util.logger import logger


@dataclass
class GetPidBindingRequestPayload:
    target_vcs: int = 0
    target_vppb: int = 0

    def dump(self) -> bytes:
        return bytes([self.target_vcs & 0xFF, self.target_vppb & 0xFF])

    @classmethod
    def parse(cls, data: bytes) -> "GetPidBindingRequestPayload":
        if len(data) < 2:
            raise ValueError("GetPidBindingRequestPayload: need 2 bytes")
        return cls(target_vcs=data[0], target_vppb=data[1])


@dataclass
class GetPidBindingResponsePayload:
    pid: int = PID_UNASSIGNED          # 12-bit; FFFh = unbound
    latency_entry_base_unit: int = 0   # 8 bytes
    latency_entry: int = 0             # 2 bytes
    bw_entry_base_unit: int = 0        # 8 bytes
    bw_entry: int = 0                  # 2 bytes

    PAYLOAD_SIZE = 0x18  # 24 bytes

    def dump(self) -> bytes:
        data = bytearray(self.PAYLOAD_SIZE)
        data[0x00:0x02] = pack("<H", self.pid & 0x0FFF)
        # 0x02..0x03 reserved
        data[0x04:0x0C] = self.latency_entry_base_unit.to_bytes(8, "little")
        data[0x0C:0x0E] = pack("<H", self.latency_entry)
        data[0x0E:0x16] = self.bw_entry_base_unit.to_bytes(8, "little")
        data[0x16:0x18] = pack("<H", self.bw_entry)
        return bytes(data)

    @classmethod
    def parse(cls, data: bytes) -> "GetPidBindingResponsePayload":
        if len(data) < cls.PAYLOAD_SIZE:
            raise ValueError(
                f"GetPidBindingResponsePayload: need {cls.PAYLOAD_SIZE} bytes, got {len(data)}"
            )
        pid = unpack_from("<H", data, 0x00)[0] & 0x0FFF
        latency_base = int.from_bytes(data[0x04:0x0C], "little")
        latency_entry = unpack_from("<H", data, 0x0C)[0]
        bw_base = int.from_bytes(data[0x0E:0x16], "little")
        bw_entry = unpack_from("<H", data, 0x16)[0]
        return cls(
            pid=pid,
            latency_entry_base_unit=latency_base,
            latency_entry=latency_entry,
            bw_entry_base_unit=bw_base,
            bw_entry=bw_entry,
        )

    def get_pretty_print(self) -> str:
        bound = self.pid != PID_UNASSIGNED
        return (
            f"- Bound: {bound}\n"
            f"- PID: {self.pid:#05x}\n"
            f"- Latency Base Unit: {self.latency_entry_base_unit}\n"
            f"- Latency Entry:     {self.latency_entry}\n"
            f"- BW Base Unit:      {self.bw_entry_base_unit}\n"
            f"- BW Entry:          {self.bw_entry}"
        )


class GetPidBindingCommand(CciForegroundCommand):
    """
    CCI foreground command for Get PID Binding (Opcode 5705h).

    Returns the current PID binding for a (vcs_id, vppb_id) pair including
    HMAT latency and BW values. Returns FFFh as PID when not bound.
    """

    OPCODE = CCI_FM_API_COMMAND_OPCODE.GET_PID_BINDING

    def __init__(self, pbr_switch_manager: PbrSwitchManager):
        super().__init__(self.OPCODE)
        self._pbr_switch_manager = pbr_switch_manager

    async def _execute(self, request: CciRequest) -> CciResponse:
        try:
            req_payload = GetPidBindingRequestPayload.parse(request.payload)
        except ValueError as e:
            logger.error(self._create_message(f"parse error: {e}"))
            return CciResponse(return_code=CCI_RETURN_CODE.INVALID_INPUT)

        binding = self._pbr_switch_manager.get_pid_binding(
            req_payload.target_vcs, req_payload.target_vppb
        )

        if binding is None:
            # Not yet bound — return PID=FFFh, zeroed HMAT
            resp_payload = GetPidBindingResponsePayload(pid=PID_UNASSIGNED)
        else:
            resp_payload = GetPidBindingResponsePayload(
                pid=binding.pid,
                latency_entry_base_unit=binding.hmat.latency_entry_base_unit,
                latency_entry=binding.hmat.latency_entry,
                bw_entry_base_unit=binding.hmat.bw_entry_base_unit,
                bw_entry=binding.hmat.bw_entry,
            )

        response = CciResponse()
        response.payload = resp_payload.dump()
        return response

    @staticmethod
    def create_cci_request(request: GetPidBindingRequestPayload) -> CciRequest:
        req = CciRequest()
        req.opcode = GetPidBindingCommand.OPCODE
        req.payload = request.dump()
        return req

    @staticmethod
    def parse_response_payload(data: bytes) -> GetPidBindingResponsePayload:
        return GetPidBindingResponsePayload.parse(data)
