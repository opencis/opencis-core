"""
Copyright (c) 2024, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from abc import abstractmethod
from typing import cast

from opencis.cxl.component.cxl_cache_manager import CxlCacheManager
from opencis.cxl.device.port_device import CxlPortDevice
from opencis.cxl.device.downstream_port_device import DownstreamPortDevice
from opencis.cxl.device.upstream_port_device import UpstreamPortDevice

from opencis.cxl.component.virtual_switch.vppb_routing_info import VppbRoutingInfo
from opencis.cxl.component.cxl_connection import CxlConnection
from opencis.cxl.component.common import CXL_COMPONENT_TYPE
from opencis.cxl.component.cxl_io_manager import CxlIoManager
from opencis.cxl.component.cxl_mem_manager import CxlMemManager
from opencis.util.logger import logger


class Vppb:
    def __init__(self):
        self._cxl_mem_manager: CxlMemManager = None
        self._cxl_io_manager: CxlIoManager = None
        self._cxl_cache_manager: CxlCacheManager = None

        self._pci_bridge_component = None
        self._pci_registers = None
        self._cxl_component = None
        self._ld_id = 0

        # Initailize with dummy cxlconnection
        self._upstream_connection = CxlConnection()
        self._downstream_connection = CxlConnection()

        super().__init__()

    def get_upstream_connection(self) -> CxlConnection:
        return self._upstream_connection

    def get_downstream_connection(self) -> CxlConnection:
        return self._downstream_connection

    async def bind_to_physical_dsp_port(self, physical_port: CxlPortDevice, ld_id: int = 0):
        physical_port = cast(DownstreamPortDevice, physical_port)
        referenced_port = await physical_port.bind_to_vppb(ld_id)
        self._cxl_mem_manager = referenced_port[0]
        self._cxl_io_manager = referenced_port[1]
        self._cxl_cache_manager = referenced_port[2]
        self._pci_bridge_component = referenced_port[3]
        self._pci_registers = referenced_port[4]
        self._cxl_component = referenced_port[5]
        self._upstream_connection = referenced_port[6]
        self._downstream_connection = referenced_port[7]
        self._ld_id = ld_id

    def bind_to_physical_usp_port(self, physical_port: CxlPortDevice):
        # pylint: disable=protected-access
        physical_port = cast(UpstreamPortDevice, physical_port)
        self._cxl_mem_manager = physical_port._cxl_mem_manager
        self._cxl_io_manager = physical_port._cxl_io_manager
        self._cxl_cache_manager = physical_port._cxl_cache_manager
        self._pci_bridge_component = physical_port._pci_bridge_component
        self._pci_registers = physical_port._pci_registers
        self._cxl_component = physical_port._cxl_component
        self._upstream_connection = physical_port._vppb_upstream_connection
        self._downstream_connection = physical_port._vppb_downstream_connection

    async def unbind_from_physical_port(self, physical_port: CxlPortDevice):
        await physical_port.unbind_from_vppb(self._ld_id)
        self._cxl_mem_manager = None
        self._cxl_io_manager = None
        self._cxl_cache_manager = None
        self._pci_bridge_component = None
        self._pci_registers = None
        self._cxl_component = None
        self._ld_id = 0
        # TODO: Other source code may not be able to handle None
        self._upstream_connection = None
        self._downstream_connection = None
        logger.info(f"VPPB unbinded from physical port, type: {physical_port.get_device_type()}")

    @abstractmethod
    def set_routing_table(self, vppb_routing_info: VppbRoutingInfo):
        """This must be implemented in the child class"""

    @abstractmethod
    def get_device_type(self) -> CXL_COMPONENT_TYPE:
        """This must be implemented in the child class"""
