"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from typing import Optional

from opencis.pci.component.routing_table import PciRoutingTable
from opencis.cxl.component.hdm_decoder import SwitchHdmDecoderManager
from opencis.cxl.component.cache_route_table_manager import SwitchCacheRouteTable


class RoutingTable(PciRoutingTable):
    def __init__(self, table_size: int, label: Optional[str] = None):
        super().__init__(table_size, label=label)
        self._hdm_decoder_manager: Optional[SwitchHdmDecoderManager] = None
        self._cache_route_table: Optional[SwitchCacheRouteTable] = None

    def set_hdm_decoder(self, hdm_decoder_manager: SwitchHdmDecoderManager):
        self._hdm_decoder_manager = hdm_decoder_manager

    def set_cache_route_table(self, cache_route_table: Optional[SwitchCacheRouteTable]):
        self._cache_route_table = cache_route_table

    def get_cxl_mem_target_port(self, memory_addr: int) -> Optional[int]:
        if self._hdm_decoder_manager is None:
            raise Exception("HDM Decoder Manager is not initialized")
        return self._hdm_decoder_manager.get_target(memory_addr)

    def get_cxl_cache_target_port(self, cache_id: int) -> Optional[int]:
        if self._cache_route_table is None:
            raise Exception("Port has no associated cache route table")
        return self._cache_route_table.get_target(cache_id)

    def get_cxl_cache_cache_id(self, target: int) -> Optional[int]:
        if self._cache_route_table is None:
            raise Exception("Port has no associated cache route table")
        return self._cache_route_table.get_cache_id(target)
