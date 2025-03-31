"""
Copyright (c) 2024, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

import re

from opencis.util.logger import logger
from opencis.cxl.component.common import CXL_COMPONENT_TYPE
from opencis.cxl.component.virtual_switch.vppb import Vppb, VppbRoutingInfo
from opencis.cxl.component.cxl_connection import CxlConnection
from opencis.cxl.component.cxl_bridge_component import (
    CxlUpstreamPortComponent,
    HDM_DECODER_COUNT,
)


# UpstreamVppb class will have many similar methods to UpstreamPortDevice class
# pylint: disable=duplicate-code
class UpstreamVppb(Vppb):
    def __init__(self, upstream_port_index: int):
        super().__init__()
        self._decoder_count = HDM_DECODER_COUNT.DECODER_32

        self._port_index = upstream_port_index
        label = f"USP{self._port_index}"
        self._label = label

    def get_reg_vals(self, ld_id: int):
        return self._cxl_io_manager[ld_id].get_cfg_reg_vals()

    def get_port_index(self):
        return self._port_index

    def get_downstream_connection(self) -> CxlConnection:
        return self._downstream_connection

    def set_routing_table(self, vppb_routing_info: VppbRoutingInfo):
        logger.debug(f"[UpstreamPort{self.get_port_index()}] Setting routing table")
        self._pci_bridge_component.set_routing_table(vppb_routing_info)
        self._cxl_component.set_routing_table(vppb_routing_info)

    def get_device_type(self) -> CXL_COMPONENT_TYPE:
        return CXL_COMPONENT_TYPE.USP

    def get_hdm_decoder_count(self) -> int:
        name = HDM_DECODER_COUNT(self._decoder_count).name
        return int(re.search(r"\d+", name).group())

    def get_cxl_component(self) -> CxlUpstreamPortComponent:
        return self._cxl_component
