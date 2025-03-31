"""
Copyright (c) 2024, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from dataclasses import dataclass, field
from typing import Optional, List
from opencis.util.pci import extract_device_from_bdf, extract_bus_from_bdf
from opencis.util.logger import logger
from opencis.util.component import LabeledComponent

BRIDGE_MAX_BARS = 2


@dataclass
class BarEntry:
    base: int = 0
    limit: int = 0


@dataclass
class MmioEntry:
    bars: List[BarEntry] = field(default_factory=list)
    base: int = 0
    limit: int = 0


@dataclass
class ConfigSpaceEntry:
    secondary_bus: int = 0
    subordinate_bus: int = 0


class PciRoutingTable(LabeledComponent):
    def __init__(self, table_size: int, label: Optional[str] = None):
        super().__init__(label)
        self._label = label
        self._router_bus_number = None
        self._table_size = table_size
        self._mmio_table = [MmioEntry() for _ in range(table_size)]
        for mmio_entry in self._mmio_table:
            for _ in range(BRIDGE_MAX_BARS):
                mmio_entry.bars.append(BarEntry())

        self._config_space_table = [[ConfigSpaceEntry(), True] for _ in range(table_size)]

    def set_router_bus_number(self, bus_number: int):
        logger.debug(self._create_message(f"Setting router bus number to {bus_number}"))
        self._router_bus_number = bus_number

    def _check_port_number(self, port_number: int):
        if port_number >= self._table_size:
            raise Exception(
                f"port_number({port_number}) should be between 0 and {self._table_size - 1} "
            )

    def _check_bar_index(self, bar_index: int):
        if bar_index >= BRIDGE_MAX_BARS:
            raise Exception(
                f"Bar index ({bar_index}) should be between 0 and {BRIDGE_MAX_BARS - 1} "
            )

    def set_secondary_bus_number(self, bus_number: int, port_number: int):
        self._check_port_number(port_number)
        self._config_space_table[port_number][0].secondary_bus = bus_number
        logger.debug(
            self._create_message(
                f"Setting secondary bus number of port {port_number} to {bus_number}"
            )
        )

    def set_subordinate_bus_number(self, bus_number: int, port_number: int):
        self._check_port_number(port_number)
        self._config_space_table[port_number][0].subordinate_bus = bus_number

    def set_memory_base(self, base: int, port_number: int):
        self._check_port_number(port_number)
        self._mmio_table[port_number].base = base

    def set_memory_limit(self, limit: int, port_number: int):
        self._check_port_number(port_number)
        self._mmio_table[port_number].limit = limit

    def set_prefetchable_memory_base(self, _: int, port_number: int):
        self._check_port_number(port_number)
        # TODO: Implement this later

    def set_prefetchable_memory_limit(self, _: int, port_number: int):
        self._check_port_number(port_number)
        # TODO: Implement this later

    def set_bar(self, bar_index: int, base: int, limit: int, port_number: int):
        self._check_port_number(port_number)
        self._check_bar_index(bar_index)
        self._mmio_table[port_number].bars[bar_index].base = base
        self._mmio_table[port_number].bars[bar_index].limit = limit

    def get_config_space_target_port(self, id: int) -> Optional[int]:
        bus_number = extract_bus_from_bdf(id)
        logger.debug(
            self._create_message(
                f"Request Bus Number: {bus_number}, Router Bus Number: {self._router_bus_number}"
            )
        )
        if bus_number == self._router_bus_number:
            logger.debug(self._create_message("Rounting to DSP"))
            device_number = extract_device_from_bdf(id)
            if extract_device_from_bdf(id) < sum(
                1 for entry, flag in self._config_space_table if flag
            ):
                return device_number
            return None

        for port_number, (config_space_entry, active) in enumerate(self._config_space_table):
            if active:
                if (
                    config_space_entry.secondary_bus
                    <= bus_number
                    <= config_space_entry.subordinate_bus
                ):
                    return port_number
        return None

    def is_config_space_id_local(self, id: int) -> bool:
        bus_number = extract_bus_from_bdf(id)
        if self._router_bus_number is None:
            raise Exception("USP is not bound yet")
        return self._router_bus_number == bus_number

    def get_mmio_target_port(self, memory_addr: int) -> Optional[int]:
        for port_number, mmio_entry in enumerate(self._mmio_table):
            for bar_entry in mmio_entry.bars:
                if bar_entry.base <= memory_addr <= bar_entry.limit:
                    return port_number
            if mmio_entry.base <= memory_addr <= mmio_entry.limit:
                return port_number
        return None

    def get_secondary_bus_number(self, port_number: int) -> int:
        return self._config_space_table[port_number][0].secondary_bus

    def activate_vppb(self, vppb_number: int):
        self._config_space_table[vppb_number][1] = True

    def deactivate_vppb(self, vppb_number: int):
        self._config_space_table[vppb_number][1] = False
