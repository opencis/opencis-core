"""
Copyright (c) 2024, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from dataclasses import dataclass
from enum import Enum, IntEnum, auto
from typing import Optional
from opencis.cxl.component.virtual_switch.vppb_routing_info import VppbRoutingInfo
from opencis.util.logger import logger

# TODO: Move mmio manager under pci directory
from opencis.pci.component.mmio_manager import MmioManager
from opencis.util.component import LabeledComponent

EEUM_VID = 0x1DC5  # Note: 1DC5 is for FADU
SW_SWITCH_DID = 0xF000
SW_SLD_DID = 0xF001
SW_USP_DID = 0xF002
SW_DSP_DID = 0xF003
SW_EP_DID = 0xF004
SW_MLD_DID = 0xF005


class PCI_CLASS(IntEnum):
    MEMORY_CONTROLLER = 0x05
    BRIDGE = 0x06
    SYSTEM_PERIPHERAL = 0x08


class MEMORY_CONTROLLER_SUBCLASS(IntEnum):
    CXL_MEMORY_DEVICE = 0x02


class PCI_BRIDGE_SUBCLASS(IntEnum):
    PCI_BRIDGE = 0x04


class PCI_SYSTEM_PERIPHERAL_SUBCLASS(IntEnum):
    OTHER = 0x80


class CXL_MEMORY_DEVICE_PI(IntEnum):
    MEMORY_DEVICE_COMMAND = 0x10


class PCI_DEVICE_PORT_TYPE(IntEnum):
    PCI_EXPRESS_ENDPOINT = 0b0000
    LEGACY_PCI_EXPRESS_ENDPOINT = 0b0001
    RCIEP = 0b1001
    ROOT_COMPLEX_EVENT_COLLECTOR = 0b1010
    ROOT_PORT_OF_PCI_EXPRESS_ROOT_COMPLEX = 0b0100
    UPSTREAM_PORT_OF_PCI_EXPRESS_SWITCH = 0b0101
    DOWNSTREAM_PORT_OF_PCI_EXPRESS_SWITCH = 0b0110
    PCI_EXPRESS_TO_PCI_PCI_X_BRIDGE = 0b0111
    PCI_PCI_X_TO_PCI_EXPRESS_BRIDGE = 0b1000


@dataclass
class PciComponentIdentity:
    vendor_id: int = 0
    device_id: int = 0
    base_class_code: int = 0
    sub_class_coce: int = 0
    programming_interface: int = 0
    subsystem_vendor_id: int = 0
    subsystem_id: int = 0
    device_port_type: int = 0
    port_number: int = 0


class PciComponent(LabeledComponent):
    def __init__(self, identity: PciComponentIdentity, mmio_manager: MmioManager):
        super().__init__()
        self._identity = identity
        self._mmio_manager = mmio_manager

    def get_identity(self) -> PciComponentIdentity:
        return self._identity

    def get_mmio_manager(self) -> MmioManager:
        return self._mmio_manager


class PCI_BRIDGE_TYPE(Enum):
    UPSTREAM_PORT = auto()
    DOWNSTREAM_PORT = auto()
    ROOT_PORT = auto()


class PciBridgeComponent(PciComponent):
    def __init__(
        self,
        type: PCI_BRIDGE_TYPE,
        identity: PciComponentIdentity,
        mmio_manager: MmioManager,
        label: Optional[str] = None,
    ):
        super().__init__(identity, mmio_manager)
        self._label = label
        self._type = type
        self._routing_table = None
        self._port_number = 0

    def set_routing_table(self, vppb_routing_info: VppbRoutingInfo):
        self._routing_table = vppb_routing_info.routing_table

    def set_port_number(self, port_number: int):
        if self._type == PCI_BRIDGE_TYPE.UPSTREAM_PORT:
            return
        self._port_number = port_number
        self._identity.port_number = port_number

    def set_secondary_bus_number(self, bus_number: int):
        if not self._routing_table:
            logger.warning(self._create_message("Routing table is not configured yet"))
            return
        if self._type == PCI_BRIDGE_TYPE.UPSTREAM_PORT:
            logger.debug(self._create_message("Setting router bus number from USP"))
            self._routing_table.set_router_bus_number(bus_number)
        else:
            logger.debug(self._create_message("Setting secondary bus number from DSP"))
            self._routing_table.set_secondary_bus_number(bus_number, self._port_number)

    def set_subordinate_bus_number(self, bus_number: int):
        if self._type == PCI_BRIDGE_TYPE.UPSTREAM_PORT:
            return
        if not self._routing_table:
            logger.warning(self._create_message("Routing table is not configured yet"))
            return
        self._routing_table.set_subordinate_bus_number(bus_number, self._port_number)

    def set_memory_base(self, base: int):
        if not self._routing_table:
            logger.warning(self._create_message("Routing table is not configured yet"))
            return
        self._mmio_manager.set_memory_base(base)
        if self._type == PCI_BRIDGE_TYPE.DOWNSTREAM_PORT:
            self._routing_table.set_memory_base(base, self._port_number)

    def set_memory_limit(self, limit: int):
        if not self._routing_table:
            logger.warning(self._create_message("Routing table is not configured yet"))
            return
        self._mmio_manager.set_memory_limit(limit)
        if self._type == PCI_BRIDGE_TYPE.DOWNSTREAM_PORT:
            self._routing_table.set_memory_limit(limit, self._port_number)

    def set_prefetchable_memory_base(self, base: int):
        if self._type == PCI_BRIDGE_TYPE.UPSTREAM_PORT:
            return
        if not self._routing_table:
            logger.warning(self._create_message("Routing table is not configured yet"))
            return
        self._routing_table.set_prefetchable_memory_base(base, self._port_number)

    def set_prefetchable_memory_limit(self, limit: int):
        if self._type == PCI_BRIDGE_TYPE.UPSTREAM_PORT:
            return
        if not self._routing_table:
            logger.warning(self._create_message("Routing table is not configured yet"))
            return
        self._routing_table.set_prefetchable_memory_limit(limit, self._port_number)

    def set_bar(self, bar_index: int, base: int, limit: int):
        if self._type == PCI_BRIDGE_TYPE.UPSTREAM_PORT:
            return
        if not self._routing_table:
            logger.warning(self._create_message("Routing table is not configured yet"))
            return
        self._routing_table.set_bar(bar_index, base, limit, self._port_number)


def memory_base_regval_to_addr(regval: int) -> int:
    addr = (regval & 0xFFF0) << 16
    return addr


def memory_base_addr_to_regval(addr: int) -> int:
    regval = (addr & 0xFFF00000) >> 16
    return regval


def memory_limit_regval_to_addr(regval: int) -> int:
    addr = ((regval & 0xFFF0) << 16) | 0xFFFFF
    return addr


def memory_limit_addr_to_regval(addr: int) -> int:
    regval = (addr & 0xFFF00000) >> 16
    return regval
