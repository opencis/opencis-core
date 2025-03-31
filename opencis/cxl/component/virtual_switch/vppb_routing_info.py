"""
Copyright (c) 2024, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from dataclasses import dataclass

from opencis.cxl.component.virtual_switch.routing_table import RoutingTable


@dataclass
class VppbRoutingInfo:
    routing_table: RoutingTable
    ld_id: int = 0  # ld_id is used meaningfully only used for MLD, default is 0
