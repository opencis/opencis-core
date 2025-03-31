"""
Copyright (c) 2024, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from dataclasses import dataclass, field
from typing import ClassVar, Optional
from opencis.cxl.cci.common import (
    CCI_GENERIC_COMMAND_OPCODE,
    CCI_RETURN_CODE,
    get_opcode_string,
)
from opencis.cxl.component.cci_executor import (
    CciRequest,
    CciResponse,
    CciForegroundCommand,
)
from opencis.cxl.component.mctp.mctp_cci_executor import MctpCciExecutor


@dataclass
class BackgroundOperationStatusField:
    operation_in_progress: bool = field(default=False, metadata={"bit": 0})
    percentage_complete: int = field(default=0, metadata={"bit": (1, 8)})

    @classmethod
    def from_byte(cls, byte: int):
        operation_in_progress = bool(byte & 0b1)
        percentage_complete = (byte & 0b11111110) >> 1
        return cls(operation_in_progress, percentage_complete)

    def to_byte(self) -> int:
        byte = self.percentage_complete << 1
        byte |= self.operation_in_progress
        return byte


@dataclass
class BackgroundOperationStatusResponsePayload:
    """
    Background Operation Status Output Payload

    +------------+-------------------+-------------------------------------------------+
    | Byte Offset| Length in Bytes   | Description                                     |
    +------------+-------------------+-------------------------------------------------+
    | 00h        | 1                 | Background Operation Status: Reports the status |
    |            |                   | of outstanding Background Operations:           |
    |            |                   | • Bit[0]: Background Operation – Indicates     |
    |            |                   |   whether a background operation is in         |
    |            |                   |   progress, as defined in Section 8.2.8.4.6.   |
    |            |                   | • Bits[7:1]: Percentage Complete – The         |
    |            |                   |   percentage complete (0-100) of the background|
    |            |                   |   command, as defined in Section 8.2.8.4.7.    |
    | 01h        | 1                 | Reserved                                        |
    | 02h        | 2                 | Command Opcode: The command identifier of the   |
    |            |                   | last command executed in the background. See    |
    |            |                   | Section 8.2.9 for the list of command opcodes.  |
    | 04h        | 2                 | Return Code: The result of the command run in   |
    |            |                   | the background. Only valid when Percentage      |
    |            |                   | Complete = 100. See Section 8.2.8.4.5.1.        |
    | 06h        | 2                 | Vendor Specific Extended Status: The vendor     |
    |            |                   | specific extended status of the last background |
    |            |                   | command. Valid only when Percentage Complete =  |
    |            |                   | 100.                                            |
    +------------+-------------------+-------------------------------------------------+
    """

    structure_size: ClassVar[int] = 8  # Fixed structure size

    background_operation_status: BackgroundOperationStatusField = field(
        default_factory=BackgroundOperationStatusField
    )
    command_opcode: int = field(default=0, metadata={"offset": 2, "length": 2})
    return_code: int = field(default=0, metadata={"offset": 4, "length": 2})
    vendor_specific_extended_status: int = field(default=0, metadata={"offset": 6, "length": 2})

    @classmethod
    def parse(cls, data: bytes):
        if len(data) != cls.structure_size:
            raise ValueError("Provided bytes object does not match the expected data size.")
        background_operation_status = BackgroundOperationStatusField.from_byte(data[0])
        command_opcode = int.from_bytes(data[2:4], "little")
        return_code = int.from_bytes(data[4:6], "little")
        vendor_specific_extended_status = int.from_bytes(data[6:8], "little")
        return cls(
            background_operation_status=background_operation_status,
            command_opcode=command_opcode,
            return_code=return_code,
            vendor_specific_extended_status=vendor_specific_extended_status,
        )

    def dump(self) -> bytes:
        data = bytearray(self.structure_size)
        data[0] = self.background_operation_status.to_byte()
        data[2:4] = self.command_opcode.to_bytes(2, "little")
        data[4:6] = self.return_code.to_bytes(2, "little")
        data[6:8] = self.vendor_specific_extended_status.to_bytes(2, "little")
        return bytes(data)

    def get_pretty_print(self) -> str:
        return (
            f"- Background Operation Status:\n"
            f"  - Operation In Progress: {self.background_operation_status.operation_in_progress}\n"
            f"  - Percentage Complete: {self.background_operation_status.percentage_complete}%\n"
            f"- Command Opcode: {get_opcode_string(self.command_opcode)}\n"
            f"- Return Code: {CCI_RETURN_CODE(self.return_code).name}\n"
            f"- Vendor Specific Extended Status: {self.vendor_specific_extended_status}"
        )


class BackgroundOperationStatusCommand(CciForegroundCommand):
    OPCODE = CCI_GENERIC_COMMAND_OPCODE.BACKGROUND_OPERATION_STATUS

    def __init__(self, mctp_cci_executor: MctpCciExecutor, label: Optional[str] = None):
        super().__init__(self.OPCODE, label=label)
        self._mctp_cci_executor = mctp_cci_executor

    async def _execute(self, _: CciRequest) -> CciResponse:
        status = await self._mctp_cci_executor.get_background_command_status()

        payload = BackgroundOperationStatusResponsePayload(
            background_operation_status=BackgroundOperationStatusField(
                status.percentage_complete != 100, status.percentage_complete
            ),
            command_opcode=status.opcode,
            return_code=status.return_code,
            vendor_specific_extended_status=status.vendor_specific_status,
        ).dump()

        return CciResponse(payload=payload)

    @classmethod
    def create_cci_request(cls) -> CciRequest:
        return CciRequest(opcode=cls.OPCODE)

    @staticmethod
    def parse_response_payload(
        payload: bytes,
    ) -> BackgroundOperationStatusResponsePayload:
        return BackgroundOperationStatusResponsePayload.parse(payload)
