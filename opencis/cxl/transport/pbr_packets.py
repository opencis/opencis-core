"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from opencis.cxl.transport.packet_structs import _GenPbrBasePacket
from opencis.cxl.transport.packet_constants import SYSTEM_PAYLOAD_TYPE
from opencis.cxl.transport.mixin import BasePacketMixin


class PbrBasePacket(BasePacketMixin, _GenPbrBasePacket):
    """
    PBR (Port-Based Routing) Packet wrapper.

    Wire format:
      [SystemHeader (2B)][PbrHeader (4B)][inner-packet bytes...]

    The system_header.payload_type = SYSTEM_PAYLOAD_TYPE.PBR (5).
    """

    @classmethod
    def create(
        cls,
        spid: int,
        dpid: int,
        data: bytes = None,
    ) -> "PbrBasePacket":
        """
        Create a PBR packet.

        Args:
            spid:  Source PID (12-bit)
            dpid:  Destination PID (12-bit)
            data:  Optional inner-packet bytes (the encapsulated TLP)
        """
        pkt = super().create(
            SYSTEM_PAYLOAD_TYPE.PBR,  # system_header__payload_type
            spid,                     # pbr_header__spid
            dpid,                     # pbr_header__dpid
            data,
        )
        return pkt

    @classmethod
    def encapsulate(cls, spid: int, dpid: int, inner_packet) -> "PbrBasePacket":
        """
        Encapsulate an existing packet object as the PBR payload.

        Args:
            spid:         Source PID
            dpid:         Destination PID
            inner_packet: Any packet object that supports bytes() serialization
        """
        inner_bytes = bytes(inner_packet)
        pkt = cls.create(spid=spid, dpid=dpid, data=inner_bytes)
        # Stash the original object so callers can avoid re-parsing
        pkt._inner_packet = inner_packet
        return pkt
