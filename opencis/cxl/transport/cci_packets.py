"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

import platform

# from opencis.util.logger import logger
from opencis.cxl.cci.common import CCI_FM_API_COMMAND_OPCODE
from opencis.cxl.transport.mixin import (
    BasePacketMixin,
    PacketDataMixin,
    CciBasePacketMixin,
)
from opencis.cxl.transport.packet_structs import (
    _GenCciBasePacket,
    _GenCciMessagePacket,
    _GenCciPayloadPacket,
    _GenCciRequestPacket,
    _GenCciResponsePacket,
)
from opencis.cxl.transport.packet_constants import (
    SYSTEM_PAYLOAD_TYPE,
    CCI_MSG_CLASS,
    CCI_MCTP_MESSAGE_CATEGORY,
)

# pylint: disable=attribute-defined-outside-init


class CciBasePacket(BasePacketMixin, CciBasePacketMixin, _GenCciBasePacket):
    pass


class CciPayload:
    # pylint: disable=protected-access
    class Field:
        def __init__(self, offset: int, width: int) -> None:
            self._offset = offset
            self._width = width

        def _get_width(self, payload: "CciPayload", name: str) -> int:
            if self._width != "dynamic":
                return self._width

            if name in payload._dynamic_widths:
                return payload._dynamic_widths[name]

            raise ValueError(f"Width for dynamic field '{name}' not provided.")

        def get(self, payload: "CciPayload", name: str) -> int | bytes:
            width = self._get_width(payload, name)
            offset = self._offset

            arch_bits = int(platform.architecture()[0].rstrip("bit"))
            if width <= arch_bits:
                # field fits in a single word. Read it directly and return int
                return payload._packet.read_bits(payload._base + offset, width)

            # field is wider than a single word, return bytes
            byte_start = (payload._base + offset) // 8
            full_bytes = width // 8
            data = payload._packet.get_bytes(byte_start, full_bytes)

            tail_bits = width - full_bytes * 8
            if tail_bits:
                last = payload._packet.read_bits(payload._base + offset + full_bytes * 8, tail_bits)
                data += bytes([last])
            return data

        def set(self, payload: "CciPayload", name: str, value: int | bytes) -> None:
            width = self._get_width(payload, name)
            offset = self._offset

            arch_bits = int(platform.architecture()[0].rstrip("bit"))
            if width <= arch_bits:
                # field fits in a single word. Read it directly and return int
                payload._packet.write_bits(payload._base + offset, width, value)
                return

            if not isinstance(value, bytes):
                raise AttributeError(
                    f"value width: {width}. value is {type(value)}, but must be 'bytes' "
                    "if it does not fit in a single word"
                )

            byte_start = (payload._base + offset) // 8
            full_bytes = width // 8
            if full_bytes:
                payload._packet.set_bytes(byte_start, value[:full_bytes])

            tail_width = width - (full_bytes * 8)
            if tail_width:
                payload._packet.write_bits(
                    payload._base + offset + full_bytes * 8, tail_width, value[full_bytes]
                )

    def __init__(
        self,
        packet: CciBasePacket,
        byte_offset: int,
        fields: dict[str, int],
        dynamic_widths: dict[str, int] | None = None,
    ) -> None:
        self._packet = packet
        self._base = byte_offset * 8
        self._fields = {name: self.Field(offset, width) for name, offset, width in fields}

        self._dynamic_widths = {}
        if dynamic_widths:
            self._dynamic_widths = dynamic_widths

    def __getattr__(self, name: str) -> int | bytes:
        if name.startswith("_"):
            return object.__getattribute__(self, name)

        fields = self.__dict__.get("_fields", {})
        if name in fields:
            return fields[name].get(self, name)

        raise AttributeError(f"{name!r} not found")

    def __setattr__(self, name: str, value: int | bytes) -> None:
        if name.startswith("_"):
            return object.__setattr__(self, name, value)

        fields = self.__dict__.get("_fields", {})
        if name in fields:
            return fields[name].set(self, name, value)

        raise AttributeError(f"{name!r} not found")

    def __bytes__(self) -> bytes:
        total_bits = 0
        for name, field in self._fields.items():
            width = field._width if field._width != "dynamic" else self._dynamic_widths.get(name)
            if width is None:
                raise ValueError(f"Width for variable field '{name}' was never supplied.")
            total_bits += width

        byte_start = self._base // 8
        byte_len = (total_bits + 7) // 8
        data = self._packet.get_bytes(byte_start, byte_len)
        return data

    def set_dynamic_field_width(self, name: str, width_bits: int) -> None:
        if name not in self._fields:
            raise KeyError(f"Unknown field '{name}'")
        self._dynamic_widths[name] = width_bits


class CciMessagePacket(BasePacketMixin, CciBasePacketMixin, _GenCciMessagePacket, PacketDataMixin):
    @classmethod
    def create(
        cls,
        data: bytes,
        message_category: CCI_MCTP_MESSAGE_CATEGORY,
        opcode: int,
        message_tag: int = 0,
        vendor_specific_extended_status: int = 0,
        return_code: int = 0,
        background_operation: int = 0,
    ) -> "CciMessagePacket":
        packet = cls()
        packet.cci_msg_header.message_category = message_category
        packet.cci_msg_header.command_opcode = opcode
        packet.cci_msg_header.message_tag = message_tag
        packet.cci_msg_header.vendor_specific_extended_status = vendor_specific_extended_status
        packet.cci_msg_header.return_code = return_code
        packet.cci_msg_header.background_operation = background_operation

        if data is not None:
            length = len(data)
            packet.cci_msg_header.message_payload_length_high = (length >> 16) & 0x1F
            packet.cci_msg_header.message_payload_length_low = length & 0xFFFF
            packet.set_data(data)
        return packet

    def get_message_payload_length(self) -> int:
        return (
            self.cci_msg_header.message_payload_length_high << 16
            | self.cci_msg_header.message_payload_length_low
        )

    def get_payload_size(self) -> int:
        return self.cci_msg_header.get_message_payload_length()

    def get_payload(self) -> bytes:
        return self.get_data()


class CciPayloadPacket(
    BasePacketMixin,
    CciBasePacketMixin,
    _GenCciPayloadPacket,
    PacketDataMixin,
):
    def get_cci_message(self) -> CciMessagePacket:
        return CciMessagePacket(bytearray(self.get_data()))

    @classmethod
    def create(cls, cci_message: CciMessagePacket, port_index: int = 0) -> "CciPayloadPacket":
        packet = cls()
        packet.system_header.payload_type = SYSTEM_PAYLOAD_TYPE.CCI_MCTP
        packet.cci_header.port_index = port_index

        if cci_message.cci_msg_header.message_category == CCI_MCTP_MESSAGE_CATEGORY.REQUEST:
            packet.cci_header.msg_class = CCI_MSG_CLASS.REQ
        else:
            packet.cci_header.msg_class = CCI_MSG_CLASS.RSP
        packet.set_data(bytes(cci_message))

        packet.system_header.payload_length = len(packet)
        return packet


class CciRequestPacket(
    BasePacketMixin,
    CciBasePacketMixin,
    _GenCciRequestPacket,
    PacketDataMixin,
):
    def __init__(self, buf: bytes | None = None) -> None:
        # pylint: disable=unused-argument
        self.payload = None
        if hasattr(self, "_fields"):
            self.init_cci_payload()

    def get_command_opcode(self) -> int:
        return self.cci_msg_header.command_opcode

    def initialize_common_headers(self) -> None:
        self.cci_header.msg_class = CCI_MSG_CLASS.REQ
        self.system_header.payload_type = SYSTEM_PAYLOAD_TYPE.CCI_MCTP
        self.cci_msg_header.message_category = CCI_MCTP_MESSAGE_CATEGORY.REQUEST
        self.cci_msg_header.message_tag = 0
        self.cci_msg_header.message_payload_length_high = 0
        self.cci_msg_header.message_payload_length_low = 0
        self.cci_msg_header.return_code = 0
        self.cci_msg_header.vendor_specific_extended_status = 0
        self.cci_msg_header.background_operation = 0
        self.system_header.payload_length = len(self)

    def populate_header_from_cci_message(self, cci_message: CciMessagePacket) -> None:
        header = cci_message.cci_msg_header
        self.cci_msg_header.message_category = header.message_category
        self.cci_msg_header.message_tag = header.message_tag
        self.cci_msg_header.command_opcode = header.command_opcode
        self.cci_msg_header.message_payload_length_high = header.message_payload_length_high
        self.cci_msg_header.message_payload_length_low = header.message_payload_length_low
        self.cci_msg_header.return_code = header.return_code
        self.cci_msg_header.vendor_specific_extended_status = header.vendor_specific_extended_status
        self.cci_msg_header.background_operation = header.background_operation

    @classmethod
    def create_packet(cls, command_opcode: int) -> "CciRequestPacket":
        packet = cls()
        packet.initialize_common_headers()
        packet.cci_msg_header.command_opcode = command_opcode
        return packet

    def init_cci_payload(self, dynamic_widths: dict[str, int] | None = None) -> int:
        cci_payload_length = self.get_cci_payload_length()
        cci_payload_offset = self.get_payload_offset()
        self.payload = CciPayload(self, cci_payload_offset, self._fields, dynamic_widths)
        self.cci_msg_header.message_payload_length_low = cci_payload_length & 0xFFFF
        self.cci_msg_header.message_payload_length_high = (cci_payload_length >> 16) & 0x1F
        return cci_payload_length


class GetLdInfoRequestPacket(CciRequestPacket):
    @classmethod
    def create(cls) -> "GetLdInfoRequestPacket":
        return super().create_packet(CCI_FM_API_COMMAND_OPCODE.GET_LD_INFO)

    @classmethod
    def create_from_cci_message(cls, cci_message: CciMessagePacket) -> "GetLdInfoRequestPacket":
        packet = cls()
        packet.initialize_common_headers()
        packet.populate_header_from_cci_message(cci_message)
        cci_msg_header_offset = packet.get_byte_offset(packet.cci_msg_header)
        packet.set_bytes(cci_msg_header_offset, bytes(cci_message))
        packet.cci_msg_header.command_opcode = CCI_FM_API_COMMAND_OPCODE.GET_LD_INFO
        return packet


class GetLdAllocationsRequestPacket(CciRequestPacket):
    _fields = [
        ("start_ld_id", 0, 8),
        ("ld_allocation_list_limit", 8, 8),
    ]

    @classmethod
    def create(
        cls, start_ld_id: int = 0, ld_allocation_list_limit: int = 0
    ) -> "GetLdAllocationsRequestPacket":
        packet = cls.create_packet(CCI_FM_API_COMMAND_OPCODE.GET_LD_ALLOCATIONS)
        packet.init_cci_payload()

        packet.payload.start_ld_id = start_ld_id
        packet.payload.ld_allocation_list_limit = ld_allocation_list_limit
        packet.set_data(bytes(packet.payload))
        packet.system_header.payload_length = len(packet)
        return packet

    @classmethod
    def create_from_cci_message(
        cls, cci_message: CciMessagePacket
    ) -> "GetLdAllocationsRequestPacket":
        packet = cls.create_packet(CCI_FM_API_COMMAND_OPCODE.GET_LD_ALLOCATIONS)
        packet.init_cci_payload()

        cci_msg_header_offset = packet.get_byte_offset(packet.cci_msg_header)
        packet.set_bytes(cci_msg_header_offset, bytes(cci_message))

        data = cci_message.get_data()
        packet.payload.start_ld_id = int.from_bytes(data[:1], "little")
        packet.payload.ld_allocation_list_limit = int.from_bytes(data[1:3], "little")
        packet.set_data(data)
        packet.system_header.payload_length = len(packet)
        return packet


class SetLdAllocationsRequestPacket(CciRequestPacket):
    _fields = [
        ("number_of_lds", 0, 8),
        ("start_ld_id", 8, 8),
        ("reserved", 16, 16),
        ("ld_allocation_list", 32, "dynamic"),
    ]

    def __init__(self, buf: bytes | None = None) -> None:
        super().__init__(buf)
        if buf is None:
            return

        length = self.payload.number_of_lds * 16
        self.payload.set_dynamic_field_width("ld_allocation_list", length * 8)

    @classmethod
    def create(
        cls, number_of_lds: int, start_ld_id: int, ld_allocations: dict[int, int]
    ) -> "SetLdAllocationsRequestPacket":
        if number_of_lds < 1:
            raise ValueError("Number of LDs must be greater than 0")

        packet = super().create_packet(CCI_FM_API_COMMAND_OPCODE.SET_LD_ALLOCATIONS)
        allocated_ld_list_bytes = bytes()
        allocated_ld_length = 0
        for i in range(number_of_lds):
            if ld_allocations.get(start_ld_id + i) == 1:
                allocated_ld_list_bytes += b"\x01" + b"\x00" * 7 + b"\x00" * 8
                allocated_ld_length += 1
            elif ld_allocations.get(start_ld_id + i) == 0:
                break

        dynamic_widths = {"ld_allocation_list": len(allocated_ld_list_bytes) * 8}
        packet.init_cci_payload(dynamic_widths)
        packet.payload.number_of_lds = number_of_lds
        packet.payload.start_ld_id = start_ld_id
        packet.payload.reserved = 0
        packet.payload.ld_allocation_list = allocated_ld_list_bytes
        packet.set_data(bytes(packet.payload))

        packet.system_header.payload_length = len(packet)
        return packet


class CciResponsePacket(
    BasePacketMixin,
    CciBasePacketMixin,
    _GenCciResponsePacket,
    PacketDataMixin,
):
    def __init__(self, buf: bytes | None = None) -> None:
        # pylint: disable=unused-argument
        self.payload = None
        if hasattr(self, "_fields"):
            self.init_cci_payload()

    def get_command_opcode(self) -> int:
        return self.cci_msg_header.command_opcode

    def initialize_common_headers(self) -> None:
        self.cci_header.msg_class = CCI_MSG_CLASS.RSP
        self.system_header.payload_type = SYSTEM_PAYLOAD_TYPE.CCI_MCTP
        self.cci_msg_header.message_category = CCI_MCTP_MESSAGE_CATEGORY.RESPONSE
        self.cci_msg_header.message_tag = 0
        self.cci_msg_header.message_payload_length_high = 0
        self.cci_msg_header.message_payload_length_low = 0
        self.cci_msg_header.return_code = 0
        self.cci_msg_header.vendor_specific_extended_status = 0
        self.cci_msg_header.background_operation = 0
        self.system_header.payload_length = len(self)

    @classmethod
    def create_packet(cls, command_opcode: int, message_tag: int = 0) -> "CciResponsePacket":
        packet = cls()
        packet.initialize_common_headers()
        packet.cci_msg_header.command_opcode = command_opcode
        packet.cci_msg_header.message_tag = message_tag
        return packet

    def init_cci_payload(self, dynamic_widths: dict[str, int] | None = None) -> int:
        cci_payload_length = self.get_cci_payload_length()
        cci_payload_offset = self.get_payload_offset()
        self.payload = CciPayload(self, cci_payload_offset, self._fields, dynamic_widths)
        self.cci_msg_header.message_payload_length_low = cci_payload_length & 0xFFFF
        self.cci_msg_header.message_payload_length_high = (cci_payload_length >> 16) & 0x1F
        return cci_payload_length

    def get_cci_message(self) -> "CciMessagePacket":
        offset = self.get_byte_offset(self.cci_msg_header)
        payload_data = bytes(self.payload)
        length = len(self.cci_msg_header) + len(payload_data)
        return CciMessagePacket(self.get_bytes(offset, length))


class GetLdInfoResponsePacket(CciResponsePacket):
    _fields = [
        ("memory_size", 0, 64),
        ("ld_count", 64, 16),
        ("qos_telemetry_capability", 80, 8),
    ]

    @classmethod
    def create(cls, memory_size: int, ld_count: int, message_tag: int) -> "GetLdInfoResponsePacket":
        packet = cls.create_packet(CCI_FM_API_COMMAND_OPCODE.GET_LD_INFO, message_tag)
        packet.init_cci_payload()

        packet.payload.memory_size = memory_size
        packet.payload.ld_count = ld_count
        packet.payload.qos_telemetry_capability = 0
        packet.set_data(bytes(packet.payload))

        packet.system_header.payload_length = len(packet)
        return packet

    def get_memory_size(self) -> int:
        return self.payload.memory_size

    def get_ld_count(self) -> int:
        return self.payload.ld_count

    def get_qos_telemetry_capability(self) -> int:
        return self.payload.qos_telemetry_capability

    def get_payload_size(self) -> int:
        return self.payload.get_size()


class GetLdAllocationsResponsePacket(CciResponsePacket):
    _fields = [
        ("number_of_lds", 0, 8),
        ("memory_granularity", 8, 8),
        ("start_ld_id", 16, 8),
        ("ld_allocation_list_length", 24, 8),
        ("ld_allocation_list", 32, "dynamic"),
    ]

    def __init__(self, buf: bytes | None = None) -> None:
        super().__init__(buf)
        if buf is None:
            return

        length = self.payload.ld_allocation_list_length * 16
        self.payload.set_dynamic_field_width("ld_allocation_list", length * 8)

    @classmethod
    def create(
        cls,
        number_of_lds: int,
        memory_granularity: int,
        start_ld_id: int,
        ld_length: int,
        ld_allocations: dict[int, int],
        message_tag: int,
    ) -> "GetLdAllocationsResponsePacket":
        packet = cls.create_packet(CCI_FM_API_COMMAND_OPCODE.GET_LD_ALLOCATIONS, message_tag)

        allocated_ld_list_bytes = bytes()
        allocated_ld_length = 0
        for i in range(ld_length):
            if ld_allocations.get(start_ld_id + i) == 1:
                allocated_ld_list_bytes += b"\x01" + b"\x00" * 7 + b"\x00" * 8
                allocated_ld_length += 1
            elif ld_allocations.get(start_ld_id + i) == 0:
                break

        dynamic_widths = {"ld_allocation_list": len(allocated_ld_list_bytes) * 8}
        packet.init_cci_payload(dynamic_widths)
        packet.payload.number_of_lds = number_of_lds
        packet.payload.memory_granularity = memory_granularity
        packet.payload.start_ld_id = start_ld_id
        packet.payload.ld_allocation_list_length = allocated_ld_length
        packet.payload.ld_allocation_list = allocated_ld_list_bytes

        packet.set_data(bytes(packet.payload))

        packet.system_header.payload_length = len(packet)
        return packet


class SetLdAllocationsResponsePacket(CciResponsePacket):
    _fields = [
        ("number_of_lds", 0, 8),
        ("start_ld_id", 8, 8),
        ("reserved", 16, 16),
        ("ld_allocation_list", 32, "dynamic"),
    ]

    def __init__(self, buf: bytes | None = None) -> None:
        super().__init__(buf)
        if buf is None:
            return

        length = self.payload.number_of_lds * 16
        self.payload.set_dynamic_field_width("ld_allocation_list", length * 8)

    @classmethod
    def create(
        cls, number_of_lds: int, start_ld_id: int, ld_allocations: dict[int, int], message_tag: int
    ) -> "SetLdAllocationsResponsePacket":
        packet = cls.create_packet(CCI_FM_API_COMMAND_OPCODE.SET_LD_ALLOCATIONS, message_tag)

        allocated_ld_list_bytes = bytearray()
        allocated_ld_length = 0
        for i, _ in enumerate(ld_allocations):
            if ld_allocations.get(start_ld_id + i) == 1:
                allocated_ld_list_bytes += b"\x01" + b"\x00" * 7 + b"\x00" * 8
                allocated_ld_length += 1
            elif ld_allocations.get(start_ld_id + i) == 0:
                break

        dynamic_widths = {"ld_allocation_list": len(allocated_ld_list_bytes) * 8}
        packet.init_cci_payload(dynamic_widths)
        packet.payload.number_of_lds = number_of_lds
        packet.payload.start_ld_id = start_ld_id
        packet.payload.reserved = 0
        packet.payload.ld_allocation_list = bytes(allocated_ld_list_bytes)
        packet.set_data(bytes(packet.payload))

        packet.system_header.payload_length = len(packet)
        return packet
