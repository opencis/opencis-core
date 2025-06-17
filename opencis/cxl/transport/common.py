"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from opencis.cxl.transport.packet_structs import _GenBasePacket
from opencis.cxl.transport.mixin import BasePacketMixin


class BasePacket(BasePacketMixin, _GenBasePacket):
    pass


class TagCounter:
    __slots__ = ("_value", "_mod")

    def __init__(self, range: int) -> None:
        self._value = 0
        self._mod = range

    def next(self, explicit: int = None) -> int:
        if explicit is not None:
            return explicit & (self._mod - 1)
        tag = self._value
        self._value = (self._value + 1) % self._mod
        return tag
