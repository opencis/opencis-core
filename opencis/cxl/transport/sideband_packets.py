"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

# from opencis.util.logger import logger
from opencis.cxl.transport.packet_structs import (
    _GenBaseSidebandPacket,
    _GenSidebandConnectionRequestPacket,
)
from opencis.cxl.transport.packet_constants import (
    SYSTEM_PAYLOAD_TYPE,
    SIDEBAND_TYPES,
)
from opencis.cxl.transport.mixin import (
    BasePacketMixin,
    PacketDataMixin,
    SidebandPacketMixin,
)


class BaseSidebandPacket(
    _GenBaseSidebandPacket,
    BasePacketMixin,
    SidebandPacketMixin,
):
    @classmethod
    def create(cls, type: SIDEBAND_TYPES) -> "BaseSidebandPacket":
        packet = cls()
        packet.system_header.payload_type = SYSTEM_PAYLOAD_TYPE.SIDEBAND
        packet.sideband_header.type = type
        packet.system_header.payload_length = len(packet)
        return packet


class SidebandConnectionRequestPacket(
    _GenSidebandConnectionRequestPacket,
    BasePacketMixin,
    SidebandPacketMixin,
    PacketDataMixin,
):
    @classmethod
    def create(cls, port_index: int) -> "SidebandConnectionRequestPacket":
        packet = cls()
        packet.system_header.payload_type = SYSTEM_PAYLOAD_TYPE.SIDEBAND
        packet.sideband_header.type = SIDEBAND_TYPES.CONNECTION_REQUEST
        packet.set_data_as_int(port_index)
        packet.system_header.payload_length = len(packet)
        return packet
