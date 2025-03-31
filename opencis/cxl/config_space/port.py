"""
Copyright (c) 2024, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from typing import Optional, TypedDict

from opencis.cxl.config_space.cfg import CxlConfigSpace
from opencis.cxl.config_space.dvsec import DvsecConfigSpaceOptions, CXL_DEVICE_TYPE
from opencis.cxl.config_space.doe.doe import CxlDoeExtendedCapabilityOptions
from opencis.pci.component.pci import PciBridgeComponent
from opencis.pci.config_space import PciExpressPortConfigSpaceOptions
from opencis.util.unaligned_bit_structure import ShareableByteArray


class CxlUpstreamPortConfigSpaceOptions(TypedDict):
    pci_bridge_component: PciBridgeComponent
    dvsec: DvsecConfigSpaceOptions
    doe: CxlDoeExtendedCapabilityOptions


class CxlDownstreamPortConfigSpaceOptions(TypedDict):
    pci_bridge_component: PciBridgeComponent
    dvsec: DvsecConfigSpaceOptions


class CxlPortConfigSpace(CxlConfigSpace):
    def __init__(
        self,
        device_type: CXL_DEVICE_TYPE,
        options: PciExpressPortConfigSpaceOptions,
        data: Optional[ShareableByteArray] = None,
        parent_name: Optional[str] = None,
    ):
        self._pci_component = options["pci_bridge_component"]
        self._doe_options = None
        if device_type is CXL_DEVICE_TYPE.USP:
            self._doe_options = options["doe"]
        self._dvsec_options = options["dvsec"]
        super().__init__(device_type, data, parent_name)


class CxlUpstreamPortConfigSpace(CxlPortConfigSpace):
    pci: PciBridgeComponent

    def __init__(
        self,
        options: CxlUpstreamPortConfigSpaceOptions,
        data: Optional[ShareableByteArray] = None,
        parent_name: Optional[str] = None,
    ):
        super().__init__(CXL_DEVICE_TYPE.USP, options, data, parent_name)


class CxlDownstreamPortConfigSpace(CxlPortConfigSpace):
    pci: PciBridgeComponent

    def __init__(
        self,
        options: CxlDownstreamPortConfigSpaceOptions,
        data: Optional[ShareableByteArray] = None,
        parent_name: Optional[str] = None,
    ):
        super().__init__(CXL_DEVICE_TYPE.DSP, options, data, parent_name)
