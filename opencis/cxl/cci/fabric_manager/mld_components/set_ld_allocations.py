"""
 Copyright (c) 2024, Eeum, Inc.

 This software is licensed under the terms of the Revised BSD License.
 See LICENSE for details.
"""

from dataclasses import dataclass, field
from struct import pack, unpack

# from opencis.util.logger import logger
from opencis.cxl.component.cci_executor import (
    CciBackgroundCommand,
    CciRequest,
    CciResponse,
)
from opencis.cxl.cci.common import CCI_FM_API_COMMAND_OPCODE

# pylint: disable=duplicate-code


@dataclass
class SetLdAllocationsRequestPayload:
    number_of_lds: int = field(default=0)  # 1byte
    start_ld_id: int = field(default=0)  # 1byte
    ld_allocation_list: bytes = field(default=b"")  # variable length

    @classmethod
    def parse(cls, data: bytes):
        number_of_lds, start_ld_id = unpack("<BB", data[:2])
        ld_allocation_list = data[4:]
        return cls(number_of_lds, start_ld_id, ld_allocation_list)

    def dump(self):
        data = bytearray()
        data.extend(pack("<BB", self.number_of_lds, self.start_ld_id))
        data.extend(b"\x00\x00")  # Reserve 2 bytes
        for range_1, range_2 in self.ld_allocation_list:
            data.extend(pack("<QQ", range_1, range_2))
        return bytes(data)

    def get_pretty_print(self):
        allocation_str = "\n".join(
            f"  - Range 1: {range_1}, Range 2: {range_2}"
            for range_1, range_2 in self.ld_allocation_list
        )
        return (
            f"- NUMBER_OF_LDS: {self.number_of_lds}\n"
            f"- START_LD_ID: {self.start_ld_id}\n"
            f"- LD_ALLOCATION_LIST:\n{allocation_str}"
        )


@dataclass
class SetLdAllocationsResponsePayload:
    number_of_lds: int = field(default=0)  # 1byte
    start_ld_id: int = field(default=0)
    # reversed 2 bytes
    ld_allocation_list: bytes = field(default=b"")  # variable length

    @classmethod
    def parse(cls, data: bytes):
        number_of_lds, start_ld_id = unpack("<BB", data[:2])
        ld_allocation_list = data[4:]
        return cls(number_of_lds, start_ld_id, ld_allocation_list)

    def dump(self):
        data = bytearray()
        data.extend(pack("<BB", self.number_of_lds, self.start_ld_id))
        data.extend(b"\x00\x00")
        for range_1, range_2 in self.ld_allocation_list:
            data.extend(pack("<QQ", range_1, range_2))
        return bytes(data)

    def get_pretty_print(self):
        allocation_str = "\n".join(
            f"  - Range 1: {range_1}, Range 2: {range_2}"
            for range_1, range_2 in self.ld_allocation_list
        )
        return (
            f"- NUMBER_OF_LDS: {self.number_of_lds}\n"
            f"- START_LD_ID: {self.start_ld_id}\n"
            f"- LD_ALLOCATION_LIST:\n{allocation_str}"
        )


class SetLdAllocationsCommand(CciBackgroundCommand):
    OPCODE = CCI_FM_API_COMMAND_OPCODE.SET_LD_ALLOCATIONS

    def __init__(
        self,
    ):
        super().__init__(self.OPCODE)

    async def _execute(self, request: CciRequest, callback) -> CciResponse:
        pass

    @classmethod
    def create_cci_request(cls, request: SetLdAllocationsRequestPayload) -> CciRequest:
        cci_request = CciRequest()
        cci_request.opcode = cls.OPCODE
        cci_request.payload = request.dump()
        return cci_request

    @classmethod
    def parse_response_payload(cls, payload: bytes) -> SetLdAllocationsResponsePayload:
        return SetLdAllocationsResponsePayload.parse(payload)
