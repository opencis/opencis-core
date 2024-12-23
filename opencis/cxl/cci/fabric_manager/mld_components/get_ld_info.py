"""
 Copyright (c) 2024, Eeum, Inc.

 This software is licensed under the terms of the Revised BSD License.
 See LICENSE for details.
"""

from dataclasses import dataclass, field
from struct import pack, unpack
from typing import TypedDict

# from opencis.util.logger import logger
from opencis.cxl.cci.common import CCI_FM_API_COMMAND_OPCODE
from opencis.cxl.component.cci_executor import (
    CciForegroundCommand,
    CciRequest,
    CciResponse,
)


class GetLdInfoResponsePayloadDict(TypedDict):
    memorySize: int
    ldCount: int
    qosTelemetryCapability: int


@dataclass
class GetLdInfoResponsePayload:
    memory_size: int = field(default=0)  # 8bytes
    ld_count: int = field(default=0)  # 2bytes
    qos_telemetry_capability: int = field(default=0)  # 1byte

    @classmethod
    def parse(cls, data: bytes):
        if len(data) < 11:
            raise ValueError("Data provided is too short to parse.")

        memory_size = unpack("<Q", data[:8])[0]
        ld_count = unpack("<H", data[8:10])[0]
        qos_telemetry_capability = data[10]
        return cls(memory_size, ld_count, qos_telemetry_capability)

    def dump(self):
        data = bytearray(11)
        data[:8] = pack("<Q", self.memory_size)
        data[8:10] = pack("<H", self.ld_count)
        data[10] = self.qos_telemetry_capability
        return bytes(data)

    def get_pretty_print(self):
        return (
            f"- Memory Size: {self.memory_size}\n"
            f"- LD Count: {self.ld_count}\n"
            f"- QoS Telemetry Capability: {self.qos_telemetry_capability}\n"
        )

    def to_dict(self) -> GetLdInfoResponsePayloadDict:
        return {
            "memorySize": self.memory_size,
            "ldCount": self.ld_count,
            "qosTelemetryCapability": self.qos_telemetry_capability,
        }


class GetLdInfoCommand(CciForegroundCommand):
    OPCODE = CCI_FM_API_COMMAND_OPCODE.GET_LD_INFO

    def __init__(self):
        super().__init__(self.OPCODE)

    async def _execute(self, request: CciRequest) -> CciResponse:
        pass

    @classmethod
    def create_cci_request(cls) -> CciRequest:
        cci_request = CciRequest()
        cci_request.opcode = cls.OPCODE
        # get_ld_info request has no payload
        return cci_request

    @classmethod
    def parse_response_payload(cls, payload: bytes) -> GetLdInfoResponsePayload:
        return GetLdInfoResponsePayload.parse(payload)
