from dataclasses import dataclass, field
from typing import List, Optional, cast
from opencis.util.logger import logger

from opencis.cxl.component.hdm_decoder import (
    HdmDecoderBase,
    HdmDecoderManagerBase,
    HdmDecoderCapabilities,
    DecoderInfo,
    INTERLEAVE_GRANULARITY,
    INTERLEAVE_WAYS,
)
from opencis.cxl.device.cxl_type3_device import CXL_DEVICE_TYPE


@dataclass
class PbrHdmDecoder(HdmDecoderBase):
    target_dpids: List[int] = field(default_factory=list)

    def get_dpid(self, hpa: int) -> int:
        decoded_ig = 1 << (self.ig + 8)
        decoded_iw = 1 << self.iw
        target_index = (hpa // decoded_ig) % decoded_iw
        return self.target_dpids[target_index]


class PbrHdmDecoderManager(HdmDecoderManagerBase):
    def __init__(self, capabilities: HdmDecoderCapabilities, label: Optional[str] = None):
        super().__init__(capabilities, label)
        decoder_count = self.get_decoder_count(self._capabilities["decoder_count"])
        self._decoders: List[PbrHdmDecoder] = []
        for decoder_index in range(decoder_count):
            self._decoders.append(PbrHdmDecoder(index=decoder_index, size=0, base=0))

    def get_device_type(self):
        return CXL_DEVICE_TYPE.SWITCH  # Or HOST_BRIDGE depending on edge port role

    def is_bi_capable(self) -> bool:
        return self._capabilities["bi_capable"]

    def decoder_enable(self, enabled: bool):
        pass

    def commit(self, index: int, info: DecoderInfo) -> bool:
        if index > len(self._decoders):
            logger.warning(self._create_message(f"Decoder index ({index}) is out of bound"))
            return False

        decoder = cast(PbrHdmDecoder, self._decoders[index])
        decoder.base = info.base
        decoder.size = info.size
        decoder.ig = INTERLEAVE_GRANULARITY(info.ig)
        decoder.iw = INTERLEAVE_WAYS(info.iw)
        # We reuse target_ports field from DecoderInfo to pass DPIDs for simplicity
        decoder.target_dpids = info.target_ports

        decoder_commit_info = (
            f"[Decoder Commit] index: {index}, base: 0x{decoder.base:x}, size: 0x{decoder.size:x}, "
            + f"ig: {decoder.ig.name}, iw: {decoder.iw.name}, "
            + f"target dpids: {str(decoder.target_dpids)}"
        )
        logger.debug(self._create_message(decoder_commit_info))
        return True

    def get_dpid(self, hpa: int) -> Optional[int]:
        decoder = self.get_decoder_from_hpa(hpa)
        if not decoder:
            return None
        pbr_decoder = cast(PbrHdmDecoder, decoder)
        return pbr_decoder.get_dpid(hpa)
