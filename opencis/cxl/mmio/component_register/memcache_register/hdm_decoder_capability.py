"""
Copyright (c) 2024, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from typing import TypedDict, Optional, Callable
from opencis.util.unaligned_bit_structure import (
    BitMaskedBitStructure,
    BitField,
    StructureField,
    ByteField,
    FIELD_ATTR,
    ShareableByteArray,
)
from opencis.cxl.component.hdm_decoder import (
    HdmDecoderManagerBase,
    DecoderInfo,
    CXL_DEVICE_TYPE,
)

MAX_DECODER_TARGETS = 8


class CxlHdmDecoderCapabilityRegisterOptions(TypedDict):
    hdm_decoder_manager: HdmDecoderManagerBase


class CxlHdmDecoderCapabilityRegister(BitMaskedBitStructure):
    decoder_count: int
    target_count: int
    a11to8_interleave_capable: int
    a14to12_interleave_capable: int
    poison_on_decoder_error_capability: int
    three_six_twelve_way_interleave_capable: int
    sixteen_way_interleave_capable: int
    uio_capable: int
    uio_capable_decoder_count: int
    mem_data_nxm_capable: int

    def __init__(
        self,
        data: Optional[ShareableByteArray] = None,
        parent_name: Optional[str] = None,
        options: Optional[CxlHdmDecoderCapabilityRegisterOptions] = None,
    ):
        if not options:
            raise Exception("options is required")

        self.hdm_decoder_manager = options["hdm_decoder_manager"]

        self._fields = [
            BitField("decoder_count", 0, 3, FIELD_ATTR.RO),
            BitField("target_count", 4, 7, FIELD_ATTR.RO),
            BitField("a11to8_interleave_capable", 8, 8, FIELD_ATTR.RO),
            BitField("a14to12_interleave_capable", 9, 9, FIELD_ATTR.RO),
            BitField("poison_on_decoder_error_capability", 10, 10, FIELD_ATTR.RO),
            BitField("three_six_twelve_way_interleave_capable", 11, 11, FIELD_ATTR.RO),
            BitField("sixteen_way_interleave_capable", 12, 12, FIELD_ATTR.RO),
            BitField("uio_capable", 13, 13, FIELD_ATTR.HW_INIT),
            BitField("reserved1", 14, 15, FIELD_ATTR.RESERVED),
            BitField("uio_capable_decoder_count", 16, 19, FIELD_ATTR.HW_INIT),
            BitField("mem_data_nxm_capable", 20, 20, FIELD_ATTR.HW_INIT),
            BitField("reserved2", 21, 31, FIELD_ATTR.RESERVED),
        ]

        super().__init__(data, parent_name)

    def read_bytes(self, start_offset: int, end_offset: int) -> int:
        capabilities = self.hdm_decoder_manager.get_capabilities()
        self.write_fields_from_dict(capabilities)
        return super().read_bytes(start_offset, end_offset)


class CxlHdmDecoderGlobalControlRegisterOptions(TypedDict):
    hdm_decoder_manager: HdmDecoderManagerBase


class CxlHdmDecoderGlobalControlRegister(BitMaskedBitStructure):
    poison_on_decode_error_enable: int
    hdm_decoder_enable: int

    def __init__(
        self,
        data: Optional[ShareableByteArray] = None,
        parent_name: Optional[str] = None,
        options: Optional[CxlHdmDecoderGlobalControlRegisterOptions] = None,
    ):
        if not options:
            raise Exception("options is required")

        self.hdm_decoder_manager = options["hdm_decoder_manager"]
        capabilities = self.hdm_decoder_manager.get_capabilities()
        poison_on_decoder_error_capability = capabilities["poison_on_decoder_error_capability"]
        poison_attr = FIELD_ATTR.RW if poison_on_decoder_error_capability == 1 else FIELD_ATTR.RO

        self._fields = [
            BitField(
                "poison_on_decode_error_enable",
                0,
                0,
                poison_attr,
            ),
            BitField("hdm_decoder_enable", 1, 1, FIELD_ATTR.RW),
            BitField("reserved1", 2, 31, FIELD_ATTR.RESERVED),
        ]

        super().__init__(data, parent_name)

    def write_bytes(self, start_offset: int, end_offset: int, value: int):
        hdm_decoder_enable_before = self.hdm_decoder_enable
        super().write_bytes(start_offset, end_offset, value)
        hdm_decoder_enable_after = self.hdm_decoder_enable

        if hdm_decoder_enable_before == 0 and hdm_decoder_enable_after == 1:
            self.hdm_decoder_manager.decoder_enable(True)
        elif hdm_decoder_enable_before == 1 and hdm_decoder_enable_after == 0:
            self.hdm_decoder_manager.decoder_enable(False)


CommitHandler = Callable[[int], bool]


class CxlHdmDecoderControlRegisterOptions(TypedDict):
    handle_commit: CommitHandler
    decoder_index: int
    bi_capable: bool
    uio_capable: bool
    device_type: CXL_DEVICE_TYPE


class CxlHdmDecoderControlRegister(BitMaskedBitStructure):
    interleave_granularity: int
    interleave_ways: int
    lock_on_commit: int
    commit: int
    committed: int
    error_not_committed: int
    target_range_type: int
    bi: int
    uio: int
    upstream_interleave_granularity: int
    upstream_interleave_ways: int
    interleave_set_position: int

    def __init__(
        self,
        data: Optional[ShareableByteArray] = None,
        parent_name: Optional[str] = None,
        options: Optional[CxlHdmDecoderControlRegisterOptions] = None,
    ):
        if not options:
            raise Exception("options is required")

        self.handle_commit = options.get("handle_commit")
        self.decoder_index = options["decoder_index"]
        bi_capable = options["bi_capable"]
        uio_capable = options["uio_capable"]
        device_type = options["device_type"]

        self.parent_name = parent_name

        upstream_interleave_attr = (
            FIELD_ATTR.RWL
            if device_type != CXL_DEVICE_TYPE.MEM_DEVICE and uio_capable
            else FIELD_ATTR.RESERVED
        )

        interleave_set_position_attr = FIELD_ATTR.RWL if uio_capable else FIELD_ATTR.RESERVED

        self._fields = [
            BitField("interleave_granularity", 0, 3, FIELD_ATTR.RWL),
            BitField("interleave_ways", 4, 7, FIELD_ATTR.RWL),
            BitField("lock_on_commit", 8, 8, FIELD_ATTR.RWL),
            BitField("commit", 9, 9, FIELD_ATTR.RWL),
            BitField("committed", 10, 10, FIELD_ATTR.RO),
            BitField("error_not_committed", 11, 11, FIELD_ATTR.RO),
            BitField(
                "target_range_type",
                12,
                12,
                FIELD_ATTR.RWL if bi_capable else FIELD_ATTR.RO,
                1,
            ),
            BitField("bi", 13, 13, FIELD_ATTR.RWL if bi_capable else FIELD_ATTR.RESERVED),
            BitField("uio", 14, 14, FIELD_ATTR.RWL if uio_capable else FIELD_ATTR.RO),
            BitField("reserved1", 15, 15, FIELD_ATTR.RESERVED),
            BitField(
                "upstream_interleave_granularity",
                16,
                19,
                upstream_interleave_attr,
            ),
            BitField("upstream_interleave_ways", 20, 23, upstream_interleave_attr),
            BitField("interleave_set_position", 24, 27, interleave_set_position_attr),
            BitField("reserved2", 28, 31, FIELD_ATTR.RESERVED),
        ]

        super().__init__(data, parent_name)

    def write_bytes(self, start_offset: int, end_offset: int, value: int):
        commit_before = self.commit
        super().write_bytes(start_offset, end_offset, value)
        commit_after = self.commit

        if not self.handle_commit:
            return

        # TODO: Implement lock on commit
        if commit_before == 0 and commit_after == 1:
            if self.handle_commit(self.decoder_index):
                self.commit = 0
                self.committed = 1
                self.error_not_committed = 0
            else:
                self.commit = 0
                self.committed = 0
                self.error_not_committed = 1


class CxlHdmDecoderTargetListLowRegister(BitMaskedBitStructure):
    way0_target: int
    way1_target: int
    way2_target: int
    way3_target: int

    _fields = [
        BitField("way0_target", 0, 7),
        BitField("way1_target", 8, 15),
        BitField("way2_target", 16, 23),
        BitField("way3_target", 24, 31),
    ]


class CxlHdmDecoderTargetListHighRegister(BitMaskedBitStructure):
    way4_target: int
    way5_target: int
    way6_target: int
    way7_target: int

    _fields = [
        BitField("way4_target", 0, 7),
        BitField("way5_target", 8, 15),
        BitField("way6_target", 16, 23),
        BitField("way7_target", 24, 31),
    ]


class CxlHdmDecoderItemOptions(TypedDict):
    hdm_decoder_manager: HdmDecoderManagerBase
    decoder_index: int


class CxlHdmDecoderItem(BitMaskedBitStructure):
    base_low: int
    base_high: int
    size_low: int
    size_high: int
    control: CxlHdmDecoderControlRegister
    dpa_skip_low: int
    dpa_skip_high: int
    target_list_low: CxlHdmDecoderTargetListLowRegister
    target_list_high: CxlHdmDecoderTargetListHighRegister

    def __init__(
        self,
        data: Optional[ShareableByteArray] = None,
        parent_name: Optional[str] = None,
        options: Optional[CxlHdmDecoderItemOptions] = None,
    ):
        if not options:
            raise Exception("options is required")

        hdm_decoder_manager = options["hdm_decoder_manager"]
        decoder_index = options["decoder_index"]
        device_type = hdm_decoder_manager.get_device_type()

        def handle_commit(decoder_index: int):
            info = DecoderInfo()
            base = self.base_low | self.base_high << 32
            size = self.size_low | self.size_high << 32
            info.size = size
            info.base = base
            info.ig = self.control.interleave_granularity
            info.iw = self.control.interleave_ways
            if device_type == CXL_DEVICE_TYPE.MEM_DEVICE:
                dpa_skip = self.dpa_skip_low | self.dpa_skip_high << 32
                info.dpa_skip = dpa_skip
            else:
                targets = [
                    self.target_list_low.way0_target,
                    self.target_list_low.way1_target,
                    self.target_list_low.way2_target,
                    self.target_list_low.way3_target,
                    self.target_list_high.way4_target,
                    self.target_list_high.way5_target,
                    self.target_list_high.way6_target,
                    self.target_list_high.way7_target,
                ]
                info.target_ports = targets

            return hdm_decoder_manager.commit(decoder_index, info)

        control_register_options = CxlHdmDecoderControlRegisterOptions()
        control_register_options["bi_capable"] = hdm_decoder_manager.is_bi_capable()
        control_register_options["uio_capable"] = hdm_decoder_manager.is_uio_capable()
        control_register_options["decoder_index"] = decoder_index
        control_register_options["device_type"] = device_type
        control_register_options["handle_commit"] = handle_commit

        self._fields = [
            ByteField("base_low", 0x00, 0x03, mask=0xF0000000),
            ByteField("base_high", 0x04, 0x07),
            ByteField("size_low", 0x08, 0x0B, mask=0xF0000000),
            ByteField("size_high", 0x0C, 0x0F),
            StructureField(
                "control",
                0x10,
                0x13,
                CxlHdmDecoderControlRegister,
                options=control_register_options,
            ),
        ]

        if device_type == CXL_DEVICE_TYPE.MEM_DEVICE:
            self._fields += [
                ByteField("dpa_skip_low", 0x14, 0x17, mask=0xF0000000),
                ByteField("dpa_skip_high", 0x18, 0x1B),
            ]
        else:
            self._fields += [
                StructureField(
                    "target_list_low",
                    0x14,
                    0x17,
                    CxlHdmDecoderTargetListLowRegister,
                ),
                StructureField(
                    "target_list_high",
                    0x18,
                    0x1B,
                    CxlHdmDecoderTargetListHighRegister,
                ),
            ]

        self._fields += [ByteField("reserved1", 0x1C, 0x1F, attribute=FIELD_ATTR.RO)]

        super().__init__(data, parent_name)


class CxlHdmDecoderCapabilityStructureOptions(TypedDict):
    hdm_decoder_manager: HdmDecoderManagerBase


class CxlHdmDecoderCapabilityStructure(BitMaskedBitStructure):
    decoder0: CxlHdmDecoderItem
    decoder1: CxlHdmDecoderItem

    def __init__(
        self,
        data: Optional[ShareableByteArray] = None,
        parent_name: Optional[str] = None,
        options: Optional[CxlHdmDecoderCapabilityStructureOptions] = None,
    ):
        if not options:
            raise Exception("options is required")

        hdm_decoder_manager = options["hdm_decoder_manager"]
        self._init_global(hdm_decoder_manager)
        self._init_decoders(hdm_decoder_manager)

        super().__init__(data, parent_name)

    def _init_global(self, hdm_decoder_manager: HdmDecoderManagerBase):
        global_control_options = CxlHdmDecoderGlobalControlRegisterOptions(
            hdm_decoder_manager=hdm_decoder_manager
        )
        capability_register_options = CxlHdmDecoderCapabilityRegisterOptions(
            hdm_decoder_manager=hdm_decoder_manager
        )

        self._fields = [
            StructureField(
                "capability",
                0,
                3,
                CxlHdmDecoderCapabilityRegister,
                options=capability_register_options,
            ),
            StructureField(
                "global_control",
                4,
                7,
                CxlHdmDecoderGlobalControlRegister,
                options=global_control_options,
            ),
            ByteField("reserved1", 8, 15, attribute=FIELD_ATTR.RESERVED),
        ]

    def _init_decoders(self, hdm_decoder_manager: HdmDecoderManagerBase):
        decoder_count_reg = hdm_decoder_manager.get_capabilities()["decoder_count"]
        decoder_count = hdm_decoder_manager.get_decoder_count(decoder_count_reg)
        for decoder_index in range(decoder_count):
            control_options = CxlHdmDecoderItemOptions(
                decoder_index=decoder_index, hdm_decoder_manager=hdm_decoder_manager
            )
            self._init_decoder_item(control_options)

    def _init_decoder_item(self, control_options: CxlHdmDecoderItemOptions):
        decoder_index = control_options["decoder_index"]
        offset = 0x20 * decoder_index + 0x10
        self._fields += [
            StructureField(
                f"decoder{decoder_index}",
                offset + 0x00,
                offset + 0x1F,
                CxlHdmDecoderItem,
                options=control_options,
            )
        ]

    @staticmethod
    def get_size_from_options(
        options: Optional[CxlHdmDecoderCapabilityStructureOptions] = None,
    ):
        if not options:
            raise Exception("options is required")

        hdm_decoder_manager = options["hdm_decoder_manager"]
        decoder_count_reg = hdm_decoder_manager.get_capabilities()["decoder_count"]
        decoder_count = hdm_decoder_manager.get_decoder_count(decoder_count_reg)
        size = 0x10 + 0x20 * decoder_count
        return size
