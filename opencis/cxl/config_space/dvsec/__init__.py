"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from enum import Enum, auto
from typing import TypedDict, Optional

from opencis.cxl.config_space.dvsec.cxl_extension_dvsec_for_ports import (
    CxlExtensionDvsecForPorts,
    CxlExtensionDvsecForPortsOptions,
)
from opencis.cxl.component.cxl_memory_device_component import CxlMemoryDeviceComponent
from opencis.cxl.config_space.dvsec.mld_dvsec import (
    MldDvsec,
    MldDvsecOptions,
)
from opencis.util.unaligned_bit_structure import (
    ShareableByteArray,
    BitMaskedBitStructure,
    StructureField,
)
from .cxl_devices import (
    DvsecCxlCacheableRangeOptions,
    DvsecCxlCapabilityOptions,
    DvsecCxlDevices,
    DvsecCxlDevicesOptions,
)
from .flex_bus_port import DvsecFlexBusPortCapability, DvsecFlexBusPortCapabilityOptions
from .register_locator import DvsecRegisterLocator, DvsecRegisterLocatorOptions


class CXL_DEVICE_TYPE(Enum):
    USP = auto()
    DSP = auto()
    LD = auto()
    ACCEL_T1 = auto()
    ACCEL_T2 = auto()
    FMLD = auto()


class DvsecConfigSpaceOptions(TypedDict):
    device_type: CXL_DEVICE_TYPE
    offset: int
    next: int
    register_locator: DvsecRegisterLocatorOptions
    memory_device_component: Optional[CxlMemoryDeviceComponent]
    capability_options: Optional[DvsecCxlCapabilityOptions]
    cacheable_address_range: Optional[DvsecCxlCacheableRangeOptions]


class DvsecConfigSpace(BitMaskedBitStructure):
    def __init__(
        self,
        data: Optional[ShareableByteArray] = None,
        parent_name: Optional[str] = None,
        options: Optional[DvsecConfigSpaceOptions] = None,
    ):
        if not options:
            raise Exception("options is required")

        self._last_offset_header = None
        self._device_type = options["device_type"]
        self._capability_offset = options["offset"]
        self._register_locator_options = options["register_locator"]
        next_offset = options["next"]
        memory_device_component = options.get("memory_device_component")
        capability_options = options.get("capability_options")
        cacheable_address_range = options.get("cacheable_address_range")

        self._fields = []

        start = 0
        start = self._add_cxl_devices_dvsec(
            start, memory_device_component, capability_options, cacheable_address_range
        )
        start = self._add_cxl_extension_dvsec_for_ports(start)
        start = self._add_pcie_dvsec_for_flex_bus_ports(start)
        start = self._add_register_locator_dvsec(start)
        start = self._add_mld_dvsec(start)
        if self._last_offset_header:
            self._last_offset_header["next_capability_offset"] = next_offset

        super().__init__(data, parent_name)

    def _add_cxl_devices_dvsec(
        self,
        start: int,
        memory_device_component: Optional[DvsecConfigSpaceOptions] = None,
        capability_options: Optional[DvsecCxlCapabilityOptions] = None,
        cacheable_address_range: Optional[DvsecCxlCacheableRangeOptions] = None,
    ) -> int:
        if self._device_type not in (
            CXL_DEVICE_TYPE.LD,
            CXL_DEVICE_TYPE.ACCEL_T1,
            CXL_DEVICE_TYPE.ACCEL_T2,
        ):
            return start

        if not memory_device_component:
            raise Exception("memory_device_component is required")
        if not capability_options:
            raise Exception("capability_options is required")

        dvsec_size = DvsecCxlDevices.get_size()
        end = start + dvsec_size - 1
        next = end + 1 + self._capability_offset
        dvsec_options: DvsecCxlDevicesOptions = {
            "header": {"next_capability_offset": next},
            "memory_device_component": memory_device_component,
            "capability_options": capability_options,
            "cacheable_address_range": cacheable_address_range,
        }
        self._last_offset_header = dvsec_options["header"]
        self._fields.append(
            StructureField(
                "cxl_devices",
                start,
                end,
                DvsecCxlDevices,
                options=dvsec_options,
            )
        )
        return end + 1

    def _add_cxl_extension_dvsec_for_ports(self, start: int) -> int:
        is_port = self._device_type in (CXL_DEVICE_TYPE.USP, CXL_DEVICE_TYPE.DSP)
        if not is_port:
            return start

        dvsec_size = CxlExtensionDvsecForPorts.get_size()
        end = start + dvsec_size - 1
        next = end + 1 + self._capability_offset
        dvsec_options: CxlExtensionDvsecForPortsOptions = {
            "header": {"next_capability_offset": next}
        }
        self._last_offset_header = dvsec_options["header"]
        self._fields.append(
            StructureField(
                "cxl_extension_dvsec_for_ports",
                start,
                end,
                CxlExtensionDvsecForPorts,
                options=dvsec_options,
            )
        )
        return end + 1

    def _add_pcie_dvsec_for_flex_bus_ports(self, start: int) -> int:
        dvsec_size = DvsecFlexBusPortCapability.get_size()
        end = start + dvsec_size - 1
        next = end + 1 + self._capability_offset
        dvsec_options: DvsecFlexBusPortCapabilityOptions = {
            "header": {"next_capability_offset": next}
        }
        self._last_offset_header = dvsec_options["header"]
        self._fields.append(
            StructureField(
                "flex_bus_port",
                start,
                end,
                DvsecFlexBusPortCapability,
                options=dvsec_options,
            )
        )
        return end + 1

    def _add_register_locator_dvsec(self, start: int) -> int:
        dvsec_size = DvsecRegisterLocator.get_size_from_options(self._register_locator_options)

        if len(self._register_locator_options["registers"]) == 0:
            return start

        dvsec_options = self._register_locator_options

        end = start + dvsec_size - 1
        next = end + 1 + self._capability_offset
        dvsec_options["header"] = {"next_capability_offset": next}
        self._last_offset_header = dvsec_options["header"]
        self._fields.append(
            StructureField(
                "register_locator",
                start,
                end,
                DvsecRegisterLocator,
                options=dvsec_options,
            )
        )
        return end + 1

    def _add_mld_dvsec(self, start: int) -> int:
        if self._device_type != CXL_DEVICE_TYPE.FMLD:
            return start

        dvsec_size = MldDvsec.get_size()
        end = start + dvsec_size - 1
        next = end + 1 + self._capability_offset
        dvsec_options: MldDvsecOptions = {"header": {"next_capability_offset": next}}
        self._last_offset_header = dvsec_options["header"]
        self._fields.append(
            StructureField(
                "mld_dvsec",
                start,
                end,
                MldDvsec,
                options=dvsec_options,
            )
        )
        return end + 1

    @staticmethod
    def get_size_from_options(options: DvsecConfigSpaceOptions) -> int:
        size = 0
        device_type = options["device_type"]

        if device_type in (CXL_DEVICE_TYPE.LD, CXL_DEVICE_TYPE.ACCEL_T1, CXL_DEVICE_TYPE.ACCEL_T2):
            size += DvsecCxlDevices.get_size()
        elif device_type in (CXL_DEVICE_TYPE.USP, CXL_DEVICE_TYPE.DSP):
            size += CxlExtensionDvsecForPorts.get_size()

        size += DvsecFlexBusPortCapability.get_size()

        if len(options["register_locator"]["registers"]) > 0:
            register_locator_options = options["register_locator"]
            size += DvsecRegisterLocator.get_size_from_options(register_locator_options)

        return size
