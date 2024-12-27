"""
 Copyright (c) 2024, Eeum, Inc.

 This software is licensed under the terms of the Revised BSD License.
 See LICENSE for details.
"""

from dataclasses import dataclass, field
from enum import Enum, IntEnum


class CCI_RETURN_CODE(IntEnum):
    # pylint: disable=duplicate-code
    SUCCESS = 0x0000
    BACKGROUND_COMMAND_STARTED = 0x0001
    INVALID_INPUT = 0x0002
    UNSUPPORTED = 0x0003
    INTERNAL_ERROR = 0x0004
    RETRY_REQUIRED = 0x0005
    BUSY = 0x0006
    MEDIA_DISABLED = 0x0007
    FW_TRANSFER_IN_PROGRESS = 0x0008
    FW_TRANSFER_OUT_OF_ORDER = 0x0009
    FW_VERIFICATION_FAILED = 0x000A
    INVALID_SLOT = 0x000B
    ACTIVATION_FAILED_FW_ROLLED_BACK = 0x000C
    ACTIVATION_FAILED_COLD_RESET_REQUIRED = 0x000D
    INVALID_HANDLE = 0x000E
    INVALID_PHYSICAL_ADDRESS = 0x000F
    INJECT_POSITION_LIMIT_REACHED = 0x0010
    PERMANENT_MEDIA_FAILURE = 0x0011
    ABORTED = 0x0012
    INVALID_SECURITY_STATE = 0x0013
    INCORRECT_PASSPHRASE = 0x0014
    UNSUPPORTED_MAILBOX_OR_CCI = 0x0015
    INVALID_PAYLOAD_LENGTH = 0x0016
    INVALID_LOG = 0x0017
    INTERRUPTED = 0x0018
    UNSUPPORTED_FEATURE_VERSION = 0x0019
    UNSUPPORTED_FEATURE_SELECTION_VALUE = 0x001A
    FEATURE_TRANSFER_IN_PROGRESS = 0x001B
    FEATURE_TRANSFER_OUT_OF_ORDER = 0x001C
    RESOURCES_EXHAUSTED = 0x001D
    INVALID_EXTENT_LIST = 0x001E


class CCI_GENERIC_COMMAND_OPCODE(IntEnum):
    IDENTIFY = 0x0001
    BACKGROUND_OPERATION_STATUS = 0x0002
    GET_RESPONSE_MESSAGE_LIMIT = 0x0003
    SET_RESPONSE_MESSAGE_LIMIT = 0x0004
    GET_EVENT_RECORDS = 0x0100
    CLEAR_EVENT_RECORDS = 0x0101
    GET_EVENT_INTERRUPT_POLICY = 0x0102
    SET_EVENT_INTERRUPT_POLICY = 0x0103
    GET_MCTP_EVENT_INTERRUPT_POLICY = 0x0104
    SET_MCTP_EVENT_INTERRUPT_POLICY = 0x0105
    EVENT_NOTIFICATION = 0x0106
    GET_FW_INFO = 0x0200
    TRANSFER_FW = 0x0201
    ACTIVATE_FW = 0x0202
    GET_TIMESTAMP = 0x0300
    SET_TIMESTAMP = 0x0301
    GET_SUPPORTED_LOGS = 0x0400
    GET_LOG = 0x0401
    GET_LOG_CAPABILITIES = 0x0402
    CLEAR_LOG = 0x0403
    POPULATE_LOG = 0x0404
    GET_SUPPORTED_LOGS_SUB_LIST = 0x0405
    GET_SUPPORTED_FEATURES = 0x0500
    GET_FEATURE = 0x0501
    SET_FEATURE = 0x0502
    PERFORM_MAINTENANCE = 0x0600


class CCI_FM_API_COMMAND_OPCODE(IntEnum):
    IDENTIFY_SWITCH_DEVICE = 0x5100
    GET_PHYSICAL_PORT_STATE = 0x5101
    PHYSICAL_PORT_CONTROL = 0x5102
    SEND_PPB_CXL_IO_CONFIGURATION_REQUEST = 0x5103
    GET_VIRTUAL_CXL_SWITCH_INFO = 0x5200
    BIND_VPPB = 0x5201
    UNBIND_VPPB = 0x5202
    GENERATE_AER_EVENT = 0x5203
    TUNNEL_MANAGEMENT_COMMAND = 0x5300
    SEND_LD_CXL_IO_CONFIGURATION_REQUEST = 0x5301
    SEND_LD_CXL_IO_MEMORY_REQUEST = 0x5302
    GET_LD_INFO = 0x5400
    GET_LD_ALLOCATIONS = 0x5401
    SET_LD_ALLOCATIONS = 0x5402
    GET_QOS_CONTROL = 0x5403
    SET_QOS_CONTROL = 0x5404
    GET_QOS_STATUS = 0x5405
    GET_QOS_ALLOCATED_BW = 0x5406
    SET_QOS_ALLOCATED_BW = 0x5407
    GET_QOS_BW_LIMIT = 0x5408
    SET_QOS_BW_LIMIT = 0x5409
    GET_MULTI_HEADED_INFO = 0x5500
    GET_DCD_INFO = 0x5600
    GET_HOST_DC_REGION_CONFIGURATION = 0x5601
    SET_DC_REGION_CONFIGURATION = 0x5602
    GET_DCD_EXTENT_LISTS = 0x5603
    INITIATE_DYNAMIC_CAPACITY_ADD = 0x5604
    INITIATE_DYNAMIC_CAPACITY_RELEASE = 0x5605


class CCI_VENDOR_SPECIFIC_OPCODE(IntEnum):
    NOTIFY_PORT_UPDATE = 0xC000
    NOTIFY_SWITCH_UPDATE = 0xC001
    NOTIFY_DEVICE_UPDATE = 0xC002
    GET_CONNECTED_DEVICES = 0xC003
    TUNNEL_MANAGEMENT_COMMAND = 0xC010


def get_opcode_string(opcode: int) -> str:
    if (
        CCI_GENERIC_COMMAND_OPCODE.IDENTIFY
        <= opcode
        <= CCI_GENERIC_COMMAND_OPCODE.PERFORM_MAINTENANCE
    ):
        return CCI_GENERIC_COMMAND_OPCODE(opcode).name

    if (
        CCI_FM_API_COMMAND_OPCODE.IDENTIFY_SWITCH_DEVICE
        <= opcode
        <= CCI_FM_API_COMMAND_OPCODE.INITIATE_DYNAMIC_CAPACITY_RELEASE
    ):
        return CCI_FM_API_COMMAND_OPCODE(opcode).name

    if (
        CCI_VENDOR_SPECIFIC_OPCODE.NOTIFY_PORT_UPDATE
        <= opcode
        <= CCI_VENDOR_SPECIFIC_OPCODE.TUNNEL_MANAGEMENT_COMMAND
    ):
        return CCI_VENDOR_SPECIFIC_OPCODE(opcode).name

    return "Unknown Command"


class TunnelManagementTargetType(Enum):
    PORT_OR_LD_BASED = 0x00
    LD_POOL_CCI = 0x01


@dataclass
class TunnelManagementRequestPayload:
    port_or_ld_id: int = field(default=0, metadata={"offset": 0, "length": 1})
    target_type: TunnelManagementTargetType = field(
        default=TunnelManagementTargetType(0), metadata={"offset": 1, "length": 1}
    )
    command_size: int = field(default=0, metadata={"offset": 2, "length": 2})
    command_payload: int = field(default=0, metadata={"offset": 4})

    def dump(self) -> bytes:
        data = bytearray(self.command_size + 4)
        data[0:1] = self.port_or_ld_id.to_bytes(1, "little")
        data[1:2] = self.target_type.value.to_bytes(1, "little")
        data[2:4] = self.command_size.to_bytes(2, "little")
        data[4 : 4 + self.command_size] = self.command_payload.to_bytes(self.command_size, "little")
        return bytes(data)

    @classmethod
    def parse(cls, data: bytes):
        port_or_ld_id = int.from_bytes(data[0:1], "little")
        target_type = int.from_bytes(data[1:2], "little")
        command_size = int.from_bytes(data[2:4], "little")
        command_payload = int.from_bytes(data[4:], "little")

        if len(data) != command_size:
            raise ValueError("Provided bytes object does not match the expected data size.")
        return cls(port_or_ld_id, target_type, command_size, command_payload)


@dataclass
class TunnelManagementResponsePayload:
    response_size: int = field(default=0, metadata={"offset": 0, "length": 2})
    reserved: int = field(default=0, metadata={"offset": 2, "length": 2})
    payload: int = field(default=0, metadata={"offset": 4})

    @classmethod
    def parse(cls, data: bytes):
        response_size = int.from_bytes(data[0:2], "little")
        payload = int.from_bytes(data[4:], "little")

        if len(data) != response_size + 4:
            raise ValueError("Provided bytes object does not match the expected data size.")
        return cls(
            response_size,
            payload,
        )

    def dump(self) -> bytes:
        data = bytearray(self.response_size + 4)
        data[0:2] = self.response_size.to_bytes(2, "little")
        data[4 : 4 + self.response_size] = self.payload.to_bytes(self.response_size, "little")
        return bytes(data)

    def get_pretty_print(self) -> str:
        return f"- Tunnel Management Command:\n" f"- Payload Bytes: {self.response_size} Bytes\n"
