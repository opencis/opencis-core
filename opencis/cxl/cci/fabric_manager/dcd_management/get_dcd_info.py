"""
Copyright (c) 2024, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from dataclasses import dataclass
import struct

from opencis.cxl.cci.common import CCI_FM_API_COMMAND_OPCODE
from opencis.cxl.component.cci_executor import (
    CciRequest,
    CciResponse,
    CciForegroundCommand,
)
from opencis.cxl.component.physical_port_manager import PhysicalPortManager
from opencis.cxl.component.virtual_switch_manager import VirtualSwitchManager


@dataclass
class GetDcdInfoResponsePayload:
    num_hosts: int = 0
    num_supported_dc_regions: int = 0
    reserved1: int = 0
    add_capacity_selection_policies: int = 0
    reserved2: int = 0
    release_capacity_removal_policies: int = 0
    reserved3: int = 0
    sanitize: int = 0
    reserved4: int = 0
    total_dynamic_capacity: int = 0
    reserved5: int = 0
    region0_block_size_mask: int = 0
    region1_block_size_mask: int = 0
    region2_block_size_mask: int = 0
    region3_block_size_mask: int = 0
    region4_block_size_mask: int = 0
    region5_block_size_mask: int = 0
    region6_block_size_mask: int = 0
    region7_block_size_mask: int = 0
    pack_mask: str = "<BBHHHHBBQQQQQQQQQ"

    @classmethod
    def parse(cls, data: bytes) -> "GetDcdInfoResponsePayload":
        if len(data) != struct.calcsize(cls.pack_mask):
            raise ValueError("Data is too short to parse.")
        (
            num_hosts,
            num_supported_dc_regions,
            reserved1,
            add_capacity_selection_policies,
            reserved2,
            release_capacity_removal_policies,
            reserved3,
            sanitize,
            reserved4,
            total_dynamic_capacity,
            reserved5,
            region0_block_size_mask,
            region1_block_size_mask,
            region2_block_size_mask,
            region3_block_size_mask,
            region4_block_size_mask,
            region5_block_size_mask,
            region6_block_size_mask,
            region7_block_size_mask,
        ) = struct.unpack(cls.pack_mask, data)

        return cls(
            num_hosts=num_hosts,
            num_supported_dc_regions=num_supported_dc_regions,
            reserved1=reserved1,
            add_capacity_selection_policies=add_capacity_selection_policies,
            reserved2=reserved2,
            release_capacity_removal_policies=release_capacity_removal_policies,
            reserved3=reserved3,
            sanitize=sanitize,
            reserved4=reserved4,
            total_dynamic_capacity=total_dynamic_capacity,
            reserved5=reserved5,
            region0_block_size_mask=region0_block_size_mask,
            region1_block_size_mask=region1_block_size_mask,
            region2_block_size_mask=region2_block_size_mask,
            region3_block_size_mask=region3_block_size_mask,
            region4_block_size_mask=region4_block_size_mask,
            region5_block_size_mask=region5_block_size_mask,
            region6_block_size_mask=region6_block_size_mask,
            region7_block_size_mask=region7_block_size_mask,
        )

    def dump(self) -> bytes:
        databytes = struct.pack(
            self.pack_mask,
            self.num_hosts,
            self.num_supported_dc_regions,
            self.reserved1,
            self.add_capacity_selection_policies,
            self.reserved2,
            self.release_capacity_removal_policies,
            self.reserved3,
            self.sanitize,
            self.reserved4,
            self.total_dynamic_capacity,
            self.reserved5,
            self.region0_block_size_mask,
            self.region1_block_size_mask,
            self.region2_block_size_mask,
            self.region3_block_size_mask,
            self.region4_block_size_mask,
            self.region5_block_size_mask,
            self.region6_block_size_mask,
            self.region7_block_size_mask,
        )
        return databytes

    def get_pretty_print(self) -> str:
        return (
            f"- Number of Hosts: {self.num_hosts}\n"
            f"- Number of Supported DC Regions: {self.num_supported_dc_regions}\n"
            f"- Reserved1: {self.reserved1}\n"
            f"- Add Capacity Selection Policies: {self.add_capacity_selection_policies}\n"
            f"- Reserved2: {self.reserved2}\n"
            f"- Release Capacity Removal Policies: {self.release_capacity_removal_policies}\n"
            f"- Reserved3: {self.reserved3}\n"
            f"- Sanitize: {self.sanitize}\n"
            f"- Reserved4: {self.reserved4}\n"
            f"- Total Dynamic Capacity: {self.total_dynamic_capacity}\n"
            f"- Reserved5: {self.reserved5}\n"
            f"- Region 0 Block Size Mask: {self.region0_block_size_mask}\n"
            f"- Region 1 Block Size Mask: {self.region1_block_size_mask}\n"
            f"- Region 2 Block Size Mask: {self.region2_block_size_mask}\n"
            f"- Region 3 Block Size Mask: {self.region3_block_size_mask}\n"
            f"- Region 4 Block Size Mask: {self.region4_block_size_mask}\n"
            f"- Region 5 Block Size Mask: {self.region5_block_size_mask}\n"
            f"- Region 6 Block Size Mask: {self.region6_block_size_mask}\n"
            f"- Region 7 Block Size Mask: {self.region7_block_size_mask}"
        )


class GetDcdInfoCommand(CciForegroundCommand):
    def __init__(
        self,
        physical_port_manager: PhysicalPortManager,
        virtual_switch_manager: VirtualSwitchManager,
    ):
        self._physical_port_manager = physical_port_manager
        self._virtual_switch_manager = virtual_switch_manager
        super().__init__(CCI_FM_API_COMMAND_OPCODE.GET_DCD_INFO)

    async def _execute(self, _: CciRequest) -> CciResponse:
        #######################################################
        # TODO: Add code that will get the following variables
        # WILL NOT WORK WITHOUT IMPLEMENTATION
        num_hosts = 0
        num_supported_dc_regions = 0
        reserved1 = 0
        add_capacity_selection_policies = 0
        reserved2 = 0
        release_capacity_removal_policies = 0
        reserved3 = 0
        sanitize = 0
        reserved4 = 0
        total_dynamic_capacity = 0
        reserved5 = 0
        region0_block_size_mask = 0
        region1_block_size_mask = 0
        region2_block_size_mask = 0
        region3_block_size_mask = 0
        region4_block_size_mask = 0
        region5_block_size_mask = 0
        region6_block_size_mask = 0
        region7_block_size_mask = 0
        #######################################################

        response_payload = GetDcdInfoResponsePayload(
            num_hosts=num_hosts,
            num_supported_dc_regions=num_supported_dc_regions,
            reserved1=reserved1,
            add_capacity_selection_policies=add_capacity_selection_policies,
            reserved2=reserved2,
            release_capacity_removal_policies=release_capacity_removal_policies,
            reserved3=reserved3,
            sanitize=sanitize,
            reserved4=reserved4,
            total_dynamic_capacity=total_dynamic_capacity,
            reserved5=reserved5,
            region0_block_size_mask=region0_block_size_mask,
            region1_block_size_mask=region1_block_size_mask,
            region2_block_size_mask=region2_block_size_mask,
            region3_block_size_mask=region3_block_size_mask,
            region4_block_size_mask=region4_block_size_mask,
            region5_block_size_mask=region5_block_size_mask,
            region6_block_size_mask=region6_block_size_mask,
            region7_block_size_mask=region7_block_size_mask,
        )
        response = self.create_cci_response(response_payload)
        return response

    @staticmethod
    def create_cci_request() -> CciRequest:
        cci_request = CciRequest()
        cci_request.opcode = CCI_FM_API_COMMAND_OPCODE.GET_DCD_INFO
        return cci_request

    @staticmethod
    def create_cci_response(
        response: GetDcdInfoResponsePayload,
    ) -> CciResponse:
        cci_response = CciResponse()
        cci_response.payload = response.dump()
        return cci_response

    @staticmethod
    def parse_response_payload(payload: bytes) -> GetDcdInfoResponsePayload:
        return GetDcdInfoResponsePayload.parse(payload)
