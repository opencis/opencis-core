"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from dataclasses import dataclass, field
from struct import pack, unpack
from typing import List, Tuple

# from opencis.util.logger import logger
from opencis.cxl.component.cci_executor import (
    CciRequest,
    CciResponse,
    CciForegroundCommand,
)
from opencis.cxl.cci.common import CCI_FM_API_COMMAND_OPCODE

# pylint: disable=duplicate-code


@dataclass
class SetLdAllocationsRequestPayload:
    number_of_lds: int = field(default=0)  # 1byte
    start_ld_id: int = field(default=0)  # 1byte
    ld_allocation_list: List[Tuple[int, int]] = field(default_factory=list)  # variable length

    @classmethod
    def parse(cls, data: bytes):
        number_of_lds, start_ld_id = unpack("<BB", data[:2])
        ld_allocation_list_data = data[4:]
        ld_allocation_list = []
        for i in range(
            0, len(ld_allocation_list_data), 16
        ):  # 8 bytes for range1 + 8 bytes for range2
            if i + 16 <= len(ld_allocation_list_data):
                range_1, range_2 = unpack("<QQ", ld_allocation_list_data[i : i + 16])
                ld_allocation_list.append((range_1, range_2))
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
    ld_allocation_list: List[Tuple[int, int]] = field(default_factory=list)  # variable length

    @classmethod
    def parse(cls, data: bytes):
        number_of_lds, start_ld_id = unpack("<BB", data[:2])
        ld_allocation_list_data = data[4:]
        ld_allocation_list = []
        for i in range(
            0, len(ld_allocation_list_data), 16
        ):  # 8 bytes for range1 + 8 bytes for range2
            if i + 16 <= len(ld_allocation_list_data):
                range_1, range_2 = unpack("<QQ", ld_allocation_list_data[i : i + 16])
                ld_allocation_list.append((range_1, range_2))
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


class SetLdAllocationsCommand(CciForegroundCommand):
    OPCODE = CCI_FM_API_COMMAND_OPCODE.SET_LD_ALLOCATIONS

    def __init__(
        self,
        virtual_switch_manager=None,
    ):
        super().__init__(self.OPCODE)
        self._virtual_switch_manager = virtual_switch_manager

    async def _execute(self, request: CciRequest) -> CciResponse:
        # Parse the request payload
        request_payload = SetLdAllocationsRequestPayload.parse(request.payload)

        # Extract LD IDs from the allocation list
        # The ld_allocation_list contains tuples of (range1, range2)
        # For now, we'll extract LD IDs from range1 values
        ld_ids = []
        for range1, _range2 in request_payload.ld_allocation_list:
            # Convert range1 to LD ID (this is a simplified approach)
            # In a real implementation, you'd need to properly decode the range values
            if range1 > 0:
                ld_ids.append(range1)

        # Update the virtual switch manager with the new LD allocations
        if self._virtual_switch_manager:
            # Get port_index from the request context
            # The port_index is passed in the CCI header and should be available
            # in the request context. For now, we'll extract it from the LD IDs
            # (assuming they follow a pattern). In a real implementation,
            # this should come from the request context
            port_index = 1  # Default to port 1, but this should be extracted from request context

            # Try to get port_index from request context if available
            if hasattr(request, "port_index"):
                port_index = request.port_index
            elif hasattr(request, "context") and hasattr(request.context, "port_index"):
                port_index = request.context.port_index

            self._virtual_switch_manager.update_ld_allocations(port_index, ld_ids)

            # Log the dynamic LD creation
            from opencis.util.logger import logger

            logger.info(
                f"Dynamically created {len(ld_ids)} logical devices for port {port_index}: {ld_ids}"
            )

        # Create response
        response_payload = SetLdAllocationsResponsePayload(
            number_of_lds=request_payload.number_of_lds,
            start_ld_id=request_payload.start_ld_id,
            ld_allocation_list=request_payload.ld_allocation_list,
        )

        return CciResponse(
            return_code=0,  # SUCCESS
            payload=response_payload.dump(),
            vendor_specific_status=0,
            bo_flag=False,
        )

    @classmethod
    def create_cci_request(cls, request: SetLdAllocationsRequestPayload) -> CciRequest:
        cci_request = CciRequest()
        cci_request.opcode = cls.OPCODE
        cci_request.payload = request.dump()
        return cci_request

    @classmethod
    def parse_response_payload(cls, payload: bytes) -> SetLdAllocationsResponsePayload:
        return SetLdAllocationsResponsePayload.parse(payload)
