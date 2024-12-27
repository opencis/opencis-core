"""
 Copyright (c) 2024, Eeum, Inc.

 This software is licensed under the terms of the Revised BSD License.
 See LICENSE for details.
"""

from dataclasses import dataclass, field, fields
from enum import IntEnum
from typing import List, TypedDict
from yaml import dump

from opencis.cxl.component.cci_executor import (
    CciRequest,
    CciResponse,
    CciForegroundCommand,
)
from opencis.cxl.cci.common import CCI_FM_API_COMMAND_OPCODE, CCI_RETURN_CODE
from opencis.cxl.component.virtual_switch_manager import (
    VirtualSwitchManager,
)
from opencis.cxl.component.virtual_switch.virtual_switch import (
    PPB_BINDING_STATUS,
)

# pylint: disable=duplicate-code


class VCS_STATE(IntEnum):
    DISABLED = 0x00
    ENABLED = 0x01
    INVALID_VCS_ID = 0xFF


"""
Request Data Class
"""


@dataclass
class GetVirtualCxlSwitchInfoRequestPayload:
    start_vppb: int
    vppb_list_limit: int
    vcs_id_list: List[int] = field(default_factory=list)

    @classmethod
    def parse(cls, data: bytes) -> "GetVirtualCxlSwitchInfoRequestPayload":
        start_vppb = data[0]
        vppb_list_limit = data[1]
        vcs_id_list = list(data[3:])
        return cls(start_vppb, vppb_list_limit, vcs_id_list)

    def dump(self) -> bytes:
        number_of_vcss = len(self.vcs_id_list)
        header = bytes([self.start_vppb, self.vppb_list_limit, number_of_vcss])
        vcs_id_list_bytes = bytes(self.vcs_id_list)
        return header + vcs_id_list_bytes

    def get_pretty_print(self) -> str:
        fields_str = "\n".join(
            f"- {field.name}: {getattr(self, field.name)}"
            for field in fields(self)
            if field.name != "number_of_vcss"
        )
        return fields_str + f"\n- number_of_vcss: {len(self.vcs_id_list)}"


"""
Response Data Class
"""


class PpbInfoDict(TypedDict):
    vppbId: int
    bindingStatus: str
    boundPortId: int
    boundLdId: int


@dataclass
class PpbInfo:
    vppb_id: int  # Excluded from dump
    binding_status: PPB_BINDING_STATUS
    bound_port_id: int
    bound_ld_id: int = 0xFF

    @classmethod
    def parse(cls, data: bytes, start: int, vppb_id: int) -> "PpbInfo":
        return cls(
            vppb_id,
            binding_status=PPB_BINDING_STATUS(data[start]),
            bound_port_id=data[start + 1],
            bound_ld_id=data[start + 2],
        )

    def dump(self) -> bytes:
        return bytes(
            [self.binding_status, self.bound_port_id, self.bound_ld_id, 0xFF]
        )  # Assuming 0xFF for reserved byte

    def get_pretty_print(self) -> str:
        return (
            f"    - vppb_id: {self.vppb_id}\n"
            f"    - binding_status: {self.binding_status.name}\n"
            f"    - bound_port_id: {self.bound_port_id}\n"
            f"    - bound_ld_id: {self.bound_ld_id}"
        )

    def to_dict(self) -> PpbInfoDict:
        return {
            "vppbId": self.vppb_id,
            "bindingStatus": self.binding_status.name,
            "boundPortId": self.bound_port_id,
            "boundLdId": self.bound_ld_id,
        }


class VcsInfoBlockDict(TypedDict):
    vcsId: int
    vcsState: str
    uspId: int
    numOfVppbs: int
    ppbInfoList: List[PpbInfoDict]


@dataclass
class VcsInfoBlock:
    vcs_id: int
    vcs_state: VCS_STATE
    usp_id: int
    num_of_vppbs: int
    ppb_info_list: List[PpbInfo] = field(default_factory=list)

    @classmethod
    def parse(
        cls, data: bytes, start: int, start_vppb: int, vppb_list_limit: int
    ) -> "VcsInfoBlock":
        vcs_id = data[start]
        vcs_state = VCS_STATE(data[start + 1])
        usp_id = data[start + 2]
        num_of_vppbs = data[start + 3]
        ppb_info_list = [
            PpbInfo.parse(data, start + 4 + i * 4, start_vppb + i)
            for i in range(min(vppb_list_limit, num_of_vppbs - start_vppb))
        ]
        return cls(vcs_id, vcs_state, usp_id, num_of_vppbs, ppb_info_list)

    def dump(self) -> bytes:
        ppb_dump = b"".join(ppb.dump() for ppb in self.ppb_info_list)
        return bytes([self.vcs_id, self.vcs_state, self.usp_id, self.num_of_vppbs]) + ppb_dump

    def get_pretty_print(self) -> str:
        return (
            f"  - vcs_id: {self.vcs_id}\n"
            f"  - vcs_state: {self.vcs_state.name}\n"
            f"  - usp_id: {self.usp_id}\n"
            f"  - num_of_vppbs: {self.num_of_vppbs}\n"
            f"  - ppb_info_list:\n"
            + "\n".join(f"{ppb.get_pretty_print()}" for ppb in self.ppb_info_list)
        )

    def to_dict(self) -> VcsInfoBlockDict:
        return {
            "virtualCxlSwitchId": self.vcs_id,
            "vcsState": self.vcs_state.name,
            "uspId": self.usp_id,
            "numOfVppbs": self.num_of_vppbs,
            "vppbs": [ppb_info.to_dict() for ppb_info in self.ppb_info_list],
        }


class GetVirtualCxlSwitchInfoResponsePayloadDict(TypedDict):
    numberOfVcss: int
    vcsInfoList: List[VcsInfoBlockDict]


@dataclass
class GetVirtualCxlSwitchInfoResponsePayload:
    number_of_vcss: int
    vcs_info_list: List[VcsInfoBlock] = field(default_factory=list)

    # NOTE: The CXL Specification assumes "vppb_list_limit", which is part of
    # the request payload to be used when parsing the response payload.
    #
    # See the details of how vppb_list_limit is used from CXL 3.0 Table 7-27.
    #
    # Paul Kang believes the way how the spec uses vppb_list_limit when parsing
    # the response payload is poorly designed, and vppb_list_limit should be
    # part of the the response payload so that the parser for response payload
    # can be designed independent of the request payload.

    @classmethod
    def parse(
        cls, data: bytes, start_vppb: int, vppb_list_limit: int
    ) -> "GetVirtualCxlSwitchInfoResponsePayload":
        number_of_vcss = data[0]
        vcs_info_list = []
        offset = 4
        for _ in range(number_of_vcss):
            vcs_info_block = VcsInfoBlock.parse(data, offset, start_vppb, vppb_list_limit)
            vcs_info_list.append(vcs_info_block)
            offset += 4 + vcs_info_block.num_of_vppbs * 4
        return cls(number_of_vcss, vcs_info_list)

    def dump(self) -> bytes:
        header = bytes([self.number_of_vcss]) + b"\x00\x00\x00"
        vcs_info_dump = b"".join(vcs_info.dump() for vcs_info in self.vcs_info_list)
        return header + vcs_info_dump

    def get_pretty_print(self) -> str:
        return dump(self.to_dict(), sort_keys=False, default_flow_style=False)

    def to_dict(self) -> GetVirtualCxlSwitchInfoResponsePayloadDict:
        return {
            "vcsInfoList": [vcs_info.to_dict() for vcs_info in self.vcs_info_list],
        }


class GetVirtualCxlSwitchInfoCommand(CciForegroundCommand):
    OPCODE = CCI_FM_API_COMMAND_OPCODE.GET_VIRTUAL_CXL_SWITCH_INFO

    def __init__(
        self,
        virtual_switch_manager: VirtualSwitchManager,
    ):
        self._virtual_switch_manager = virtual_switch_manager
        super().__init__(self.OPCODE)

    async def _execute(self, request: CciRequest) -> CciResponse:
        request_payload = self.parse_request_payload(request.payload)

        if request_payload.vppb_list_limit < 1:
            return CciResponse(return_code=CCI_RETURN_CODE.INVALID_INPUT)

        vcs_count = self._virtual_switch_manager.get_virtual_switch_counts()
        vcs_info_list = []
        for vcs_id in request_payload.vcs_id_list:
            if vcs_id >= vcs_count:
                return CciResponse(return_code=CCI_RETURN_CODE.INVALID_INPUT)
            vcs = self._virtual_switch_manager.get_virtual_switch(vcs_id)
            vcs_state = VCS_STATE.ENABLED
            usp_id = vcs.get_usp_port_id()
            num_of_vppbs = vcs.get_vppb_counts()
            ppb_info_list = []
            start_vppb = request_payload.start_vppb
            stop_vppb = start_vppb + request_payload.vppb_list_limit
            for vppb_id in range(start_vppb, stop_vppb):
                if vppb_id >= num_of_vppbs:
                    break
                binding_status = (
                    PPB_BINDING_STATUS.BOUND_LD
                    if vcs.is_vppb_bound(vppb_id)
                    else PPB_BINDING_STATUS.UNBOUND
                )
                bound_port_id = (
                    vcs.get_bound_port_id(vppb_id)
                    if binding_status == PPB_BINDING_STATUS.BOUND_LD
                    else 0
                )
                if binding_status == PPB_BINDING_STATUS.BOUND_LD:
                    bound_ld_id = vcs.get_ld_id(vppb_id)
                else:
                    bound_ld_id = 0
                ppb_info = PpbInfo(vppb_id, binding_status, bound_port_id, bound_ld_id)
                ppb_info_list.append(ppb_info)
            vcs_info = VcsInfoBlock(vcs_id, vcs_state, usp_id, num_of_vppbs, ppb_info_list)
            vcs_info_list.append(vcs_info)

        response_payload = GetVirtualCxlSwitchInfoResponsePayload(
            number_of_vcss=len(vcs_info_list), vcs_info_list=vcs_info_list
        )
        response = self.create_cci_response(response_payload)
        return response

    @classmethod
    def create_cci_request(
        cls,
        request: GetVirtualCxlSwitchInfoRequestPayload,
    ) -> CciRequest:
        cci_request = CciRequest()
        cci_request.opcode = cls.OPCODE
        cci_request.payload = request.dump()
        return cci_request

    @staticmethod
    def create_cci_response(
        response: GetVirtualCxlSwitchInfoResponsePayload,
    ) -> CciResponse:
        cci_response = CciResponse()
        cci_response.payload = response.dump()
        return cci_response

    @staticmethod
    def parse_request_payload(payload: bytes) -> GetVirtualCxlSwitchInfoRequestPayload:
        return GetVirtualCxlSwitchInfoRequestPayload.parse(payload)

    @staticmethod
    def parse_response_payload(
        payload: bytes,
        start_vppb: int,
        vppb_list_limit: int,
    ) -> GetVirtualCxlSwitchInfoResponsePayload:
        return GetVirtualCxlSwitchInfoResponsePayload.parse(payload, start_vppb, vppb_list_limit)
