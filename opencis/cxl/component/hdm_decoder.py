"""
Copyright (c) 2024, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from abc import abstractmethod
from dataclasses import dataclass, field
from enum import IntEnum, Enum, auto
from typing import TypedDict, List, Optional, cast

from opencis.util.component import LabeledComponent
from opencis.util.logger import logger


class HDM_DECODER_COUNT(IntEnum):
    DECODER_1 = 0x0
    DECODER_2 = 0x1
    DECODER_4 = 0x2
    DECODER_6 = 0x3
    DECODER_8 = 0x4
    DECODER_10 = 0x5
    DECODER_12 = 0x6
    DECODER_14 = 0x7
    DECODER_16 = 0x8
    DECODER_20 = 0x9
    DECODER_24 = 0xA
    DECODER_28 = 0xB
    DECODER_32 = 0xC


class INTERLEAVE_GRANULARITY(IntEnum):
    SIZE_256B = 0x0
    SIZE_512B = 0x1
    SIZE_1KB = 0x2
    SIZE_2KB = 0x3
    SIZE_4KB = 0x4
    SIZE_8KB = 0x5
    SIZE_16KB = 0x6


class INTERLEAVE_WAYS(IntEnum):
    WAY_1 = 0x0
    WAY_2 = 0x1
    WAY_4 = 0x2
    WAY_8 = 0x3
    WAY_16 = 0x4
    WAY_3 = 0x8
    WAY_6 = 0x9
    WAY_12 = 0xA


class IW_TO_WAYS:
    @staticmethod
    def calc(value: INTERLEAVE_WAYS) -> int:
        return int((value.name).split("_")[-1])


class HDM_COUNT_TO_NUM:
    @staticmethod
    def calc(value: HDM_DECODER_COUNT) -> int:
        return int((value.name).split("_")[-1])


class HdmDecoderCapabilities(TypedDict):
    # pylint: disable=duplicate-code
    decoder_count: HDM_DECODER_COUNT
    target_count: int
    a11to8_interleave_capable: int
    a14to12_interleave_capable: int
    poison_on_decoder_error_capability: int
    three_six_twelve_way_interleave_capable: int
    sixteen_way_interleave_capable: int
    uio_capable: int
    uio_capable_decoder_count: int
    mem_data_nxm_capable: int
    bi_capable: bool


@dataclass
class HdmDecoderBase:
    index: int = 0
    size: int = 0
    base: int = 0
    ig: INTERLEAVE_GRANULARITY = INTERLEAVE_GRANULARITY.SIZE_256B  # interleave granularity
    iw: INTERLEAVE_WAYS = INTERLEAVE_WAYS.WAY_1  # interleave ways

    def is_hpa_in_range(self, hpa: int) -> bool:
        return self.base <= hpa < (self.base + self.size)


@dataclass
class DeviceHdmDecoder(HdmDecoderBase):
    dpa_base: int = 0
    dpa_skip: int = 0

    @staticmethod
    def get_bit_range(number: int, start_bit: int, end_bit: int) -> int:
        mask = (1 << (end_bit - start_bit + 1)) - 1
        shifted_number = number >> start_bit
        selected_bits = shifted_number & mask
        return selected_bits

    def get_dpa(self, hpa: int) -> int:
        hpa_offset = hpa - self.base
        dpa_offset_low = self.get_bit_range(hpa_offset, 0, self.ig + 7)
        if self.iw < 8:
            dpa_offset_high = self.get_bit_range(hpa_offset, self.ig + 8 + self.iw, 51)
        else:
            dpa_offset_high = self.get_bit_range(hpa_offset, self.ig + self.iw, 51) // 3
        dpa_offset = dpa_offset_low | (dpa_offset_high << (self.ig + 8))
        dpa = dpa_offset + self.dpa_base
        return dpa

    def get_hpa(self, dpa: int) -> int:
        return dpa + self.base


@dataclass
class SwitchHdmDecoder(HdmDecoderBase):
    target_ports: List[int] = field(default_factory=list)

    def get_target(self, hpa: int) -> int:
        decoded_ig = 1 << (self.ig + 8)
        decoded_iw = 1 << self.iw
        target_index = (hpa // decoded_ig) % decoded_iw
        return self.target_ports[target_index]


@dataclass
class DecoderInfo:
    size: int = 0
    base: int = 0
    dpa_skip: int = 0
    ig: INTERLEAVE_GRANULARITY = INTERLEAVE_GRANULARITY.SIZE_256B
    iw: INTERLEAVE_WAYS = INTERLEAVE_WAYS.WAY_1
    target_ports: List[int] = field(default_factory=list)


class CXL_DEVICE_TYPE(Enum):
    MEM_DEVICE = auto()
    SWITCH = auto()
    HOST_BRIDGE = auto()


class HdmDecoderManagerBase(LabeledComponent):
    def __init__(self, capabilities: HdmDecoderCapabilities, label: Optional[str] = None):
        super().__init__(label)
        self._capabilities = capabilities
        self._decoders: List[HdmDecoderBase] = []

    @abstractmethod
    def get_device_type(self) -> CXL_DEVICE_TYPE:
        """This must be implemented in the child class"""

    @abstractmethod
    def is_bi_capable(self) -> bool:
        """This must be implemented in the child class"""

    @abstractmethod
    def commit(self, index: int, info: DecoderInfo) -> bool:
        """This must be implemented in the child class"""

    @abstractmethod
    def decoder_enable(self, enabled: bool):
        """This must be implemented in the child class"""

    def is_uio_capable(self):
        return self._capabilities["uio_capable"] == 1

    def get_capabilities(self) -> HdmDecoderCapabilities:
        return self._capabilities

    def get_decoder_from_hpa(self, hpa: int) -> Optional[HdmDecoderBase]:
        for decoder in self._decoders:
            logger.debug(
                f"decoder.index:{decoder.index}, decoder.base:{decoder.base:x}"
                f"decoder.size:{decoder.size:x}, decoder.ig/iw:{decoder.ig:x}/{decoder.iw:x}"
            )
            if decoder.is_hpa_in_range(hpa):
                return decoder
        return None

    def is_hpa_in_range(self, hpa: int) -> bool:
        return self.get_decoder_from_hpa(hpa) is not None

    def get_decoder_for_dpa(self) -> Optional[HdmDecoderBase]:
        for decoder in self._decoders:
            if decoder is not None:
                return decoder
        return None

    @staticmethod
    def get_decoder_count(decode_register_value: int):
        if decode_register_value == 0:
            return 1
        if 1 <= decode_register_value <= 8:
            return decode_register_value * 2
        if 9 <= decode_register_value <= 0x0C:
            return (decode_register_value - 9) * 4 + 20
        raise Exception(f"Undefied value: {decode_register_value}")


class DeviceHdmDecoderManager(HdmDecoderManagerBase):
    def __init__(self, capabilities: HdmDecoderCapabilities, label: Optional[str] = None):
        super().__init__(capabilities, label)
        decoder_count = self.get_decoder_count(self._capabilities["decoder_count"])
        for decoder_index in range(decoder_count):
            self._decoders.append(DeviceHdmDecoder(index=decoder_index, size=0, base=0))

    def get_device_type(self):
        return CXL_DEVICE_TYPE.MEM_DEVICE

    def is_bi_capable(self) -> bool:
        return self._capabilities["bi_capable"]

    def decoder_enable(self, enabled: bool):
        pass

    def poison_enable(self, enabled: bool):
        pass

    def commit(self, index: int, info: DecoderInfo) -> bool:
        # TODO: implement index >= 1
        decoder = cast(DeviceHdmDecoder, self._decoders[index])
        decoder.dpa_base = 0
        decoder.dpa_skip = info.dpa_skip
        decoder.base = info.base
        decoder.size = info.size
        decoder.ig = INTERLEAVE_GRANULARITY(info.ig)
        decoder.iw = INTERLEAVE_WAYS(info.iw)

        decoder_commit_info = (
            f"[Decoder Commit] index: {index}, base: 0x{decoder.base:x}, size: 0x{decoder.size:x}, "
            + f"ig: {decoder.ig.name}, iw: {decoder.iw.name}, dpa skip: {str(decoder.dpa_skip)}"
        )
        logger.debug(self._create_message(decoder_commit_info))

        return True

    def get_dpa(self, hpa: int) -> Optional[int]:
        decoder = self.get_decoder_from_hpa(hpa)
        # print(decoder)
        # print("")
        if not decoder:
            return None
        device_decoder = cast(DeviceHdmDecoder, decoder)
        return device_decoder.get_dpa(hpa)

    def get_hpa(self, dpa: int) -> Optional[int]:
        decoder = self.get_decoder_for_dpa()
        if not decoder:
            return None
        device_decoder = cast(DeviceHdmDecoder, decoder)
        if device_decoder.iw != INTERLEAVE_WAYS.WAY_1:
            return None
        return device_decoder.get_hpa(dpa)


class SwitchHdmDecoderManager(HdmDecoderManagerBase):
    def __init__(self, capabilities: HdmDecoderCapabilities, label: Optional[str] = None):
        super().__init__(capabilities, label)
        decoder_count = self.get_decoder_count(self._capabilities["decoder_count"])
        self._decoders: List[SwitchHdmDecoder] = []
        for decoder_index in range(decoder_count):
            self._decoders.append(SwitchHdmDecoder(index=decoder_index, size=0, base=0))

    def get_device_type(self):
        return CXL_DEVICE_TYPE.SWITCH

    def is_bi_capable(self) -> bool:
        return self._capabilities["bi_capable"]

    def decoder_enable(self, enabled: bool):
        pass

    def poison_enable(self, enabled: bool):
        pass

    def commit(self, index: int, info: DecoderInfo) -> bool:
        # TODO: implement index >= 1
        if index > len(self._decoders):
            logger.warning(f"Decoder index ({index}) is out of bound")
            return False

        decoder = cast(SwitchHdmDecoder, self._decoders[index])
        decoder.base = info.base
        decoder.size = info.size
        decoder.ig = INTERLEAVE_GRANULARITY(info.ig)
        decoder.iw = INTERLEAVE_WAYS(info.iw)
        decoder.target_ports = info.target_ports

        decoder_commit_info = (
            f"[Decoder Commit] index: {index}, base: 0x{decoder.base:x}, size: 0x{decoder.size:x}, "
            + f"ig: {decoder.ig.name}, iw: {decoder.iw.name}, "
            + f"target ports: {str(decoder.target_ports)}"
        )
        logger.debug(self._create_message(decoder_commit_info))
        return True

    def get_target(self, hpa: int) -> Optional[int]:
        decoder = self.get_decoder_from_hpa(hpa)
        if not decoder:
            return None
        switch_decoder = cast(SwitchHdmDecoder, decoder)
        return switch_decoder.get_target(hpa)
