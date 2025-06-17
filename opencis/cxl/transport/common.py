"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from opencis.cxl.transport.packet_structs import RawBasePacket
from opencis.cxl.transport.mixin import BasePacketMixin


class BasePacket(BasePacketMixin, RawBasePacket):
    pass
