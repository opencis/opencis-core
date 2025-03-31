"""
Copyright (c) 2024, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from dataclasses import dataclass
from typing import TypedDict, List, Optional

from opencis.util.number_const import MB
from opencis.util.unaligned_bit_structure import (
    ShareableByteArray,
    BitMaskedBitStructure,
    BitField,
    ByteField,
    StructureField,
    DataField,
    FIELD_ATTR,
)
from opencis.cxl.config_space.dvsec.common import (
    DvsecCapabilityHeader,
    DvsecCapabilityHeaderOptions,
)
from opencis.cxl.component.cxl_memory_device_component import CxlMemoryDeviceComponent


class CxlDvsecHeader1(BitMaskedBitStructure):
    _fields = [
        BitField("dvsec_vendor_id", 0, 15, FIELD_ATTR.RO, 0x1E98),
        BitField("dvsec_revision_id", 16, 19, FIELD_ATTR.RO, 0x2),
        BitField("dvsec_length", 20, 31, FIELD_ATTR.RO, 0x03C),
    ]


@dataclass
class DvsecCxlCapabilityOptions:
    cache_capable: int
    mem_capable: int
    hdm_count: int
    cache_writeback_and_invalidate_capable: int
    cache_size_unit: int
    cache_size: int


class DvsecCxlCapability(BitMaskedBitStructure):
    def __init__(
        self,
        data: Optional[ShareableByteArray] = None,
        parent_name: Optional[str] = None,
        options: Optional[DvsecCxlCapabilityOptions] = None,
    ):
        if options is None:
            raise Exception("options is required")
        self._fields = [
            BitField("cache_capable", 0, 0, FIELD_ATTR.RO, options.cache_capable),
            BitField("io_capable", 1, 1, FIELD_ATTR.RO, 1),
            BitField("mem_capable", 2, 2, FIELD_ATTR.RO, options.mem_capable),
            BitField("mem_hwinit_mode", 3, 3, FIELD_ATTR.RO),
            BitField("hdm_count", 4, 5, FIELD_ATTR.RO, options.hdm_count),
            BitField(
                "cache_writeback_and_invalidate_capable",
                6,
                6,
                FIELD_ATTR.RO,
                options.cache_writeback_and_invalidate_capable,
            ),
            BitField("cxl_reset_capable", 7, 7, FIELD_ATTR.RO),
            BitField("cxl_reset_timeout", 8, 10, FIELD_ATTR.RO),
            BitField("cxl_reset_mem_clr_capable", 11, 11, FIELD_ATTR.HW_INIT),
            BitField("tsp_capable", 12, 12, FIELD_ATTR.HW_INIT),
            BitField("multiple_logical_devices", 13, 13, FIELD_ATTR.HW_INIT),
            BitField("viral_capable", 14, 14, FIELD_ATTR.RO),
            BitField("pm_init_completion_reporting_capable", 15, 15, FIELD_ATTR.HW_INIT),
        ]
        super().__init__(data, parent_name)


class DvsecCxlControl(BitMaskedBitStructure):
    _fields = [
        BitField("cache_enable", 0, 0, FIELD_ATTR.RWL),
        BitField("io_enable", 1, 1, FIELD_ATTR.RO, 1),
        BitField("mem_enable", 2, 2, FIELD_ATTR.RWL),
        BitField("cache_sf_coverage", 3, 7, FIELD_ATTR.RWL),
        BitField("cache_sf_granularity", 8, 10, FIELD_ATTR.RWL),
        BitField("cache_clean_eviction", 11, 11, FIELD_ATTR.RWL),
        BitField("reserved1", 12, 13, FIELD_ATTR.RESERVED),
        BitField("viral_enable", 14, 14, FIELD_ATTR.RW),
        BitField("reserved2", 15, 15, FIELD_ATTR.RESERVED),
    ]


class DvsecCxlStatus(BitMaskedBitStructure):
    _fields = [
        BitField("reserved1", 0, 13, FIELD_ATTR.RO),
        BitField("viral_status", 14, 14, FIELD_ATTR.RW1CS),
        BitField("reserved2", 15, 15, FIELD_ATTR.RESERVED),
    ]


class DvsecCxlControl2(BitMaskedBitStructure):
    _fields = [
        BitField("disable_caching", 0, 0, FIELD_ATTR.RW),
        BitField("initiate_cache_write_back_and_invalidate", 1, 1, FIELD_ATTR.RW),
        BitField("initiate_cxl_reset", 2, 2, FIELD_ATTR.RW),
        BitField("cxl_reset_mem_clr_enable", 3, 3, FIELD_ATTR.RW),
        BitField("desired_volatile_hdm_status_after_hot_reset", 4, 4, FIELD_ATTR.RO),
        BitField("reserved1", 5, 15, FIELD_ATTR.RO),
    ]


class DvsecCxlStatus2(BitMaskedBitStructure):
    _fields = [
        BitField("cache_invalid", 0, 0, FIELD_ATTR.RO),
        BitField("cxl_reset_complete", 1, 1, FIELD_ATTR.RO),
        BitField("cxl_reset_error", 2, 2, FIELD_ATTR.RO),
        BitField("volatile_hdm_preservation_error", 3, 3, FIELD_ATTR.RW1CS),
        BitField("reserved", 4, 14, FIELD_ATTR.RESERVED),
        BitField("power_management_initialization_complete", 15, 15, FIELD_ATTR.RO),
    ]


class DvsecCxlLock(BitMaskedBitStructure):
    _fields = [
        BitField("config_lock", 0, 0, FIELD_ATTR.RWO),
        BitField("reserved1", 1, 15, FIELD_ATTR.RESERVED),
    ]


class DvsecCxlCapability2(BitMaskedBitStructure):
    _fields = [
        BitField("cache_size_unit", 0, 3, FIELD_ATTR.RO),
        BitField("fallback_capability", 4, 5, FIELD_ATTR.HW_INIT),
        BitField("modified_completion_capable", 6, 6, FIELD_ATTR.HW_INIT),
        BitField("no_clean_writeback", 7, 7, FIELD_ATTR.HW_INIT),
        BitField("cache_size", 8, 15, FIELD_ATTR.RO),
    ]


class DvsecCxlRangeSizeLowOptions(TypedDict):
    memory_size_low: int
    is_valid: bool


class DvsecCxlRangeSizeLow(BitMaskedBitStructure):
    def __init__(
        self,
        data: ShareableByteArray | None = None,
        parent_name: str | None = None,
        options: Optional[DvsecCxlRangeSizeLowOptions] = None,
    ):
        if not options:
            raise Exception("options is required")

        memory_size_low = options["memory_size_low"]
        is_valid = options["is_valid"]

        self._fields = [
            BitField("memory_info_valid", 0, 0, FIELD_ATTR.RO, 1 if is_valid else 0),
            BitField("memory_active", 1, 1, FIELD_ATTR.RO, 1 if is_valid else 0),
            BitField("media_type", 2, 4, FIELD_ATTR.RO, 0b10),
            BitField("memory_class", 5, 7, FIELD_ATTR.RO, 0b10),
            BitField("desired_interleave", 8, 12, FIELD_ATTR.RO),
            BitField("memory_active_timeout", 13, 15, FIELD_ATTR.HW_INIT),
            BitField("reserved", 16, 27, FIELD_ATTR.RESERVED),
            BitField("memory_size_low", 28, 31, FIELD_ATTR.RO, memory_size_low >> 28),
        ]

        super().__init__(data, parent_name)


class DvsecCxlRangeBaseLow(BitMaskedBitStructure):
    _fields = [
        BitField("reserved1", 0, 27, FIELD_ATTR.RESERVED),
        BitField("memory_base_low", 28, 31, FIELD_ATTR.RWL),
    ]


@dataclass
class DvsecCxlCacheableRangeOptions:
    start_addr: int
    end_addr: int


class DvsecCxlCacheableRange(BitMaskedBitStructure):
    def __init__(
        self,
        data: Optional[ShareableByteArray] = None,
        parent_name: Optional[str] = None,
        options: Optional[DvsecCxlCacheableRangeOptions] = None,
    ):
        if options is None:
            raise Exception("options is required")
        self._fields = [
            BitField("start_addr", 0, 45, FIELD_ATTR.HW_INIT, options.start_addr),
            BitField("end_addr", 46, 91, FIELD_ATTR.HW_INIT, options.end_addr),
            BitField("reserved", 92, 95, FIELD_ATTR.RESERVED),
        ]
        super().__init__(data, parent_name)


class DvsecCxlCapability3(BitMaskedBitStructure):
    _fields = [
        BitField("default_volatile_hdm_state_after_cold_reset", 0, 0, FIELD_ATTR.HW_INIT),
        BitField("default_volatile_hdm_state_after_warm_reset", 1, 1, FIELD_ATTR.HW_INIT),
        BitField("default_volatile_hdm_state_after_hot_reset", 2, 2, FIELD_ATTR.HW_INIT),
        BitField(
            "volatile_hdml_state_after_hot_reset_configurability",
            3,
            3,
            FIELD_ATTR.HW_INIT,
        ),
        BitField("reserved1", 4, 15, FIELD_ATTR.RESERVED),
    ]


class DvsecCxlDevicesOptions(TypedDict):
    header: Optional[DvsecCapabilityHeaderOptions]
    memory_device_component: CxlMemoryDeviceComponent
    capability_options: DvsecCxlCapabilityOptions
    cacheable_address_range: DvsecCxlCacheableRangeOptions


class DvsecCxlDevices(BitMaskedBitStructure):
    def __init__(
        self,
        data: Optional[ShareableByteArray] = None,
        parent_name: Optional[str] = None,
        options: Optional[DvsecCxlDevicesOptions] = None,
    ):
        if not options:
            raise Exception("options is required")

        header_options = options.get("header")
        memory_device_component = options["memory_device_component"]
        capability_options = options["capability_options"]
        cacheable_address_range = options["cacheable_address_range"]
        identity = memory_device_component.get_identity()

        volatile_only_capacity = identity.volatile_only_capacity * 256 * MB

        range1_size_low_options: DvsecCxlRangeSizeLowOptions = {
            "memory_size_low": volatile_only_capacity & 0xFFFFFFFF,
            "is_valid": True,
        }
        range1_size_high = volatile_only_capacity >> 32
        range2_size_low_options: DvsecCxlRangeSizeLowOptions = {
            "memory_size_low": 0,
            "is_valid": False,
        }

        self._fields = [
            StructureField(
                "capability_header", 0, 3, DvsecCapabilityHeader, options=header_options
            ),
            StructureField("dvsec_header1", 4, 7, CxlDvsecHeader1),
            ByteField("dvsec_header2", 8, 9, attribute=FIELD_ATTR.RO, default=0x0000),
            StructureField(
                "cxl_capability", 0xA, 0xB, DvsecCxlCapability, options=capability_options
            ),
            StructureField("cxl_control", 0xC, 0xD, DvsecCxlControl),
            StructureField("cxl_status", 0xE, 0xF, DvsecCxlStatus),
            StructureField("cxl_control2", 0x10, 0x11, DvsecCxlControl2),
            StructureField("cxl_status2", 0x12, 0x13, DvsecCxlStatus2),
            StructureField("cxl_lock", 0x14, 0x15, DvsecCxlLock),
            StructureField("cxl_capability2", 0x16, 0x17, DvsecCxlCapability2),
            ByteField("range1_size_high", 0x18, 0x1B, default=range1_size_high),
            StructureField(
                "range1_size_low",
                0x1C,
                0x1F,
                DvsecCxlRangeSizeLow,
                options=range1_size_low_options,
            ),
            ByteField("range1_base_high", 0x20, 0x23),
            StructureField("range1_base_low", 0x24, 0x27, DvsecCxlRangeBaseLow),
            ByteField("range2_size_high", 0x28, 0x2B),
            StructureField(
                "range2_size_low",
                0x2C,
                0x2F,
                DvsecCxlRangeSizeLow,
                options=range2_size_low_options,
            ),
            ByteField("range2_base_high", 0x30, 0x33),
            StructureField("range2_base_low", 0x34, 0x37, DvsecCxlRangeBaseLow),
            StructureField("cxl_capability3", 0x38, 0x39, DvsecCxlCapability3),
            ByteField("reserved1", 0x3A, 0x3F),
            StructureField(
                "cxl_cacheable_range",
                0x40,
                0x4B,
                DvsecCxlCacheableRange,
                options=cacheable_address_range,
            ),
        ]

        super().__init__(data, parent_name)

    @staticmethod
    def get_size(fields: List[DataField] | None = None) -> int:
        return 0x4C
