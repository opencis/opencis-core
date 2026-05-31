"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.

Set DRT — Opcode 5709h
Section 7.7.13.10, CXL Specification Rev 4.0 Version 1.0

Writes entries into a DPID Routing Table (DRT) in a PBR switch.

DRT model:
  - The DRT maps DPID → egress physical port (or RGT index for multicast).
  - The FM programs this after assigning PIDs via Configure PID Assignment
    (5704h), since PID assignment does NOT auto-populate the DRT.
  - Workflow:
      1. FM: Configure PID Assignment (5704h) — assigns PID to a target
      2. FM: Set DRT (5709h) — programs DRT[drt_index][pid] = {type, port}
      3. Switch HW: uses DRT to route incoming TLPs by DPID

Input Payload (Table 7-134):
  Byte 0x00  len=1   DRT Index: which DRT table to write
  Byte 0x01  len=1   Reserved
  Byte 0x02  len=2   Number of Entries
  Byte 0x04  len=2   Start Entry (starting DPID index into the DRT)
  Byte 0x06  varies  DRT Entry List (Table 7-133 × Number of Entries)

DRT Entry (Table 7-133) — 2 bytes each:
  Byte 0: Bits[1:0] = Entry Type (00=Invalid, 01=Physical Port, 10=RGT Index)
  Byte 1: Routing Target (port number OR RGT entry index)

Output Payload: None

Return codes: Success, Unsupported, Invalid Input, Internal Error, Retry Required
"""

from dataclasses import dataclass, field
from struct import pack, unpack_from
from typing import List

from opencis.cxl.cci.common import CCI_FM_API_COMMAND_OPCODE, CCI_RETURN_CODE
from opencis.cxl.component.cci_executor import CciRequest, CciResponse, CciForegroundCommand
from opencis.cxl.component.pbr_switch_manager import DrtEntry, PbrSwitchManager
from opencis.util.logger import logger


@dataclass
class SetDrtRequestPayload:
    drt_index: int = 0
    start_entry: int = 0
    entries: List[DrtEntry] = field(default_factory=list)

    def dump(self) -> bytes:
        header = bytearray(6)
        header[0x00] = self.drt_index & 0xFF
        # 0x01 reserved
        header[0x02:0x04] = pack("<H", len(self.entries))
        header[0x04:0x06] = pack("<H", self.start_entry)
        entry_bytes = b"".join(e.dump() for e in self.entries)
        return bytes(header) + entry_bytes

    @classmethod
    def parse(cls, data: bytes) -> "SetDrtRequestPayload":
        if len(data) < 6:
            raise ValueError("SetDrtRequestPayload: need at least 6 bytes")
        drt_index = data[0x00]
        num_entries = unpack_from("<H", data, 0x02)[0]
        start_entry = unpack_from("<H", data, 0x04)[0]
        entries = []
        offset = 6
        for _ in range(num_entries):
            if offset + 2 > len(data):
                raise ValueError("SetDrtRequestPayload: truncated entry list")
            entries.append(DrtEntry.parse(data, offset))
            offset += 2
        return cls(drt_index=drt_index, start_entry=start_entry, entries=entries)


class SetDrtCommand(CciForegroundCommand):
    """
    CCI foreground command for Set DRT (Opcode 5709h).

    Writes DRT entries into PbrSwitchManager. This is the mechanism by which
    the FM programs the DPID → egress-port routing table after PID assignment.

    The DRT entry at index DPID tells the switch hardware where to send packets
    that arrive with that DPID in the PBR TLP Header (PTH).
    """

    OPCODE = CCI_FM_API_COMMAND_OPCODE.SET_DRT

    def __init__(self, pbr_switch_manager: PbrSwitchManager):
        super().__init__(self.OPCODE)
        self._pbr_switch_manager = pbr_switch_manager

    async def _execute(self, request: CciRequest) -> CciResponse:
        try:
            payload = SetDrtRequestPayload.parse(request.payload)
        except ValueError as e:
            logger.error(self._create_message(f"parse error: {e}"))
            return CciResponse(return_code=CCI_RETURN_CODE.INVALID_INPUT)

        rc = self._pbr_switch_manager.set_drt(
            payload.drt_index,
            payload.start_entry,
            payload.entries,
        )

        if rc != CCI_RETURN_CODE.SUCCESS:
            return CciResponse(return_code=rc)
        return CciResponse()

    @staticmethod
    def create_cci_request(request: SetDrtRequestPayload) -> CciRequest:
        req = CciRequest()
        req.opcode = SetDrtCommand.OPCODE
        req.payload = request.dump()
        return req

    @staticmethod
    def parse_request_payload(data: bytes) -> SetDrtRequestPayload:
        return SetDrtRequestPayload.parse(data)
