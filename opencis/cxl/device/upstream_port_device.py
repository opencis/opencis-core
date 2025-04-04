"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

import re

from opencis.cxl.component.cxl_cache_manager import CxlCacheManager
from opencis.cxl.component.cxl_io_callback_data import CxlIoCallbackData
from opencis.util.logger import logger
from opencis.cxl.component.common import CXL_COMPONENT_TYPE
from opencis.cxl.device.port_device import CxlPortDevice
from opencis.cxl.config_space.doe.doe import CxlDoeExtendedCapabilityOptions
from opencis.cxl.config_space.dvsec import (
    DvsecConfigSpaceOptions,
    DvsecRegisterLocatorOptions,
    CXL_DEVICE_TYPE,
)
from opencis.cxl.config_space.port import (
    CxlUpstreamPortConfigSpace,
    CxlUpstreamPortConfigSpaceOptions,
)
from opencis.cxl.mmio import CombinedMmioRegister, CombinedMmioRegiterOptions
from opencis.cxl.component.cxl_connection import CxlConnection
from opencis.cxl.component.cxl_bridge_component import (
    CxlUpstreamPortComponent,
    HDM_DECODER_COUNT,
)
from opencis.cxl.component.virtual_switch.vppb_routing_info import VppbRoutingInfo
from opencis.cxl.component.cxl_mem_manager import CxlMemManager
from opencis.cxl.component.cxl_io_manager import CxlIoManager
from opencis.pci.component.pci import (
    PciBridgeComponent,
    PCI_BRIDGE_TYPE,
    PciComponentIdentity,
    EEUM_VID,
    SW_USP_DID,
    PCI_CLASS,
    PCI_BRIDGE_SUBCLASS,
    PCI_DEVICE_PORT_TYPE,
)
from opencis.pci.component.mmio_manager import BarEntry
from opencis.pci.component.config_space_manager import PCI_DEVICE_TYPE


# Shares code between DownstreamPortDevice
# pylint: disable=duplicate-code
class UpstreamPortDevice(CxlPortDevice):
    def __init__(self, transport_connection: CxlConnection, port_index: int):
        super().__init__(transport_connection, port_index)
        self._decoder_count = HDM_DECODER_COUNT.DECODER_32
        self._vppb_upstream_connection = transport_connection

        label = f"USP{self._port_index}"
        self._label = label
        self._pci_bridge_component = None
        self._pci_registers = None

        self._cxl_component = CxlUpstreamPortComponent(
            decoder_count=self._decoder_count,
            label=label,
        )
        self._cxl_io_manager = CxlIoManager(
            self._vppb_upstream_connection.mmio_fifo,
            self._vppb_downstream_connection.mmio_fifo,
            self._vppb_upstream_connection.cfg_fifo,
            self._vppb_downstream_connection.cfg_fifo,
            device_type=PCI_DEVICE_TYPE.UPSTREAM_BRIDGE,
            init_callback=self._init_device,
            label=label,
        )
        self._cxl_mem_manager = CxlMemManager(
            upstream_fifo=self._vppb_upstream_connection.cxl_mem_fifo,
            downstream_fifo=self._vppb_downstream_connection.cxl_mem_fifo,
            label=label,
        )
        self._cxl_cache_manager = CxlCacheManager(
            upstream_fifo=self._vppb_upstream_connection.cxl_cache_fifo,
            downstream_fifo=self._vppb_downstream_connection.cxl_cache_fifo,
            label=label,
        )

    def _init_device(
        self,
        cxl_io_callback_data: CxlIoCallbackData,
    ):
        pci_identity = PciComponentIdentity(
            vendor_id=EEUM_VID,
            device_id=SW_USP_DID,
            base_class_code=PCI_CLASS.BRIDGE,
            sub_class_coce=PCI_BRIDGE_SUBCLASS.PCI_BRIDGE,
            programming_interface=0x00,
            device_port_type=PCI_DEVICE_PORT_TYPE.UPSTREAM_PORT_OF_PCI_EXPRESS_SWITCH,
        )
        self._pci_bridge_component = PciBridgeComponent(
            identity=pci_identity,
            type=PCI_BRIDGE_TYPE.UPSTREAM_PORT,
            mmio_manager=cxl_io_callback_data.mmio_manager,
        )

        # NOTE: Create MMIO Register
        mmio_options = CombinedMmioRegiterOptions(cxl_component=self._cxl_component)
        mmio_register = CombinedMmioRegister(options=mmio_options)
        cxl_io_callback_data.mmio_manager.set_bar_entries([BarEntry(mmio_register)])

        # NOTE: Create Config Space Register
        doe_options = CxlDoeExtendedCapabilityOptions(cdat_entries=[])
        pci_registers_options = CxlUpstreamPortConfigSpaceOptions(
            pci_bridge_component=self._pci_bridge_component,
            dvsec=DvsecConfigSpaceOptions(
                device_type=CXL_DEVICE_TYPE.USP,
                register_locator=DvsecRegisterLocatorOptions(
                    registers=mmio_register.get_dvsec_register_offsets()
                ),
            ),
            doe=doe_options,
        )
        self._pci_registers = CxlUpstreamPortConfigSpace(options=pci_registers_options)
        cxl_io_callback_data.config_space_manager.set_register(self._pci_registers)

    def get_reg_vals(self):
        return self._cxl_io_manager.get_cfg_reg_vals()

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
