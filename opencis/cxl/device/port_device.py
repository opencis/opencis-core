"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from abc import abstractmethod
from asyncio import create_task, gather
from enum import IntEnum

from opencis.cxl.component.cxl_cache_manager import CxlCacheManager
from opencis.cxl.component.virtual_switch.vppb_routing_info import VppbRoutingInfo
from opencis.util.logger import logger
from opencis.util.unaligned_bit_structure import (
    UnalignedBitStructure,
    BitField,
    FIELD_ATTR,
)
from opencis.cxl.component.cxl_connection import CxlConnection
from opencis.cxl.component.common import CXL_COMPONENT_TYPE
from opencis.util.component import RunnableComponent
from opencis.cxl.component.cxl_io_manager import CxlIoManager
from opencis.cxl.component.cxl_mem_manager import CxlMemManager


class CURRENT_PORT_CONFIGURATION_STATE(IntEnum):
    DISABLED = 0x00
    BIND_IN_PROGRESS = 0x01
    UNBIND_IN_PROGRESS = 0x02
    DSP = 0x03
    USP = 0x04
    RESERVED = 0x05
    INVALID_PORT_ID = 0x0F


class CONNECTED_DEVICE_MODE(IntEnum):
    NOT_CXL_OR_DISCONNECTED = 0x00
    RCD_MODE = 0x01
    CXL_68B_FLIT_AND_VH_MODE = 0x02
    STANDARD_256B_FLIT_MODE = 0x03
    CXL_LATENCY_OPTIMIZED_256B_FLIT_MODE = 0x04
    PBR_MODE = 0x05


class CONNECTED_DEVICE_TYPE(IntEnum):
    NO_DEVICE_DETECTED = 0x00
    PCIE_DEVICE = 0x01
    CXL_TYPE1_DEVICE = 0x02
    CXL_TYPE2_DEVICE = 0x03
    CXL_TYPE3_SLD = 0x04
    CXL_TYPE3_MLD = 0x05
    RESERVED = 0x06


class SupportedCxlModes(UnalignedBitStructure):
    _fields = [
        BitField("rcd_mode", 0, 0),
        BitField("cxl_68b_flit_and_vh_capable", 1, 1),
        BitField("256b_flit_and_cxl_capable", 2, 2),
        BitField("cxl_latency_optimized_256b_flit_capable", 3, 3),
        BitField("pbr_capable", 4, 4),
        BitField("reserved", 5, 7, FIELD_ATTR.RESERVED),
    ]


class CxlPortDevice(RunnableComponent):
    def __init__(self, transport_connection: CxlConnection, port_index: int):
        self._cxl_mem_manager: CxlMemManager | list[CxlMemManager]
        self._cxl_io_manager: CxlIoManager | list[CxlIoManager]
        self._cxl_cache_manager: CxlCacheManager | list[CxlCacheManager]

        self._vppb_upstream_connection: CxlConnection | list[CxlConnection] = CxlConnection()
        self._vppb_downstream_connection: CxlConnection | list[CxlConnection] = CxlConnection()

        super().__init__()
        self._port_index = port_index
        self._transport_connection = transport_connection

    def get_port_index(self) -> int:
        return self._port_index

    def get_transport_connection(self) -> CxlConnection:
        return self._transport_connection

    def get_downstream_connection(self) -> CxlConnection | list[CxlConnection]:
        return self._vppb_downstream_connection

    def get_upstream_connection(self) -> CxlConnection | list[CxlConnection]:
        return self._vppb_upstream_connection

    @abstractmethod
    def set_routing_table(self, vppb_routing_info: VppbRoutingInfo):
        """This must be implemented in the child class"""

    @abstractmethod
    def get_device_type(self) -> CXL_COMPONENT_TYPE:
        """This must be implemented in the child class"""

    async def _run(self):
        logger.info(self._create_message("Starting"))
        run_tasks = [
            create_task(self._cxl_io_manager.run()),
            create_task(self._cxl_mem_manager.run()),
            create_task(self._cxl_cache_manager.run()),
        ]
        wait_tasks = [
            create_task(self._cxl_io_manager.wait_for_ready()),
            create_task(self._cxl_mem_manager.wait_for_ready()),
            create_task(self._cxl_cache_manager.wait_for_ready()),
        ]
        # pylint: disable=duplicate-code
        await gather(*wait_tasks)
        await self._change_status_to_running()
        await gather(*run_tasks)
        logger.info(self._create_message("Stopped"))

    async def _stop(self):
        logger.info(self._create_message("Stopping"))
        tasks = [
            create_task(self._cxl_io_manager.stop()),
            create_task(self._cxl_mem_manager.stop()),
            create_task(self._cxl_cache_manager.stop()),
        ]
        await gather(*tasks)
