"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from typing import TypedDict, List, Optional

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


class FlexBusPortDvsecHeader1(BitMaskedBitStructure):
    _fields = [
        BitField("dvsec_vendor_id", 0, 15, FIELD_ATTR.RO, 0x1E98),
        BitField("dvsec_revision_id", 16, 19, FIELD_ATTR.RO, 0x2),
        BitField("dvsec_length", 20, 31, FIELD_ATTR.RO, 0x020),
    ]


class DvsecFlexBusPortCapability1(BitMaskedBitStructure):
    _fields = [
        BitField("cache_capable", 0, 0, FIELD_ATTR.HW_INIT),
        BitField("io_capable", 1, 1, FIELD_ATTR.HW_INIT, 1),
        BitField("mem_capable", 2, 2, FIELD_ATTR.HW_INIT),
        BitField("reserved1", 3, 4, FIELD_ATTR.RESERVED),
        BitField("cxl_68b_flit_and_vh_capable", 5, 5, FIELD_ATTR.HW_INIT),
        BitField("cxl_multi_logical_device_capable", 6, 6, FIELD_ATTR.HW_INIT),
        BitField("reserved2", 7, 12, FIELD_ATTR.RESERVED),
        BitField("cxl_latency_optimized_256b_flit_capable", 13, 13, FIELD_ATTR.HW_INIT),
        BitField("cxl_pbr_flit_capable", 14, 14, FIELD_ATTR.HW_INIT),
        BitField("reserved3", 15, 15, FIELD_ATTR.RESERVED),
    ]


class DvsecFlexBusPortControl(BitMaskedBitStructure):
    _fields = [
        BitField("cache_enable", 0, 0, FIELD_ATTR.HW_INIT),
        BitField("io_enable", 1, 1, FIELD_ATTR.RO, 1),
        BitField("mem_enable", 2, 2, FIELD_ATTR.HW_INIT),
        BitField("cxl_sync_hdr_bypass_enable", 3, 3, FIELD_ATTR.HW_INIT),
        BitField("drift_buffer_enable", 4, 4, FIELD_ATTR.HW_INIT),
        BitField("cxl_68b_flit_and_vh_enable", 5, 5, FIELD_ATTR.HW_INIT),
        BitField("cxl_multi_logical_device_enable", 6, 6, FIELD_ATTR.HW_INIT),
        BitField("disable_rcd_training", 7, 7, FIELD_ATTR.HW_INIT),
        BitField("retimer1_present", 8, 8, FIELD_ATTR.RESERVED),
        BitField("retimer2_present", 9, 9, FIELD_ATTR.RESERVED),
        BitField("reserved2", 10, 12, FIELD_ATTR.RESERVED),
        BitField("cxl_latency_optimized_256_flit_enable", 13, 13, FIELD_ATTR.HW_INIT),
        BitField("cxl_pbr_flit_enable", 14, 14, FIELD_ATTR.HW_INIT),
        BitField("reserved3", 15, 15, FIELD_ATTR.RESERVED),
    ]


class DvsecFlexBusPortStatus(BitMaskedBitStructure):
    _fields = [
        BitField("cache_enabled", 0, 0, FIELD_ATTR.RO),
        BitField("io_enabled", 1, 1, FIELD_ATTR.RO),
        BitField("mem_enabled", 2, 2, FIELD_ATTR.RO),
        BitField("cxl_sync_hdr_bypass_enabled", 3, 3, FIELD_ATTR.RO),
        BitField("drift_buffer_enabled", 4, 4, FIELD_ATTR.RO),
        BitField("cxl_68b_flit_and_vh_enabled", 5, 5, FIELD_ATTR.RO),
        BitField("cxl_multi_logical_device_enabled", 6, 6, FIELD_ATTR.RO),
        BitField("even_half_failed", 7, 7, FIELD_ATTR.RW1CS),
        BitField("cxl_correctable_protocol_id_framing_error", 8, 8, FIELD_ATTR.RW1CS),
        BitField("cxl_uncorrectable_protocol_id_framing_error", 9, 9, FIELD_ATTR.RW1CS),
        BitField("cxl_unexpected_protocol_id_dropped", 10, 10, FIELD_ATTR.RW1CS),
        BitField("cxl_retimers_present_mismatch", 11, 11, FIELD_ATTR.RW1CS),
        BitField("flex_bus_enabled_bits_phase2_mismatch", 12, 12, FIELD_ATTR.RW1CS),
        BitField("cxl_latency_optimized_256_flit_enabled", 13, 13, FIELD_ATTR.RO),
        BitField("cxl_pbr_flit_enabled", 14, 14, FIELD_ATTR.RO),
        BitField("cxl_io_throttle_required_at_64gts", 15, 15, FIELD_ATTR.RO),
    ]


class DvsecFlexBusPortReceivedModifiedTsDataPhase1(BitMaskedBitStructure):
    _fields = [
        BitField("received_flex_bus_data_phase1", 0, 23, FIELD_ATTR.RO),
        BitField("reserved1", 24, 31, FIELD_ATTR.RESERVED),
    ]


class DvsecFlexBusPortCapability2(BitMaskedBitStructure):
    _fields = [
        BitField("nop_hint_capable", 0, 0, FIELD_ATTR.RO),
        BitField("reserved1", 1, 31, FIELD_ATTR.RESERVED),
    ]


class DvsecFlexBusPortControl2(BitMaskedBitStructure):
    _fields = [
        BitField("nop_hint_enable", 0, 0, FIELD_ATTR.RW),
        BitField("reserved1", 1, 31, FIELD_ATTR.RESERVED),
    ]


class DvsecFlexBusPortStatus2(BitMaskedBitStructure):
    _fields = [
        BitField("nop_hint_info", 0, 0, FIELD_ATTR.RO),
        BitField("reserved1", 1, 31, FIELD_ATTR.RESERVED),
    ]


class DvsecFlexBusPortCapabilityOptions(TypedDict):
    header: Optional[DvsecCapabilityHeaderOptions]


class DvsecFlexBusPortCapability(BitMaskedBitStructure):
    def __init__(
        self,
        data: Optional[ShareableByteArray] = None,
        parent_name: Optional[str] = None,
        options: Optional[DvsecFlexBusPortCapabilityOptions] = None,
    ):
        header_options = None
        if options:
            header_options = options.get("header")

        self._fields = [
            StructureField(
                "capability_header", 0, 3, DvsecCapabilityHeader, options=header_options
            ),
            StructureField("dvsec_header1", 4, 7, FlexBusPortDvsecHeader1),
            ByteField("dvsec_header2", 8, 9, attribute=FIELD_ATTR.RO, default=0x0007),
            StructureField("flex_bus_port_capability", 0xA, 0xB, DvsecFlexBusPortCapability1),
            StructureField("flex_bus_control", 0xC, 0xD, DvsecFlexBusPortControl),
            StructureField("flex_bus_status", 0xE, 0xF, DvsecFlexBusPortStatus),
            StructureField(
                "flex_bus_received_modified_ts_data_phase1",
                0x10,
                0x13,
                DvsecFlexBusPortReceivedModifiedTsDataPhase1,
            ),
            StructureField("flex_bus_port_capability2", 0x14, 0x17, DvsecFlexBusPortCapability2),
            StructureField("flex_bus_port_control2", 0x18, 0x1B, DvsecFlexBusPortControl2),
            StructureField("flex_bus_port_status2", 0x1C, 0x1F, DvsecFlexBusPortStatus2),
        ]

        super().__init__(data, parent_name)

    @staticmethod
    def get_size(fields: List[DataField] | None = None) -> int:
        return 0x20
