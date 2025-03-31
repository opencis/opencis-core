"""
Copyright (c) 2024, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

# pylint: disable=unused-import
from typing import Optional

from opencis.pci.component.fifo_pair import FifoPair
from opencis.pci.component.packet_processor import PacketProcessor


class CxlCacheManager(PacketProcessor):
    def __init__(
        self,
        upstream_fifo: FifoPair,
        downstream_fifo: Optional[FifoPair] = None,
        label: Optional[str] = None,
    ):
        self._downstream_fifo: Optional[FifoPair]
        self._upstream_fifo: FifoPair
        self._cache_device_component = None

        super().__init__(upstream_fifo, downstream_fifo, label)
