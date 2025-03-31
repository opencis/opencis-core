"""
Copyright (c) 2024, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from dataclasses import dataclass, field
from typing import List, Optional, TypedDict
from abc import ABC, abstractmethod
from opencis.util.number_const import DWORD_BYTES
from opencis.util.unaligned_bit_structure import (
    UnalignedBitStructure,
    ShareableByteArray,
    ByteField,
    StructureField,
)
from opencis.util.logger import logger

MAX_MAILBOX_SIZE = (1 << 18) * DWORD_BYTES


@dataclass
class DoeMailboxContext:
    read_mailbox_index: int = 0
    read_mailbox_len: int = 0
    write_mailbox_len: int = 0
    write_mailbox: ShareableByteArray = field(
        default_factory=lambda: ShareableByteArray(MAX_MAILBOX_SIZE)
    )
    read_mailbox: ShareableByteArray = field(
        default_factory=lambda: ShareableByteArray(MAX_MAILBOX_SIZE)
    )
    protocols: List["DoeMailboxProtocolBase"] = field(default_factory=list)

    def get_protocol(self, protocol_id: int) -> Optional["DoeMailboxProtocolBase"]:
        filtered_protocols = filter(lambda x: x.get_protocol_id() == protocol_id, self.protocols)
        return next(filtered_protocols, None)


class DoeMailboxProtocolBase(ABC):
    vendor_id: int
    data_object_type: int
    name: str

    def get_protocol_id(self) -> int:
        return (self.vendor_id & 0xFFFF) | ((self.data_object_type & 0xFF) << 16)

    @abstractmethod
    def process_request(self, mailbox_context: DoeMailboxContext) -> bool:
        pass


class DoeObjectHeader(UnalignedBitStructure):
    vendor_id: int
    data_object_type: int
    length: int

    _fields = [
        ByteField("vendor_id", 0, 1),
        ByteField("data_object_type", 2, 2),
        ByteField("reserved1", 3, 3),
        ByteField("length", 4, 5),
        ByteField("reserved2", 6, 7),
    ]


class DoeDiscoveryRequest(UnalignedBitStructure):
    header: DoeObjectHeader
    index: int

    _fields = [
        StructureField("header", 0, 7, DoeObjectHeader),
        ByteField("index", 8, 8),
        ByteField("reserved1", 9, 0xB),
    ]


class DoeDiscoveryResponse(UnalignedBitStructure):
    header: DoeObjectHeader
    vendor_id: int
    data_object_type: int
    next_index: int

    _fields = [
        StructureField("header", 0, 7, DoeObjectHeader),
        ByteField("vendor_id", 8, 9),
        ByteField("data_object_type", 0xA, 0xA),
        ByteField("next_index", 0xB, 0xB),
    ]


class DoeMailboxProtocolDoeDiscovery(DoeMailboxProtocolBase):
    vendor_id = 0x0001
    data_object_type = 0x00
    name = "DOE Discovery"
    req_dwords = 3

    def process_request(self, mailbox_context: DoeMailboxContext) -> bool:
        logger.debug("[DOE] Processing DOE Discovery")
        if mailbox_context.write_mailbox_len != self.req_dwords:
            return False

        request = DoeDiscoveryRequest()
        request.reset(bytes(mailbox_context.write_mailbox)[0 : len(request)])

        response = DoeDiscoveryResponse()
        response.header.vendor_id = self.vendor_id
        response.header.data_object_type = self.data_object_type
        response.header.length = len(response) // DWORD_BYTES

        index = request.index

        logger.debug("[DOE] DOE Discovery: Index = {index}")

        if index >= len(mailbox_context.protocols):
            response.vendor_id = 0xFFFF
            response.data_object_type = 0xFF
        else:
            protocol = mailbox_context.protocols[index]
            response.vendor_id = protocol.vendor_id
            response.data_object_type = protocol.data_object_type
            if index + 1 == len(mailbox_context.protocols):
                response.next_index = 0
            else:
                response.next_index = index + 1

        mailbox_context.read_mailbox.copy_from(response)
        mailbox_context.read_mailbox_len = response.header.length

        logger.debug(f"[DOE] DOE Discovery: Response Length (DWORD) = {response.header.length}")

        return True


DEFAULT_DOE_PROTOCOLS: List[DoeMailboxProtocolBase] = [DoeMailboxProtocolDoeDiscovery()]


class DoeStatusContext(TypedDict):
    doe_busy: int
    doe_interrupt_status: int
    doe_error: int
    data_object_ready: int


class DoeMailboxComponent:
    def __init__(self, protocols: Optional[List[DoeMailboxProtocolBase]]):
        if protocols is None:
            protocols = []
        protocols = DEFAULT_DOE_PROTOCOLS + protocols
        self._mailbox_context = DoeMailboxContext()
        self._mailbox_context.protocols = protocols
        self._status = DoeStatusContext(
            doe_busy=0, doe_interrupt_status=0, doe_error=0, data_object_ready=0
        )

        for protocol in self._mailbox_context.protocols:
            logger.debug(
                f"[DOE] Initialize: Adding DOE protocol {protocol.name} "
                + f"(Vendor ID = 0x{protocol.vendor_id:04x}, "
                + f"Data Object Type = 0x{protocol.data_object_type:02x})"
            )

    def abort(self):
        logger.debug("[DOE] Abort is requested")
        self._clear_ready()
        self._clear_error()
        self._reset_mailbox()

    def go(self):
        logger.debug("[DOE] Mailbox processing is requested")

        if self._has_error():
            logger.warning("[DOE] Aborting mailbox request due to pending error")
            return

        protocol_id = self._mailbox_context.write_mailbox.read_bytes(0, DWORD_BYTES - 1)
        vendor_id = protocol_id & 0xFFFF
        data_object_type = (protocol_id >> 16) & 0xFF
        protocol = self._mailbox_context.get_protocol(protocol_id)
        if not protocol:
            logger.warning(
                "[DOE] Invalid protocol: Vendor ID = 0x%04x, Data Object Type = 0x%02x",
                vendor_id,
                data_object_type,
            )
            self._reset_mailbox()
            return

        logger.debug(
            "[DOE] Valid protocol: Vendor ID = 0x%04x, Data Object Type = 0x%02x",
            vendor_id,
            data_object_type,
        )
        successful = protocol.process_request(self._mailbox_context)
        if not successful:
            logger.debug("[DOE] Failed to process request")
            self._reset_mailbox()
            return

        logger.debug("[DOE] Successfully processed request. Read mailbox is ready")
        self._set_ready()

    def request_next_data(self):
        if not self._is_object_ready():
            logger.debug("[DOE] Data object is not ready")
            self._set_error()
            return

        self._mailbox_context.read_mailbox_index += 1
        if self._mailbox_context.read_mailbox_index == self._mailbox_context.read_mailbox_len:
            logger.debug("[DOE] Reached end of read mailbox")
            self._reset_mailbox()
            self._clear_ready()
        elif self._mailbox_context.read_mailbox_index > self._mailbox_context.read_mailbox_len:
            logger.warning("[DOE] Read mailbox is not ready")
            self._set_error()
        else:
            offset = self._mailbox_context.read_mailbox_index * DWORD_BYTES
            logger.debug(f"[DOE] Requesting Read Mailbox Data[{offset:x}]")

    def read_next_data(self) -> int:
        if self._has_error() or not self._is_object_ready():
            return 0

        mailbox_start_offset = self._mailbox_context.read_mailbox_index * DWORD_BYTES
        mailbox_end_offset = mailbox_start_offset + DWORD_BYTES - 1
        return self._mailbox_context.read_mailbox.read_bytes(
            mailbox_start_offset, mailbox_end_offset
        )

    def write_next_data(self, value: int):
        mailbox_start_offset = self._mailbox_context.write_mailbox_len * DWORD_BYTES
        mailbox_end_offset = mailbox_start_offset + DWORD_BYTES - 1
        self._mailbox_context.write_mailbox.write_bytes(
            mailbox_start_offset, mailbox_end_offset, value
        )
        logger.debug(f"[DOE] Write Mailbox Data[{mailbox_start_offset:x}] = 0x{value:08x}")
        self._mailbox_context.write_mailbox_len += 1

    def get_status(self) -> DoeStatusContext:
        return self._status

    def _set_ready(self):
        self._status["data_object_ready"] = 1

    def _clear_ready(self):
        self._status["data_object_ready"] = 0

    def _is_object_ready(self) -> bool:
        return self._status["data_object_ready"] == 1

    def _set_error(self):
        self._status["doe_error"] = 1

    def _clear_error(self):
        self._status["doe_error"] = 0

    def _has_error(self) -> bool:
        return self._status["doe_error"] == 1

    def _reset_mailbox(self):
        self._mailbox_context.read_mailbox_index = 0
        self._mailbox_context.read_mailbox_len = 0
        self._mailbox_context.write_mailbox_len = 0
        self._mailbox_context.write_mailbox.reset()
        self._mailbox_context.read_mailbox.reset()
