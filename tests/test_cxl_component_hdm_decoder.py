"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from opencis.cxl.component.hdm_decoder import (
    DeviceHdmDecoderManager,
    HdmDecoderCapabilities,
    CXL_DEVICE_TYPE,
    DecoderInfo,
)


def test_device_hdm_decoder_manager():
    # pylint: disable=duplicate-code
    capabilities = HdmDecoderCapabilities(
        decoder_count=1,
        target_count=0,
        a11to8_interleave_capable=0,
        a14to12_interleave_capable=0,
        poison_on_decoder_error_capability=0,
        three_six_twelve_way_interleave_capable=0,
        sixteen_way_interleave_capable=0,
        uio_capable=0,
        uio_capable_decoder_count=0,
        mem_data_nxm_capable=0,
        bi_capable=True,
    )
    decoder = DeviceHdmDecoderManager(capabilities)
    assert decoder.get_device_type() == CXL_DEVICE_TYPE.MEM_DEVICE
    assert decoder.is_bi_capable() is True
    assert decoder.get_capabilities() == capabilities
    assert decoder.decoder_enable(True) is None
    assert decoder.poison_enable(True) is None
    assert decoder.is_uio_capable() is False

    decoder_info = DecoderInfo(size=0x1000, base=0x2000)
    decoder_index = 0
    assert decoder.commit(decoder_index, decoder_info) is True
    assert decoder.is_hpa_in_range(0x2000 - 1) is False
    assert decoder.is_hpa_in_range(0x2000) is True
    assert decoder.is_hpa_in_range(0x3000 - 1) is True
    assert decoder.is_hpa_in_range(0x3000) is False
    assert decoder.get_dpa(0x3000) is None

    decoder_info = DecoderInfo(size=0x1000, base=0x2000, iw=1)
    decoder_index = 0
    assert decoder.commit(decoder_index, decoder_info) is True
    assert decoder.get_dpa(0x2012) == 0x12
    assert decoder.get_dpa(0x2212) == 0x112

    decoder_info = DecoderInfo(size=0x1000, base=0x2000, iw=8)
    decoder_index = 0
    assert decoder.commit(decoder_index, decoder_info) is True
    assert decoder.get_dpa(0x2023) == 0x023
    assert decoder.get_dpa(0x2323) == 0x123

    decoder_info = DecoderInfo(size=0x1000, base=0x2000, iw=1, ig=1)
    decoder_index = 0
    assert decoder.commit(decoder_index, decoder_info) is True
    assert decoder.get_dpa(0x2012) == 0x12
    assert decoder.get_dpa(0x2412) == 0x212
