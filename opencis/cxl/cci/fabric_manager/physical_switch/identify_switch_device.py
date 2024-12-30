"""
 Copyright (c) 2024, Eeum, Inc.

 This software is licensed under the terms of the Revised BSD License.
 See LICENSE for details.
"""

from dataclasses import dataclass

from opencis.cxl.cci.common import CCI_FM_API_COMMAND_OPCODE
from opencis.cxl.component.cci_executor import (
    CciRequest,
    CciResponse,
    CciForegroundCommand,
)
from opencis.cxl.component.physical_port_manager import PhysicalPortManager
from opencis.cxl.component.virtual_switch_manager import VirtualSwitchManager

"""

The following dataclasses and helper functions are genearted by ChatGPT (GPT-4)

https://chat.openai.com/share/3c1589d6-fc6a-46b1-9048-fd3b716cda30

"""


@dataclass
class IdentifySwitchDeviceResponsePayload:
    ingress_port_id: int = 0
    num_physical_ports: int = 0
    num_vcss: int = 0
    active_port_bitmask: int = 0
    active_vcs_bitmask: int = 0
    total_num_vppbs: int = 0
    num_bound_vppbs: int = 0
    num_hdm_decoders: int = 0

    @classmethod
    def parse(cls, data: bytes) -> "IdentifySwitchDeviceResponsePayload":
        if len(data) < 49:
            raise ValueError("Data is too short to parse.")

        ingress_port_id = int.from_bytes(data[0x00:0x01], "little")
        num_physical_ports = int.from_bytes(data[0x02:0x03], "little")
        num_vcss = int.from_bytes(data[0x03:0x04], "little")
        active_port_bitmask = int.from_bytes(data[0x04:0x24], "little")
        active_vcs_bitmask = int.from_bytes(data[0x24:0x44], "little")
        total_num_vppbs = int.from_bytes(data[0x44:0x46], "little")
        num_bound_vppbs = int.from_bytes(data[0x46:0x48], "little")
        num_hdm_decoders = int.from_bytes(data[0x48:0x49], "little")

        return cls(
            ingress_port_id=ingress_port_id,
            num_physical_ports=num_physical_ports,
            num_vcss=num_vcss,
            active_port_bitmask=active_port_bitmask,
            active_vcs_bitmask=active_vcs_bitmask,
            total_num_vppbs=total_num_vppbs,
            num_bound_vppbs=num_bound_vppbs,
            num_hdm_decoders=num_hdm_decoders,
        )

    def dump(self) -> bytes:
        data = bytearray(49)
        data[0x00:0x01] = self.ingress_port_id.to_bytes(1, "little")
        data[0x01:0x02] = (0).to_bytes(1, "little")  # Reserved field set to 0
        data[0x02:0x03] = self.num_physical_ports.to_bytes(1, "little")
        data[0x03:0x04] = self.num_vcss.to_bytes(1, "little")
        data[0x04:0x24] = self.active_port_bitmask.to_bytes(0x20, "little")
        data[0x24:0x44] = self.active_vcs_bitmask.to_bytes(0x20, "little")
        data[0x44:0x46] = self.total_num_vppbs.to_bytes(2, "little")
        data[0x46:0x48] = self.num_bound_vppbs.to_bytes(2, "little")
        data[0x48:0x49] = self.num_hdm_decoders.to_bytes(1, "little")

        return bytes(data)

    def get_pretty_print(self) -> str:
        return (
            f"- Ingress Port ID: {self.ingress_port_id}\n"
            f"- Number of Physical Ports: {self.num_physical_ports}\n"
            f"- Number of VCSs: {self.num_vcss}\n"
            f"- Active Port Bitmask: {self.active_port_bitmask:#034b}\n"
            f"- Active VCS Bitmask: {self.active_vcs_bitmask:#034b}\n"
            f"- Total Number of vPPBs: {self.total_num_vppbs}\n"
            f"- Number of Bound vPPBs: {self.num_bound_vppbs}\n"
            f"- Number of HDM Decoders: {self.num_hdm_decoders}"
        )


class IdentifySwitchDeviceCommand(CciForegroundCommand):
    def __init__(
        self,
        physical_port_manager: PhysicalPortManager,
        virtual_switch_manager: VirtualSwitchManager,
    ):
        self._physical_port_manager = physical_port_manager
        self._virtual_switch_manager = virtual_switch_manager
        super().__init__(CCI_FM_API_COMMAND_OPCODE.IDENTIFY_SWITCH_DEVICE)

    async def _execute(self, _: CciRequest) -> CciResponse:
        number_of_physical_ports = self._physical_port_manager.get_port_counts()
        number_of_vcss = self._virtual_switch_manager.get_virtual_switch_counts()
        response_payload = IdentifySwitchDeviceResponsePayload(
            ingress_port_id=0,
            num_physical_ports=number_of_physical_ports,
            num_vcss=number_of_vcss,
            active_port_bitmask=(1 << number_of_physical_ports) - 1,
            active_vcs_bitmask=(1 << number_of_vcss) - 1,
            total_num_vppbs=self._virtual_switch_manager.get_total_vppbs_count(),
            num_bound_vppbs=self._virtual_switch_manager.get_total_bound_vppbs_count(),
            num_hdm_decoders=self._physical_port_manager.get_usp_hdm_decoder_count(),
        )
        response = self.create_cci_response(response_payload)
        return response

    @staticmethod
    def create_cci_request() -> CciRequest:
        cci_request = CciRequest()
        cci_request.opcode = CCI_FM_API_COMMAND_OPCODE.IDENTIFY_SWITCH_DEVICE
        return cci_request

    @staticmethod
    def create_cci_response(
        response: IdentifySwitchDeviceResponsePayload,
    ) -> CciResponse:
        cci_response = CciResponse()
        cci_response.payload = response.dump()
        return cci_response

    @staticmethod
    def parse_response_payload(payload: bytes) -> IdentifySwitchDeviceResponsePayload:
        return IdentifySwitchDeviceResponsePayload.parse(payload)
