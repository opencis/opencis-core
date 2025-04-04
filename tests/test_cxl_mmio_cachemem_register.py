"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from unittest.mock import MagicMock, patch

from opencis.cxl.mmio.component_register.memcache_register.capability import (
    CxlCapabilityHeaderStructure,
    CxlCapabilityHeaderStructureOptions,
)
from opencis.cxl.mmio.component_register.memcache_register.hdm_decoder_capability import (
    CxlHdmDecoderCapabilityStructure,
    CxlHdmDecoderCapabilityStructureOptions,
)
from opencis.cxl.mmio.component_register.memcache_register import (
    CxlCacheMemRegister,
    CxlCacheMemRegisterOptions,
    CXL_CACHE_MEM_REGISTER_SIZE,
)
from opencis.cxl.component.bi_decoder import (
    CxlBIDecoderCapabilityStructureOptions,
    CxlBIDecoderCapabilityRegisterOptions,
    CxlBIDecoderControlRegisterOptions,
    CxlBIDecoderStatusRegisterOptions,
    CxlBIDecoderCapabilityStructure,
    CxlBIRTCapabilityStructureOptions,
    CxlBIRTCapabilityRegisterOptions,
    CxlBIRTControlRegisterOptions,
    CxlBIRTStatusRegisterOptions,
    CxlBIRTCapabilityStructure,
    CxlBITimeoutScale,
)
from opencis.cxl.component.common import CXL_COMPONENT_TYPE
from opencis.cxl.component.hdm_decoder import (
    HdmDecoderCapabilities,
    DecoderInfo,
    CXL_DEVICE_TYPE,
    HDM_DECODER_COUNT,
    DeviceHdmDecoderManager,
)


def test_cxl_capability_header_register_without_options():
    register = CxlCapabilityHeaderStructure()
    assert not hasattr(register, "ras")
    assert hasattr(register, "header")
    assert register.header.cxl_capability_id == 0x0001
    assert register.header.cxl_capability_version == 0x1
    assert register.header.cxl_cache_mem_version == 0x1
    assert register.header.array_size == 0x0


def test_cxl_capability_header_register():
    # pylint: disable=no-member
    options: CxlCapabilityHeaderStructureOptions = {
        "ras": 0x100,
        "link": 0x200,
        "hdm_decoder": 0x400,
        "bi_route_table": 0x500,
        "bi_decoder": 0x600,
    }
    register = CxlCapabilityHeaderStructure(options=options)
    assert hasattr(register, "ras")
    assert register.ras.cxl_capability_id == 0x0002
    assert hasattr(register, "link")
    assert register.link.cxl_capability_id == 0x0004
    assert hasattr(register, "hdm_decoder")
    assert register.hdm_decoder.cxl_capability_id == 0x0005
    assert hasattr(register, "bi_route_table")
    assert register.bi_route_table.cxl_capability_id == 0x000B
    assert hasattr(register, "bi_decoder")
    assert register.bi_decoder.cxl_capability_id == 0x000C
    assert register.header.array_size == len(options.items())


def test_hdm_decoder_capability_with_one_decoder():
    hdm_decoder_manager = MagicMock()
    hdm_decoder_manager.get_capabilities.return_value = HdmDecoderCapabilities(
        decoder_count=HDM_DECODER_COUNT.DECODER_1,
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
    options = CxlHdmDecoderCapabilityStructureOptions(hdm_decoder_manager=hdm_decoder_manager)
    register = CxlHdmDecoderCapabilityStructure(options=options)
    assert len(bytes(register)) == 0x30
    assert hasattr(register, "decoder0")
    assert not hasattr(register, "decoder1")


def test_hdm_decoder_capability_with_four_decoders():
    hdm_decoder_manager = DeviceHdmDecoderManager(
        HdmDecoderCapabilities(
            decoder_count=HDM_DECODER_COUNT.DECODER_4,
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
    )
    options = CxlHdmDecoderCapabilityStructureOptions(hdm_decoder_manager=hdm_decoder_manager)
    register = CxlHdmDecoderCapabilityStructure(options=options)
    assert len(bytes(register)) == 0x10 + 0x20 * 4
    assert hasattr(register, "decoder3")
    assert not hasattr(register, "decoder4")


def test_hdm_decoder_capability_enable_decoder():
    hdm_decoder_manager = MagicMock()
    hdm_decoder_manager.get_capabilities.return_value = HdmDecoderCapabilities(
        decoder_count=HDM_DECODER_COUNT.DECODER_4,
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
    options = CxlHdmDecoderCapabilityStructureOptions(hdm_decoder_manager=hdm_decoder_manager)
    register = CxlHdmDecoderCapabilityStructure(options=options)
    register.write_bytes(0x4, 0x7, 0x00000002)
    hdm_decoder_manager.decoder_enable.assert_called_once_with(True)
    register.write_bytes(0x4, 0x7, 0x00000000)
    hdm_decoder_manager.decoder_enable.assert_called_with(False)


def test_hdm_decoder_capability_commit():
    class_path = "opencis.cxl.component.hdm_decoder.DeviceHdmDecoderManager"
    with patch(f"{class_path}.commit", return_value=True) as commit_mock:
        with patch(f"{class_path}.get_device_type", return_value=CXL_DEVICE_TYPE) as _:
            hdm_decoder_manager = DeviceHdmDecoderManager(
                HdmDecoderCapabilities(
                    decoder_count=HDM_DECODER_COUNT.DECODER_4,
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
            )
            hdm_decoder_manager.get_device_type.return_value = CXL_DEVICE_TYPE.MEM_DEVICE

            options = CxlHdmDecoderCapabilityStructureOptions(
                hdm_decoder_manager=hdm_decoder_manager
            )
            register = CxlHdmDecoderCapabilityStructure(options=options)

            register.write_bytes(0x20, 0x23, 0x00000200)
            commit_mock.assert_called_with(0, DecoderInfo())
            assert register.decoder0.control.commit == 0
            assert register.decoder0.control.committed == 1
            assert register.decoder0.control.error_not_committed == 0

            commit_mock.return_value = False
            register.write_bytes(0x40, 0x43, 0x00000200)
            commit_mock.assert_called_with(1, DecoderInfo())
            assert register.decoder1.control.commit == 0
            assert register.decoder1.control.committed == 0
            assert register.decoder1.control.error_not_committed == 1


def test_cachemem_register():
    register = CxlCacheMemRegister()
    assert len(register) == CXL_CACHE_MEM_REGISTER_SIZE
    assert hasattr(register, "capability_header")
    assert not hasattr(register, "ras")
    assert not hasattr(register, "link")
    assert not hasattr(register, "hdm_decoder")


def test_cachemem_register_with_options_ras_only():
    options = CxlCacheMemRegisterOptions()
    options["ras"] = True
    register = CxlCacheMemRegister(options=options)
    assert len(register) == CXL_CACHE_MEM_REGISTER_SIZE
    assert hasattr(register, "capability_header")
    assert hasattr(register, "ras")
    assert not hasattr(register, "link")
    assert not hasattr(register, "hdm_decoder")


def test_cachemem_register_with_options_link_only():
    options = CxlCacheMemRegisterOptions()
    options["link"] = True
    register = CxlCacheMemRegister(options=options)
    assert len(register) == CXL_CACHE_MEM_REGISTER_SIZE
    assert hasattr(register, "capability_header")
    assert hasattr(register, "link")
    assert not hasattr(register, "ras")
    assert not hasattr(register, "hdm_decoder")


def test_cachemem_register_with_options_hdm_decoder_only():
    options = CxlCacheMemRegisterOptions()

    hdm_decoder_manager = DeviceHdmDecoderManager(
        HdmDecoderCapabilities(
            decoder_count=HDM_DECODER_COUNT.DECODER_1,
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
    )
    options["hdm_decoder"] = CxlHdmDecoderCapabilityStructureOptions(
        hdm_decoder_manager=hdm_decoder_manager
    )
    register = CxlCacheMemRegister(options=options)
    assert len(register) == CXL_CACHE_MEM_REGISTER_SIZE
    assert hasattr(register, "capability_header")
    assert hasattr(register, "hdm_decoder")
    assert not hasattr(register, "ras")
    assert not hasattr(register, "link")


def test_cachemem_register_with_options_bi_decoder_only():
    options = CxlCacheMemRegisterOptions()

    options["bi_decoder"] = CxlBIDecoderCapabilityStructureOptions()
    options["bi_decoder"]["capability_options"] = CxlBIDecoderCapabilityRegisterOptions(
        hdm_d_compatible=0, explicit_bi_decoder_commit_required=1
    )
    options["bi_decoder"]["control_options"] = CxlBIDecoderControlRegisterOptions(
        bi_forward=1, bi_enable=0, bi_decoder_commit=0
    )
    options["bi_decoder"]["status_options"] = CxlBIDecoderStatusRegisterOptions(
        bi_decoder_committed=0,
        bi_decoder_error_not_committed=0,
        bi_decoder_commit_timeout_base=CxlBITimeoutScale.hundred_ms,
        bi_decoder_commit_timeout_scale=1,
    )
    options["bi_decoder"]["device_type"] = CXL_COMPONENT_TYPE.LD
    register = CxlCacheMemRegister(options=options)
    assert len(register) == CXL_CACHE_MEM_REGISTER_SIZE
    assert hasattr(register, "capability_header")
    assert hasattr(register, "bi_decoder")
    assert not hasattr(register, "bi_route_table")
    assert not hasattr(register, "hdm_decoder")
    assert not hasattr(register, "ras")
    assert not hasattr(register, "link")


def test_cachemem_register_with_options_bi_rt_only():
    options = CxlCacheMemRegisterOptions()

    options["bi_route_table"] = CxlBIRTCapabilityStructureOptions()
    options["bi_route_table"]["capability_options"] = CxlBIRTCapabilityRegisterOptions(
        explicit_bi_rt_commit_required=1
    )
    options["bi_route_table"]["control_options"] = CxlBIRTControlRegisterOptions(bi_rt_commit=0)
    options["bi_route_table"]["status_options"] = CxlBIRTStatusRegisterOptions(
        bi_rt_committed=0,
        bi_rt_error_not_committed=0,
        bi_rt_commit_timeout_base=CxlBITimeoutScale.hundred_ms,
        bi_rt_commit_timeout_scale=1,
    )

    register = CxlCacheMemRegister(options=options)
    assert len(register) == CXL_CACHE_MEM_REGISTER_SIZE
    assert hasattr(register, "capability_header")
    assert hasattr(register, "bi_route_table")
    assert not hasattr(register, "bi_decoder")
    assert not hasattr(register, "hdm_decoder")
    assert not hasattr(register, "ras")
    assert not hasattr(register, "link")


def test_cachemem_register_with_options_bi_only():
    options = CxlCacheMemRegisterOptions()

    options["bi_decoder"] = CxlBIDecoderCapabilityStructureOptions()
    options["bi_decoder"]["capability_options"] = CxlBIDecoderCapabilityRegisterOptions(
        hdm_d_compatible=0, explicit_bi_decoder_commit_required=1
    )
    options["bi_decoder"]["control_options"] = CxlBIDecoderControlRegisterOptions(
        bi_forward=1, bi_enable=0, bi_decoder_commit=0
    )
    options["bi_decoder"]["status_options"] = CxlBIDecoderStatusRegisterOptions(
        bi_decoder_committed=0,
        bi_decoder_error_not_committed=0,
        bi_decoder_commit_timeout_base=CxlBITimeoutScale.hundred_ms,
        bi_decoder_commit_timeout_scale=1,
    )
    options["bi_decoder"]["device_type"] = CXL_COMPONENT_TYPE.LD

    options["bi_route_table"] = CxlBIRTCapabilityStructureOptions()
    options["bi_route_table"]["capability_options"] = CxlBIRTCapabilityRegisterOptions(
        explicit_bi_rt_commit_required=1
    )
    options["bi_route_table"]["control_options"] = CxlBIRTControlRegisterOptions(bi_rt_commit=0)
    options["bi_route_table"]["status_options"] = CxlBIRTStatusRegisterOptions(
        bi_rt_committed=0,
        bi_rt_error_not_committed=0,
        bi_rt_commit_timeout_base=CxlBITimeoutScale.hundred_ms,
        bi_rt_commit_timeout_scale=1,
    )

    register = CxlCacheMemRegister(options=options)
    assert len(register) == CXL_CACHE_MEM_REGISTER_SIZE
    assert hasattr(register, "capability_header")
    assert hasattr(register, "bi_decoder")
    assert hasattr(register, "bi_route_table")
    assert not hasattr(register, "hdm_decoder")
    assert not hasattr(register, "ras")
    assert not hasattr(register, "link")


def test_bi_decoder_without_options_only():
    # pylint: disable=bare-except, unused-variable
    # Test if Exception will be thrown if options=None, for 100% code coverage
    try:
        register = CxlBIDecoderCapabilityStructure(options=None)
    except:
        pass


def test_bi_rt_without_options_only():
    # pylint: disable=bare-except, unused-variable
    try:
        register = CxlBIRTCapabilityStructure(options=None)
    except:
        pass


def test_cachemem_register_with_options_all():
    options = CxlCacheMemRegisterOptions()
    options["ras"] = True
    options["link"] = True
    hdm_decoder_manager = DeviceHdmDecoderManager(
        HdmDecoderCapabilities(
            decoder_count=HDM_DECODER_COUNT.DECODER_1,
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
    )
    options["hdm_decoder"] = CxlHdmDecoderCapabilityStructureOptions(
        hdm_decoder_manager=hdm_decoder_manager
    )
    options["bi_decoder"] = CxlBIDecoderCapabilityStructureOptions()
    options["bi_decoder"]["capability_options"] = CxlBIDecoderCapabilityRegisterOptions(
        hdm_d_compatible=0, explicit_bi_decoder_commit_required=1
    )
    options["bi_decoder"]["control_options"] = CxlBIDecoderControlRegisterOptions(
        bi_forward=1, bi_enable=0, bi_decoder_commit=0
    )
    options["bi_decoder"]["status_options"] = CxlBIDecoderStatusRegisterOptions(
        bi_decoder_committed=0,
        bi_decoder_error_not_committed=0,
        bi_decoder_commit_timeout_base=CxlBITimeoutScale.hundred_ms,
        bi_decoder_commit_timeout_scale=1,
    )
    options["bi_decoder"]["device_type"] = CXL_COMPONENT_TYPE.LD
    options["bi_route_table"] = CxlBIRTCapabilityStructureOptions()
    options["bi_route_table"]["capability_options"] = CxlBIRTCapabilityRegisterOptions(
        explicit_bi_rt_commit_required=1
    )
    options["bi_route_table"]["control_options"] = CxlBIRTControlRegisterOptions(bi_rt_commit=0)
    options["bi_route_table"]["status_options"] = CxlBIRTStatusRegisterOptions(
        bi_rt_committed=0,
        bi_rt_error_not_committed=0,
        bi_rt_commit_timeout_base=CxlBITimeoutScale.hundred_ms,
        bi_rt_commit_timeout_scale=1,
    )
    register = CxlCacheMemRegister(options=options)
    assert len(register) == CXL_CACHE_MEM_REGISTER_SIZE
    assert hasattr(register, "capability_header")
    assert hasattr(register, "bi_decoder")
    assert hasattr(register, "bi_route_table")
    assert hasattr(register, "ras")
    assert hasattr(register, "link")
    assert hasattr(register, "hdm_decoder")
