"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.

Get DRT — Opcode 5708h
Section 7.7.13.9, CXL Specification Rev 4.0 Version 1.0

Reads entries from a DPID Routing Table (DRT) in a PBR switch.

DRT model:
  - A PBR switch may have multiple DRT tables (reported by Identify PBR Switch).
  - Each DRT is a flat array of 4096 entries, indexed by DPID (12-bit PID).
  - The DPID in the PBR TLP Header (PTH) of an incoming packet is used as an
    index to look up the egress physical port (or RGT entry for group routing).
  - This is NOT a port↔vPPB map — vPPB bindings are a separate HBR concept.

Input Payload (Table 7-131):
  Byte 0x00  len=1   DRT Index: which DRT table to read
  Byte 0x01  len=1   Reserved
  Byte 0x02  len=2   Number of Entries to read
  Byte 0x04  len=2   Start Entry (starting DPID index into the DRT)

Output Payload (Table 7-132):
  Byte 0x00  len=1   DRT Index
  Byte 0x01  len=1   Reserved
  Byte 0x02  len=2   Number of Entries returned
  Byte 0x04  len=2   Start Entry
  Byte 0x06  len=1   Associated RGT Index
  Byte 0x07  len=1   Reserved
  Byte 0x08  varies  DRT Entry List (Table 7-133 × Number of Entries)

DRT Entry (Table 7-133) — 2 bytes each:
  Byte 0: Bits[1:0] = Entry Type (00=Invalid, 01=Physical Port, 10=RGT Index)
  Byte 1: Routing Target (port number OR RGT entry index)

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
class GetDrtRequestPayload:
    drt_index: int = 0
    num_entries: int = 0
    start_entry: int = 0

    def dump(self) -> bytes:
        data = bytearray(6)
        data[0x00] = self.drt_index & 0xFF
        # 0x01 reserved
        data[0x02:0x04] = pack("<H", self.num_entries)
        data[0x04:0x06] = pack("<H", self.start_entry)
        return bytes(data)

    @classmethod
    def parse(cls, data: bytes) -> "GetDrtRequestPayload":
        if len(data) < 6:
            raise ValueError("GetDrtRequestPayload: need 6 bytes")
        drt_index = data[0x00]
        num_entries = unpack_from("<H", data, 0x02)[0]
        start_entry = unpack_from("<H", data, 0x04)[0]
        return cls(drt_index=drt_index, num_entries=num_entries, start_entry=start_entry)


@dataclass
class GetDrtResponsePayload:
    drt_index: int = 0
    num_entries: int = 0
    start_entry: int = 0
    associated_rgt_index: int = 0
    entries: List[DrtEntry] = field(default_factory=list)

    HEADER_SIZE = 8  # bytes before the entry list

    def dump(self) -> bytes:
        header = bytearray(self.HEADER_SIZE)
        header[0x00] = self.drt_index & 0xFF
        # 0x01 reserved
        header[0x02:0x04] = pack("<H", len(self.entries))
        header[0x04:0x06] = pack("<H", self.start_entry)
        header[0x06] = self.associated_rgt_index & 0xFF
        # 0x07 reserved
        entry_bytes = b"".join(e.dump() for e in self.entries)
        return bytes(header) + entry_bytes

    @classmethod
    def parse(cls, data: bytes) -> "GetDrtResponsePayload":
        if len(data) < cls.HEADER_SIZE:
            raise ValueError(f"GetDrtResponsePayload: need at least {cls.HEADER_SIZE} bytes")
        drt_index = data[0x00]
        num_entries = unpack_from("<H", data, 0x02)[0]
        start_entry = unpack_from("<H", data, 0x04)[0]
        assoc_rgt = data[0x06]
        entries = []
        offset = cls.HEADER_SIZE
        for _ in range(num_entries):
            if offset + 2 > len(data):
                raise ValueError("GetDrtResponsePayload: truncated entry list")
            entries.append(DrtEntry.parse(data, offset))
            offset += 2
        return cls(
            drt_index=drt_index,
            num_entries=num_entries,
            start_entry=start_entry,
            associated_rgt_index=assoc_rgt,
            entries=entries,
        )

    def get_pretty_print(self) -> str:
        lines = [
            f"- DRT Index:          {self.drt_index}",
            f"- Start Entry (DPID): {self.start_entry:#05x}",
            f"- Num Entries:        {len(self.entries)}",
            f"- Assoc RGT Index:    {self.associated_rgt_index}",
        ]
        for i, e in enumerate(self.entries):
            dpid = self.start_entry + i
            lines.append(
                f"  [{dpid:#05x}] type={e.entry_type.name} target={e.routing_target}"
            )
        return "\n".join(lines)


class GetDrtCommand(CciForegroundCommand):
    """
    CCI foreground command for Get DRT (Opcode 5708h).

    Reads a slice of a DRT from PbrSwitchManager and returns it.
    The DRT is indexed by DPID; entries map DPID → egress port.
    """

    OPCODE = CCI_FM_API_COMMAND_OPCODE.GET_DRT

    def __init__(self, pbr_switch_manager: PbrSwitchManager):
        super().__init__(self.OPCODE)
        self._pbr_switch_manager = pbr_switch_manager

    async def _execute(self, request: CciRequest) -> CciResponse:
        try:
            req_payload = GetDrtRequestPayload.parse(request.payload)
        except ValueError as e:
            logger.error(self._create_message(f"parse error: {e}"))
            return CciResponse(return_code=CCI_RETURN_CODE.INVALID_INPUT)

        result = self._pbr_switch_manager.get_drt(
            req_payload.drt_index,
            req_payload.start_entry,
            req_payload.num_entries,
        )

        if result is None:
            return CciResponse(return_code=CCI_RETURN_CODE.INVALID_INPUT)

        entries, assoc_rgt = result
        resp_payload = GetDrtResponsePayload(
            drt_index=req_payload.drt_index,
            num_entries=len(entries),
            start_entry=req_payload.start_entry,
            associated_rgt_index=assoc_rgt,
            entries=entries,
        )

        response = CciResponse()
        response.payload = resp_payload.dump()
        return response

    @staticmethod
    def create_cci_request(request: GetDrtRequestPayload) -> CciRequest:
        req = CciRequest()
        req.opcode = GetDrtCommand.OPCODE
        req.payload = request.dump()
        return req

    @staticmethod
    def parse_response_payload(data: bytes) -> GetDrtResponsePayload:
        return GetDrtResponsePayload.parse(data)
