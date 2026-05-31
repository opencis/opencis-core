"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.

Configure PID Assignment — Opcode 5704h
Section 7.7.13.5, CXL Specification Rev 4.0 Version 1.0

Assigns or clears PIDs on targets within a PBR switch.

IMPORTANT: This command does NOT update DRT entries. The FM must separately
call Set DRT (5709h) after assigning PIDs to enable actual packet routing.

Input Payload (Table 7-123):
  Byte 0x00  len=1   Operation (Bits[2:0]: 000b=Assign, 001b=Clear)
  Byte 0x01  len=1   Reserved
  Byte 0x02  len=2   Number of Targets
  Byte 0x04  varies  PID Assignment List (Table 7-124 entries)

PID Assignment Entry (Table 7-124):
  Byte 0x00  len=2   PID (Bits[11:0])
  Byte 0x02  len=2   Target ID
  Byte 0x04  len=1   Instance ID
  Total: 5 bytes per entry

Output Payload: None (empty on success)

Return codes: Success, Unsupported, Invalid Input, Internal Error, Retry Required
"""

from dataclasses import dataclass, field
from struct import pack, unpack_from
from typing import List

from opencis.cxl.cci.common import CCI_FM_API_COMMAND_OPCODE, CCI_RETURN_CODE
from opencis.cxl.component.cci_executor import CciRequest, CciResponse, CciForegroundCommand
from opencis.cxl.component.pbr_switch_manager import PbrSwitchManager
from opencis.util.logger import logger


class PidAssignmentOperation:
    ASSIGN = 0b000
    CLEAR = 0b001


@dataclass
class PidAssignmentEntry:
    """One entry in the PID Assignment List (Table 7-124). 5 bytes on wire."""
    pid: int = 0           # Bits[11:0]
    target_id: int = 0     # 2 bytes
    instance_id: int = 0   # 1 byte

    ENTRY_SIZE = 5

    def dump(self) -> bytes:
        data = bytearray(self.ENTRY_SIZE)
        data[0:2] = pack("<H", self.pid & 0x0FFF)
        data[2:4] = pack("<H", self.target_id)
        data[4] = self.instance_id & 0xFF
        return bytes(data)

    @classmethod
    def parse(cls, data: bytes, offset: int = 0) -> "PidAssignmentEntry":
        pid = unpack_from("<H", data, offset)[0] & 0x0FFF
        target_id = unpack_from("<H", data, offset + 2)[0]
        instance_id = data[offset + 4]
        return cls(pid=pid, target_id=target_id, instance_id=instance_id)


@dataclass
class ConfigurePidAssignmentRequestPayload:
    operation: int = PidAssignmentOperation.ASSIGN  # Bits[2:0]
    entries: List[PidAssignmentEntry] = field(default_factory=list)

    def dump(self) -> bytes:
        header = bytearray(4)
        header[0] = self.operation & 0x07
        # byte 1 reserved
        header[2:4] = pack("<H", len(self.entries))
        body = b"".join(e.dump() for e in self.entries)
        return bytes(header) + body

    @classmethod
    def parse(cls, data: bytes) -> "ConfigurePidAssignmentRequestPayload":
        if len(data) < 4:
            raise ValueError("ConfigurePidAssignmentRequestPayload: too short")
        operation = data[0] & 0x07
        num_targets = unpack_from("<H", data, 2)[0]
        entries = []
        offset = 4
        for _ in range(num_targets):
            if offset + PidAssignmentEntry.ENTRY_SIZE > len(data):
                raise ValueError("ConfigurePidAssignmentRequestPayload: truncated entry list")
            entries.append(PidAssignmentEntry.parse(data, offset))
            offset += PidAssignmentEntry.ENTRY_SIZE
        return cls(operation=operation, entries=entries)


class ConfigurePidAssignmentCommand(CciForegroundCommand):
    """
    CCI foreground command for Configure PID Assignment (Opcode 5704h).

    Iterates through the PID assignment list and calls PbrSwitchManager.assign_pid()
    or clear_pid() for each entry. Fails fast on any INVALID_INPUT.

    The DRT is NOT updated here — the FM is responsible for issuing Set DRT
    (5709h) afterwards to program the routing entries for the assigned PIDs.
    """

    OPCODE = CCI_FM_API_COMMAND_OPCODE.CONFIGURE_PID_ASSIGNMENT

    def __init__(self, pbr_switch_manager: PbrSwitchManager):
        super().__init__(self.OPCODE)
        self._pbr_switch_manager = pbr_switch_manager

    async def _execute(self, request: CciRequest) -> CciResponse:
        try:
            payload = ConfigurePidAssignmentRequestPayload.parse(request.payload)
        except ValueError as e:
            logger.error(self._create_message(f"parse error: {e}"))
            return CciResponse(return_code=CCI_RETURN_CODE.INVALID_INPUT)

        for entry in payload.entries:
            if payload.operation == PidAssignmentOperation.ASSIGN:
                rc = self._pbr_switch_manager.assign_pid(
                    entry.pid, entry.target_id, entry.instance_id
                )
            elif payload.operation == PidAssignmentOperation.CLEAR:
                rc = self._pbr_switch_manager.clear_pid(
                    entry.pid, entry.target_id, entry.instance_id
                )
            else:
                logger.error(self._create_message(f"unknown operation {payload.operation}"))
                return CciResponse(return_code=CCI_RETURN_CODE.INVALID_INPUT)

            if rc != CCI_RETURN_CODE.SUCCESS:
                return CciResponse(return_code=rc)

        return CciResponse()

    @staticmethod
    def create_cci_request(request: ConfigurePidAssignmentRequestPayload) -> CciRequest:
        req = CciRequest()
        req.opcode = ConfigurePidAssignmentCommand.OPCODE
        req.payload = request.dump()
        return req

    @staticmethod
    def parse_request_payload(data: bytes) -> ConfigurePidAssignmentRequestPayload:
        return ConfigurePidAssignmentRequestPayload.parse(data)
