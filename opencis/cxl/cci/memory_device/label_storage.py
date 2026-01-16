"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from opencis.cxl.features.mailbox import (
    CxlMailboxContext,
    CxlMailboxCommandBase,
    MAILBOX_RETURN_CODE,
)
from opencis.util.unaligned_bit_structure import (
    UnalignedBitStructure,
    ShareableByteArray,
    ByteField,
)
from opencis.util.logger import logger


class GetLabelStorageAreaInput(UnalignedBitStructure):
    offset: int
    length: int

    _fields = [
        ByteField("offset", 0x00, 0x03),
        ByteField("length", 0x04, 0x07),
    ]


class GetLabelStorageArea(CxlMailboxCommandBase):
    """Get Label Storage Area (Opcode 4100h)

    Copies a slice of the device's Label Storage Area (LSA) into the mailbox
    output buffer according to the requested offset and length.
    """

    def __init__(self, lsa_storage: bytearray):
        super().__init__(0x4100)
        self._lsa = lsa_storage

    def process(self, context: CxlMailboxContext) -> bool:
        payload_length = context.command["payload_length"]
        if payload_length != GetLabelStorageAreaInput.get_size():
            context.status["return_code"] = MAILBOX_RETURN_CODE.INVALID_INPUT
            logger.error(f"[CCI] GetLabelStorageArea: Invalid input length: {payload_length}")
            return True

        input_buffer = context.payloads.create_shared(payload_length)
        request = GetLabelStorageAreaInput(input_buffer)

        offset = int(request.offset)
        length = int(request.length)

        # Validate bounds
        if length < 0 or offset < 0 or offset + length > len(self._lsa):
            context.status["return_code"] = MAILBOX_RETURN_CODE.INVALID_INPUT
            logger.error(f"[CCI] GetLabelStorageArea: Invalid offset or length: {offset} {length}")
            return True

        data_bytes = bytes(self._lsa[offset : offset + length])
        sba = ShareableByteArray(len(data_bytes), bytearray(data_bytes))
        context.payloads.copy_from(sba)
        context.command["payload_length"] = len(data_bytes)
        return True


class GetLabelStorageAreaSize(CxlMailboxCommandBase):
    """Get Label Storage Area (Opcode 4102h)

    Input Payload (8 bytes):
      - [0:4] Offset (LE)
      - [4:8] Length (LE)

    Output Payload: Requested bytes from the LSA.
    """

    def __init__(self, lsa_storage: bytearray):
        super().__init__(0x4102)
        self._lsa = lsa_storage

    def process(self, context: CxlMailboxContext) -> bool:
        payload_length = context.command["payload_length"]
        if payload_length != GetLabelStorageAreaInput.get_size():
            context.status["return_code"] = MAILBOX_RETURN_CODE.INVALID_INPUT
            logger.error(
                f"[CCI] GetLabelStorageAreaSize(0x4102): Invalid input length: {payload_length}"
            )
            return True

        input_buffer = context.payloads.create_shared(payload_length)
        request = GetLabelStorageAreaInput(input_buffer)

        offset = int(request.offset)
        length = int(request.length)

        if length < 0 or offset < 0 or offset + length > len(self._lsa):
            context.status["return_code"] = MAILBOX_RETURN_CODE.INVALID_INPUT
            logger.error(
                f"[CCI] GetLabelStorageAreaSize(0x4102): Invalid offset/length: {offset} {length}"
            )
            return True

        data_bytes = bytes(self._lsa[offset : offset + length])

        sba = ShareableByteArray(len(data_bytes), bytearray(data_bytes))
        context.payloads.copy_from(sba)
        context.command["payload_length"] = len(data_bytes)
        context.status["return_code"] = MAILBOX_RETURN_CODE.SUCCESS
        return True


class SetLabelStorageArea(CxlMailboxCommandBase):
    """Set Label Storage Area (Opcode 4103h)

    Writes the provided data into the device's Label Storage Area (LSA) at the
    specified byte offset.

    Input Payload:
      - [0:4] Offset (LE)
      - [4:8] Reserved (ignored)
      - [8:]  Data bytes to write

    Output Payload: None.
    """

    def __init__(self, lsa_storage: bytearray):
        super().__init__(0x4103)
        self._lsa = lsa_storage

    def process(self, context: CxlMailboxContext) -> bool:
        payload_length = context.command["payload_length"]

        # Must be at least 8 bytes (offset + reserved)
        if payload_length < 8:
            context.status["return_code"] = MAILBOX_RETURN_CODE.INVALID_INPUT
            logger.error(f"[CCI] SetLabelStorageArea: Invalid input length: {payload_length}")
            return True

        # Read offset (little-endian uint32). Reserved field is ignored.
        offset = context.payloads.read_bytes(0, 3)
        data_length = payload_length - 8

        # Bounds check against LSA size
        if offset < 0 or offset + data_length > len(self._lsa):
            context.status["return_code"] = MAILBOX_RETURN_CODE.INVALID_INPUT
            logger.error(
                f"[CCI] SetLabelStorageArea: Invalid offset={offset} data_len={data_length}"
            )
            return True

        # Get data slice and write into LSA
        data_view = context.payloads.create_shared(data_length, 8)
        self._lsa[offset : offset + data_length] = bytes(data_view)

        # No output payload for Set LSA
        context.command["payload_length"] = 0
        context.status["return_code"] = MAILBOX_RETURN_CODE.SUCCESS
        return True
