"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from typing import Optional

from opencis.cxl.component.cxl_component import CxlComponent
from opencis.cxl.component.common import CXL_COMPONENT_TYPE
from opencis.cxl.component.bi_decoder import (
    CxlBIDecoderCapabilityStructureOptions,
    CxlBIDecoderCapabilityRegisterOptions,
    CxlBIDecoderControlRegisterOptions,
    CxlBIDecoderStatusRegisterOptions,
    CxlBIRTCapabilityStructureOptions,
    CxlBIRTCapabilityRegisterOptions,
    CxlBIRTControlRegisterOptions,
    CxlBIRTStatusRegisterOptions,
    CxlBITimeoutScale,
)
from opencis.cxl.component.hdm_decoder import (
    HdmDecoderManagerBase,
    SwitchHdmDecoderManager,
    HdmDecoderCapabilities,
    HDM_DECODER_COUNT,
)
from opencis.cxl.component.virtual_switch.vppb_routing_info import VppbRoutingInfo
from opencis.cxl.component.cache_route_table import (
    CacheIdRTCommitTimeout,
    CacheIdTargetNOptions,
    CacheRouteTableCapabilityRegisterOptions,
    CacheRouteTableCapabilityStructureOptions,
    CacheRouteTableControlRegisterOptions,
    CacheRouteTableStatusRegisterOptions,
)
from opencis.cxl.component.cache_id_decoder_capability import (
    CxlCacheIdDecoderCapabilityRegisterOptions,
    CxlCacheIdDecoderCapabilityStructureOptions,
    CxlCacheIdDecoderControlOptions,
    CxlCacheIdDecoderStatusOptions,
)


class CxlUpstreamPortComponent(CxlComponent):
    def __init__(
        self,
        decoder_count: HDM_DECODER_COUNT = HDM_DECODER_COUNT.DECODER_1,
        label: Optional[str] = None,
    ):
        # pylint: disable=duplicate-code
        # CE-94
        super().__init__(label)
        hdm_decoder_capabilities = HdmDecoderCapabilities(
            decoder_count=decoder_count,
            target_count=8,
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
        self._hdm_decoder_manager = SwitchHdmDecoderManager(hdm_decoder_capabilities, label)
        rt_register_opts = CacheRouteTableCapabilityRegisterOptions(
            cache_id_target_count=0,
            hdmd_type2_device_max_count=8,
            explicit_cache_id_rt_cmt_required=0,
        )
        rt_ctl_opts = CacheRouteTableControlRegisterOptions(cache_id_rt_cmt=0)
        rt_status_opts = CacheRouteTableStatusRegisterOptions(
            cache_id_rt_cmtd=0,
            cache_id_rt_err_not_cmtd=0,
            cache_id_rt_cmt_timeout_base=0,
            cache_id_rt_cmt_timeout_scale=CacheIdRTCommitTimeout._1_mS,
        )
        self.cache_route_table_capabilities = CacheRouteTableCapabilityStructureOptions(
            register_options=rt_register_opts,
            control_options=rt_ctl_opts,
            status_options=rt_status_opts,
        )
        self._routing_table = None

    def get_component_type(self) -> CXL_COMPONENT_TYPE:
        return CXL_COMPONENT_TYPE.USP

    def get_hdm_decoder_manager(self) -> Optional[HdmDecoderManagerBase]:
        return self._hdm_decoder_manager

    def get_bi_rt_options(self) -> Optional[CxlBIRTCapabilityStructureOptions]:
        options = CxlBIRTCapabilityStructureOptions()
        options["capability_options"] = CxlBIRTCapabilityRegisterOptions(
            explicit_bi_rt_commit_required=1
        )
        options["control_options"] = CxlBIRTControlRegisterOptions(bi_rt_commit=0)
        options["status_options"] = CxlBIRTStatusRegisterOptions(
            bi_rt_committed=0,
            bi_rt_error_not_committed=0,
            bi_rt_commit_timeout_base=CxlBITimeoutScale.hundred_ms,
            bi_rt_commit_timeout_scale=1,
        )
        return options

    def get_cache_route_table_options(self) -> Optional[CacheRouteTableCapabilityStructureOptions]:
        return self.cache_route_table_capabilities

    def add_cache_route_target(self, physical_port_number: int):
        no_targs = self.cache_route_table_capabilities["register_options"]["cache_id_target_count"]
        new_targ_options = CacheIdTargetNOptions(
            valid=1,
            port_number=physical_port_number,
        )
        targ_name = f"target{no_targs}_options"
        self.cache_route_table_capabilities[targ_name] = new_targ_options
        self.cache_route_table_capabilities["register_options"]["cache_id_target_count"] = (
            no_targs + 1
        )

    def set_routing_table(self, vppb_routing_info: VppbRoutingInfo):
        self._routing_table = vppb_routing_info.routing_table
        self._routing_table.set_hdm_decoder(self._hdm_decoder_manager)


class CxlDownstreamPortComponent(CxlComponent):
    def __init__(
        self,
        label: Optional[str] = None,
        cache_id_decoder_options: Optional[CxlCacheIdDecoderCapabilityStructureOptions] = None,
    ):
        if cache_id_decoder_options:
            self.cache_id_decoder_options = cache_id_decoder_options
        else:
            # assign a sensible default
            register_options = CxlCacheIdDecoderCapabilityRegisterOptions(
                explicit_cache_id_decoder_cmt_required=0, rsvd=0
            )
            control_options = CxlCacheIdDecoderControlOptions(
                forward_cache_id=1,
                assign_cache_id=0,
                hdmd_t2_device_present=0,
                cache_id_decoder_cmt=0,
                rsvd=0,
                hdmd_t2_device_cache_id=0,
                rsvd2=0,
                local_cache_id=0,
                rsvd3=0,
            )
            status_options = CxlCacheIdDecoderStatusOptions(
                cache_id_decoder_cmtd=0,
                cache_id_decoder_err_not_cmtd=0,
                rsvd=0,
                cache_id_decoder_cmt_timeout_scale=0,
                cache_id_decoder_cmt_timeout_base=0,
                rsvd2=0,
            )
            self.cache_id_decoder_options = CxlCacheIdDecoderCapabilityStructureOptions(
                register_options=register_options,
                control_options=control_options,
                status_options=status_options,
            )
        super().__init__()

    def get_bi_decoder_options(self) -> Optional[CxlBIDecoderCapabilityStructureOptions]:
        options = CxlBIDecoderCapabilityStructureOptions()
        options["capability_options"] = CxlBIDecoderCapabilityRegisterOptions(
            explicit_bi_decoder_commit_required=1
        )
        options["control_options"] = CxlBIDecoderControlRegisterOptions(
            bi_forward=0,
            bi_enable=1,
            bi_decoder_commit=0,
        )
        options["status_options"] = CxlBIDecoderStatusRegisterOptions(
            bi_decoder_committed=0,
            bi_decoder_error_not_committed=0,
            bi_decoder_commit_timeout_base=CxlBITimeoutScale.hundred_ms,
            bi_decoder_commit_timeout_scale=1,
        )
        options["device_type"] = self.get_component_type()
        return options

    def get_cache_decoder_options(self) -> Optional[CxlCacheIdDecoderCapabilityStructureOptions]:
        return self.cache_id_decoder_options

    def get_component_type(self) -> CXL_COMPONENT_TYPE:
        return CXL_COMPONENT_TYPE.DSP
