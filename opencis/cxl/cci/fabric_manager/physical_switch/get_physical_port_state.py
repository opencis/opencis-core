"""
 Copyright (c) 2024, Eeum, Inc.

 This software is licensed under the terms of the Revised BSD License.
 See LICENSE for details.
"""

from dataclasses import dataclass, field
from enum import IntEnum
from typing import List, Dict
from yaml import dump

from opencis.cxl.cci.common import CCI_FM_API_COMMAND_OPCODE, CCI_RETURN_CODE
from opencis.cxl.component.cci_executor import (
    CciForegroundCommand,
    CciRequest,
    CciResponse,
)
from opencis.cxl.component.switch_connection_manager import (
    SwitchConnectionManager,
    PORT_TYPE,
)
from opencis.cxl.device.config.logical_device import (
    LogicalDeviceConfig,
    MultiLogicalDeviceConfig,
)


class CURRENT_PORT_CONFIGURATION_STATE(IntEnum):
    DISABLED = 0x0
    BIND_IN_PROGRESS = 0x1
    UNBIND_IN_PROGRESS = 0x2
    DSP = 0x3
    USP = 0x4
    RESERVED_FABRIC_LINK = 0x5
    INVALID_PORT_ID = 0xF
    # All other encodings are reserved


class CONNECTED_DEVICE_MODE(IntEnum):
    CONNECTION_NOT_CXL_OR_DISCONNECTED = 0x0
    RCD_MODE = 0x1
    CXL_68B_FLIT_AND_VH_MODE = 0x2
    STANDARD_256B_FLIT_MODE = 0x3
    CXL_LATENCY_OPTIMIZED_256B_FLIT_MODE = 0x4
    PBR_MODE = 0x5
    # All other values are reserved for all values of Current Port Configuration State except DSP


class CONNECTED_DEVICE_TYPE(IntEnum):
    NO_DEVICE_DETECTED = 0x00
    PCIE_DEVICE = 0x01
    CXL_TYPE_1_DEVICE = 0x02
    CXL_TYPE_2_DEVICE = 0x03
    CXL_TYPE_3_SLD = 0x04
    CXL_TYPE_3_MLD = 0x05
    RESERVED_CXL_SWITCH = 0x06
    # All other encodings are reserved
    # This field is reserved if Supported CXL Modes is 00h.
    # This field is reserved for all values of Current Port Configuration State except DSP.


class SUPPORTED_CXL_MODES(IntEnum):
    RCD_MODE = 0b00001
    CXL_68B_FLIT_AND_VH_CAPABLE = 0b00010
    CXL_256B_FLIT_CAPABLE = 0b00100
    CXL_LATENCY_OPTIMIZED_256B_FLIT_CAPABLE = 0b01000
    PBR_CAPABLE = 0b10000
    # Bits[7:5] are reserved for future CXL use
    # Undefined when the value is 0x00


class LTSSM_STATE(IntEnum):
    DETECT = 0x00
    POLLING = 0x01
    CONFIGURATION = 0x02
    RECOVERY = 0x03
    L0 = 0x04
    L0S = 0x05
    L1 = 0x06
    L2 = 0x07
    DISABLED = 0x08
    LOOPBACK = 0x09
    HOT_RESET = 0x0A
    # All other encodings are reserved


"""

The following dataclasses and helper functions are genearted by ChatGPT (GPT-4)

https://chat.openai.com/share/405e3169-6aae-4863-b265-123407c3a718

"""


@dataclass
class GetPhysicalPortStateRequestPayload:
    port_id_list: List[int] = field(default_factory=list)

    @classmethod
    def parse(cls, data: bytes) -> "GetPhysicalPortStateRequestPayload":
        port_id_list = list(data[1 : 1 + data[0]])  # The first byte is the number of ports
        return cls(port_id_list=port_id_list)

    def dump(self) -> bytes:
        number_of_ports = len(self.port_id_list)
        return (
            bytes([number_of_ports])
            + bytes(self.port_id_list)
            + bytes([0] * (255 - number_of_ports))
        )

    def get_pretty_print(self) -> str:
        pretty_print_output = (
            f"- Number of Ports: {len(self.port_id_list)}\n"
            f"- Port ID List: {', '.join(str(pid) for pid in self.port_id_list)}"
        )
        return pretty_print_output


@dataclass
class PortInfo:
    port_id: int = 0
    current_port_configuration_state: CURRENT_PORT_CONFIGURATION_STATE = (
        CURRENT_PORT_CONFIGURATION_STATE.DISABLED
    )
    connected_device_mode: CONNECTED_DEVICE_MODE = (
        CONNECTED_DEVICE_MODE.CONNECTION_NOT_CXL_OR_DISCONNECTED
    )
    connected_device_type: CONNECTED_DEVICE_TYPE = CONNECTED_DEVICE_TYPE.NO_DEVICE_DETECTED
    supported_cxl_modes: int = SUPPORTED_CXL_MODES.RCD_MODE
    maximum_link_width: int = 0
    negotiated_link_width: int = 0
    supported_link_speeds_vector: int = 0
    max_link_speed: int = 0
    current_link_speed: int = 0
    ltssm_state: LTSSM_STATE = LTSSM_STATE.DETECT
    first_negotiated_lane_number: int = 0
    link_state_flags: int = 0
    supported_ld_count: int = 0

    @classmethod
    def parse(cls, data: bytes) -> "PortInfo":
        return cls(
            port_id=data[0],
            current_port_configuration_state=CURRENT_PORT_CONFIGURATION_STATE(data[1] & 0x0F),
            connected_device_mode=CONNECTED_DEVICE_MODE(data[2] & 0x0F),
            connected_device_type=CONNECTED_DEVICE_TYPE(data[4]),
            supported_cxl_modes=data[5],
            maximum_link_width=data[6] & 0x3F,
            negotiated_link_width=data[7] & 0x3F,
            supported_link_speeds_vector=data[8] & 0x3F,
            max_link_speed=data[9] & 0x3F,
            current_link_speed=data[10] & 0x3F,
            ltssm_state=LTSSM_STATE(data[11]),
            first_negotiated_lane_number=data[12],
            link_state_flags=int.from_bytes(data[13:15], "little"),
            supported_ld_count=data[15],
        )

    def dump(self) -> bytes:
        data = bytearray(16)
        data[0] = self.port_id
        data[1] = self.current_port_configuration_state & 0x0F  # Bits[3:0]
        data[2] = self.connected_device_mode & 0x0F  # Bits[3:0]
        data[4] = self.connected_device_type
        data[5] = self.supported_cxl_modes
        data[6] = self.maximum_link_width & 0x3F  # Bits[5:0]
        data[7] = self.negotiated_link_width & 0x3F  # Bits[5:0]
        data[8] = self.supported_link_speeds_vector & 0x3F  # Bits[5:0]
        data[9] = self.max_link_speed & 0x3F  # Bits[5:0]
        data[10] = self.current_link_speed & 0x3F  # Bits[5:0]
        data[11] = self.ltssm_state
        data[12] = self.first_negotiated_lane_number
        data[13:15] = self.link_state_flags.to_bytes(2, "little")
        data[15] = self.supported_ld_count
        return bytes(data)

    def to_dict(self) -> Dict:
        return {
            "portId": self.port_id,
            "currentPortConfigurationState": self.current_port_configuration_state.name,
            "connectedDeviceMode": self.connected_device_mode.name,
            "connectedDeviceType": self.connected_device_type.name,
            "supportedCxlModes": self.supported_cxl_modes,
            "maximumLinkWidth": self.maximum_link_width,
            "negotiatedLinkWidth": self.negotiated_link_width,
            "supportedLinkSpeedsVector": self.supported_link_speeds_vector,
            "maxLinkSpeed": self.max_link_speed,
            "currentLinkSpeed": self.current_link_speed,
            "ltssmState": self.ltssm_state.name,
            "firstNegotiatedLaneNumber": self.first_negotiated_lane_number,
            "linkStateFlags": self.link_state_flags,
            "supportedLdCount": self.supported_ld_count,
        }


@dataclass
class GetPhysicalPortStateResponsePayload:
    port_info_list: List[PortInfo] = field(default_factory=list)

    @classmethod
    def parse(cls, data: bytes) -> "GetPhysicalPortStateResponsePayload":
        number_of_ports = data[0]
        port_info_list = []
        offset = 4  # Start of the Port Information List
        for _ in range(number_of_ports):
            port_info_data = data[offset : offset + 16]
            port_info = PortInfo.parse(port_info_data)
            port_info_list.append(port_info)
            offset += 16
        return cls(port_info_list=port_info_list)

    def dump(self) -> bytes:
        buffer = bytearray(4)  # Include reserved bytes
        buffer[0] = len(self.port_info_list)
        for port_info in self.port_info_list:
            buffer.extend(port_info.dump())
        return bytes(buffer)

    def get_pretty_print(self) -> str:
        return dump(self.to_dict(), sort_keys=False, default_flow_style=False)

    def to_dict(self) -> Dict[str, List[Dict]]:
        return {"portInfoList": [port_info.to_dict() for port_info in self.port_info_list]}


class GetPhysicalPortStateCommand(CciForegroundCommand):
    def __init__(
        self,
        switch_connection_manager: SwitchConnectionManager,
        device_configs: List[LogicalDeviceConfig],
    ):
        super().__init__(CCI_FM_API_COMMAND_OPCODE.GET_PHYSICAL_PORT_STATE)
        self._switch_connection_manager = switch_connection_manager
        self._device_configs = device_configs

    async def _execute(self, request: CciRequest) -> CciResponse:
        request_payload = self.parse_request_payload(request.payload)
        switch_ports = self._switch_connection_manager.get_switch_ports()
        port_info_list = []
        usp_count = 0
        for port_id in request_payload.port_id_list:
            if port_id >= len(switch_ports):
                return CciResponse(return_code=CCI_RETURN_CODE.INVALID_INPUT)
            switch_port = switch_ports[port_id]
            port_info = PortInfo()
            port_info.port_id = port_id
            if switch_port.port_config.type == PORT_TYPE.USP:
                port_info.current_port_configuration_state = CURRENT_PORT_CONFIGURATION_STATE.USP
                port_info.connected_device_type = CONNECTED_DEVICE_TYPE.NO_DEVICE_DETECTED
                usp_count += 1
            elif switch_port.port_config.type == PORT_TYPE.DSP:
                port_info.current_port_configuration_state = CURRENT_PORT_CONFIGURATION_STATE.DSP
                if switch_port.connected:
                    # First item is always USP
                    if isinstance(
                        self._device_configs[port_info.port_id - usp_count],
                        MultiLogicalDeviceConfig,
                    ):
                        port_info.connected_device_type = CONNECTED_DEVICE_TYPE.CXL_TYPE_3_MLD
                    else:
                        port_info.connected_device_type = CONNECTED_DEVICE_TYPE.CXL_TYPE_3_SLD
                else:
                    port_info.connected_device_type = CONNECTED_DEVICE_TYPE.NO_DEVICE_DETECTED
            else:
                port_info.current_port_configuration_state = (
                    CURRENT_PORT_CONFIGURATION_STATE.DISABLED
                )
                port_info.connected_device_type = CONNECTED_DEVICE_TYPE.NO_DEVICE_DETECTED
            port_info.connected_device_mode = CONNECTED_DEVICE_MODE.CXL_68B_FLIT_AND_VH_MODE
            port_info.supported_cxl_modes = SUPPORTED_CXL_MODES.CXL_68B_FLIT_AND_VH_CAPABLE
            if switch_port.connected:
                port_info.ltssm_state = LTSSM_STATE.L0
            else:
                port_info.ltssm_state = LTSSM_STATE.DISABLED

            port_info_list.append(port_info)
        response_payload = GetPhysicalPortStateResponsePayload()
        response_payload.port_info_list = port_info_list

        response = self.create_cci_response(response_payload)
        return response

    @staticmethod
    def create_cci_request(
        request: GetPhysicalPortStateRequestPayload,
    ) -> CciRequest:
        cci_request = CciRequest()
        cci_request.opcode = CCI_FM_API_COMMAND_OPCODE.GET_PHYSICAL_PORT_STATE
        cci_request.payload = request.dump()
        return cci_request

    @staticmethod
    def create_cci_response(
        response: GetPhysicalPortStateResponsePayload,
    ) -> CciResponse:
        cci_response = CciResponse()
        cci_response.payload = response.dump()
        return cci_response

    @staticmethod
    def parse_request_payload(payload: bytes) -> GetPhysicalPortStateRequestPayload:
        return GetPhysicalPortStateRequestPayload.parse(payload)

    @staticmethod
    def parse_response_payload(
        payload: bytes,
    ) -> GetPhysicalPortStateResponsePayload:
        return GetPhysicalPortStateResponsePayload.parse(payload)
