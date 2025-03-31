"""
Copyright (c) 2024, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from abc import abstractmethod
from dataclasses import dataclass
from enum import Enum, IntEnum, auto
from typing import Optional, List

from opencis.cxl.config_space.doe.cdat import CDAT_ENTRY
from opencis.cxl.features.mailbox import CxlMailbox
from opencis.cxl.features.event_manager import EventManager
from opencis.cxl.features.log_manager import LogManager
from opencis.cxl.component.bi_decoder import (
    CxlBIDecoderCapabilityStructureOptions,
    CxlBIRTCapabilityStructureOptions,
)
from opencis.cxl.component.common import CXL_COMPONENT_TYPE
from opencis.cxl.component.hdm_decoder import HdmDecoderManagerBase
from opencis.util.component import LabeledComponent
from opencis.cxl.component.cache_route_table import (
    CacheRouteTableCapabilityStructureOptions,
)
from opencis.cxl.component.cache_id_decoder_capability import (
    CxlCacheIdDecoderCapabilityStructureOptions,
)


class PORT_TYPE(Enum):
    USP = auto()
    DSP = auto()


@dataclass
class PortConfig:
    type: PORT_TYPE


class CxlComponent(LabeledComponent):
    def get_primary_mailbox(self) -> Optional[CxlMailbox]:
        return None

    def get_secondary_mailbox(self) -> Optional[CxlMailbox]:
        return None

    def get_hdm_decoder_manager(self) -> Optional[HdmDecoderManagerBase]:
        return None

    def get_bi_decoder_options(self) -> Optional[CxlBIDecoderCapabilityStructureOptions]:
        return None

    def get_bi_rt_options(self) -> Optional[CxlBIRTCapabilityStructureOptions]:
        return None

    def get_cache_route_table_options(self) -> Optional[CacheRouteTableCapabilityStructureOptions]:
        return None

    def get_cache_decoder_options(self) -> Optional[CxlCacheIdDecoderCapabilityStructureOptions]:
        return None

    def get_cdat_entries(self) -> List[CDAT_ENTRY]:
        return []

    @abstractmethod
    def get_component_type(self) -> CXL_COMPONENT_TYPE:
        """This must be implemented in the child class"""


class CXL_DEVICE_CAPABILITY_TYPE(IntEnum):
    INFER_PCI_CLASS_CODE = 0
    MEMORY_DEVICE = 1
    SWITCH_MAILBOX_CCI = 2


class CxlDeviceComponent(CxlComponent):
    @abstractmethod
    def get_capability_type(self) -> CXL_DEVICE_CAPABILITY_TYPE:
        """This must be implemented in the child class"""

    @abstractmethod
    def get_event_manager(self) -> EventManager:
        """This must be implemented in the child class"""

    @abstractmethod
    def get_log_manager(self) -> LogManager:
        """This must be implemented in the child class"""
