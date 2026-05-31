"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.

Configure PID Binding — Opcode 5706h
Section 7.7.13.7, CXL Specification Rev 4.0 Version 1.0

Configures the binding of a PID to a target. Used to:
  - Bind Downstream ES PIDs to Upstream ES vDSPs
  - Bind Upstream ES USP PIDs to Downstream ES vUSPs

This is a BACKGROUND command (link-state transitions required).
The input includes HMAT latency and BW values for CDAT generation.

Input Payload (Table 7-127):
  Byte 0x00  len=1   Operation (Bits[2:0]: 000b=Bind, 001b=Unbind)
  Byte 0x01  len=1   Target VCS ID
  Byte 0x02  len=1   Target vPPB index (reserved if binding target is Host ES VCS)
  Byte 0x03  len=1   Reserved
  Byte 0x04  len=2   PID (Bits[11:0]) of remote binding target
  Byte 0x06  len=2   Reserved
  Byte 0x08  len=8   Latency Entry Base Unit (HMAT; reserved for Host ES VCS)
  Byte 0x10  len=2   Latency Entry       (HMAT; reserved for Host ES VCS)
  Byte 0x12  len=8   BW Entry Base Unit  (HMAT; reserved for Host ES VCS)
  Byte 0x1A  len=2   BW Entry            (HMAT; reserved for Host ES VCS)
  Total: 0x1C = 28 bytes

Output Payload: None

Return codes: Success, Unsupported, Background Command Started, Invalid Input,
              Internal Error, Retry Required, Busy
"""

from dataclasses import dataclass
from struct import pack, unpack_from

from opencis.cxl.cci.common import CCI_FM_API_COMMAND_OPCODE, CCI_RETURN_CODE
from opencis.cxl.component.cci_executor import (
    CciRequest,
    CciResponse,
    CciBackgroundCommand,
    ProgressCallback,
)
from opencis.cxl.component.pbr_switch_manager import (
    PbrSwitchManager,
    PidBindingOperation,
    HmatInfo,
)
from opencis.util.logger import logger


@dataclass
class ConfigurePidBindingRequestPayload:
    operation: int = PidBindingOperation.BIND   # Bits[2:0]
    target_vcs: int = 0
    target_vppb: int = 0
    pid: int = 0                                # Bits[11:0]
    latency_entry_base_unit: int = 0            # 8 bytes
    latency_entry: int = 0                      # 2 bytes
    bw_entry_base_unit: int = 0                 # 8 bytes
    bw_entry: int = 0                           # 2 bytes

    PAYLOAD_SIZE = 0x1C  # 28 bytes

    def dump(self) -> bytes:
        data = bytearray(self.PAYLOAD_SIZE)
        data[0x00] = self.operation & 0x07
        data[0x01] = self.target_vcs & 0xFF
        data[0x02] = self.target_vppb & 0xFF
        # 0x03 reserved
        data[0x04:0x06] = pack("<H", self.pid & 0x0FFF)
        # 0x06..0x07 reserved
        data[0x08:0x10] = self.latency_entry_base_unit.to_bytes(8, "little")
        data[0x10:0x12] = pack("<H", self.latency_entry)
        data[0x12:0x1A] = self.bw_entry_base_unit.to_bytes(8, "little")
        data[0x1A:0x1C] = pack("<H", self.bw_entry)
        return bytes(data)

    @classmethod
    def parse(cls, data: bytes) -> "ConfigurePidBindingRequestPayload":
        if len(data) < cls.PAYLOAD_SIZE:
            raise ValueError(
                f"ConfigurePidBindingRequestPayload: need {cls.PAYLOAD_SIZE} bytes, "
                f"got {len(data)}"
            )
        operation = data[0x00] & 0x07
        target_vcs = data[0x01]
        target_vppb = data[0x02]
        pid = unpack_from("<H", data, 0x04)[0] & 0x0FFF
        latency_base = int.from_bytes(data[0x08:0x10], "little")
        latency_entry = unpack_from("<H", data, 0x10)[0]
        bw_base = int.from_bytes(data[0x12:0x1A], "little")
        bw_entry = unpack_from("<H", data, 0x1A)[0]
        return cls(
            operation=operation,
            target_vcs=target_vcs,
            target_vppb=target_vppb,
            pid=pid,
            latency_entry_base_unit=latency_base,
            latency_entry=latency_entry,
            bw_entry_base_unit=bw_base,
            bw_entry=bw_entry,
        )


class ConfigurePidBindingCommand(CciBackgroundCommand):
    """
    CCI background command for Configure PID Binding (Opcode 5706h).

    This is a background operation because binding requires link-state
    transitions (Hot Reset → Detect → L0 via VDMs), which take time.
    The FM polls Background Operation Status to know when it completes.
    """

    OPCODE = CCI_FM_API_COMMAND_OPCODE.CONFIGURE_PID_BINDING

    def __init__(self, pbr_switch_manager: PbrSwitchManager):
        super().__init__(self.OPCODE)
        self._pbr_switch_manager = pbr_switch_manager

    async def _execute(
        self, request: CciRequest, callback: ProgressCallback
    ) -> CciResponse:
        try:
            payload = ConfigurePidBindingRequestPayload.parse(request.payload)
        except ValueError as e:
            logger.error(self._create_message(f"parse error: {e}"))
            await callback(100)
            return CciResponse(return_code=CCI_RETURN_CODE.INVALID_INPUT)

        await callback(10)

        op = PidBindingOperation(payload.operation)
        hmat = HmatInfo(
            latency_entry_base_unit=payload.latency_entry_base_unit,
            latency_entry=payload.latency_entry,
            bw_entry_base_unit=payload.bw_entry_base_unit,
            bw_entry=payload.bw_entry,
        )

        await callback(50)

        rc = self._pbr_switch_manager.configure_pid_binding(
            op, payload.target_vcs, payload.target_vppb, payload.pid, hmat
        )

        await callback(100)

        if rc != CCI_RETURN_CODE.SUCCESS:
            return CciResponse(return_code=rc)
        return CciResponse()

    @staticmethod
    def create_cci_request(request: ConfigurePidBindingRequestPayload) -> CciRequest:
        req = CciRequest()
        req.opcode = ConfigurePidBindingCommand.OPCODE
        req.payload = request.dump()
        return req

    @staticmethod
    def parse_request_payload(data: bytes) -> ConfigurePidBindingRequestPayload:
        return ConfigurePidBindingRequestPayload.parse(data)
