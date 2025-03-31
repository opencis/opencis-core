"""
Copyright (c) 2024, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from asyncio import create_task, gather
from dataclasses import dataclass
from typing import List, Dict, Optional, cast

from opencis.cxl.device.port_device import CxlPortDevice
from opencis.cxl.device.upstream_port_device import UpstreamPortDevice
from opencis.cxl.device.pci_to_pci_bridge_device import PpbDevice
from opencis.cxl.device.downstream_port_device import DownstreamPortDevice
from opencis.cxl.device.config.logical_device import (
    LogicalDeviceConfig,
    MultiLogicalDeviceConfig,
    SingleLogicalDeviceConfig,
)
from opencis.cxl.component.bind_processor import PpbDspBindProcessor
from opencis.cxl.component.switch_connection_manager import SwitchConnectionManager
from opencis.cxl.component.cxl_component import (
    PORT_TYPE,
    PortConfig,
)
from opencis.cxl.component.common import CXL_COMPONENT_TYPE
from opencis.util.component import RunnableComponent


@dataclass
class MemoryDeviceInfo:
    vendor_id: int
    device_id: int
    subsystem_vendor_id: int
    subsystem_id: int
    serial_number: str
    bound_port_id: int
    total_capacity: int


# TODO: Support initializing USP hdm decoder count
class PhysicalPortManager(RunnableComponent):
    def __init__(
        self,
        switch_connection_manager: SwitchConnectionManager,
        port_configs: List[PortConfig],
        # TODO: CE-35, device enumeration from DSP is not supported yet.
        # Read device configs from an environment file directly as a workaround.
        device_configs: Optional[List[LogicalDeviceConfig]] = None,
    ):
        super().__init__()
        self._port_devices: List[CxlPortDevice] = []
        self._ppb_devices: List[PpbDevice] = []
        self._ppb_binds: List[PpbDspBindProcessor] = []

        self._switch_connection_manager = switch_connection_manager
        self._device_configs = device_configs
        for port_index, port_config in enumerate(port_configs):
            transport_connection = self._switch_connection_manager.get_cxl_connection(port_index)
            if port_config.type == PORT_TYPE.USP:
                self._port_devices.append(UpstreamPortDevice(transport_connection, port_index))
                self._ppb_binds.append(None)
            else:
                physical_port = DownstreamPortDevice(transport_connection, port_index)
                ppb = PpbDevice(port_index)
                self._port_devices.append(physical_port)
                self._ppb_devices.append(ppb)
                bind = PpbDspBindProcessor(
                    ppb.get_downstream_connection(), physical_port.get_transport_connection()
                )
                self._ppb_binds.append(bind)
                physical_port.set_ppb(ppb, bind)

    def get_port_device(self, port_index: int) -> CxlPortDevice:
        if port_index < 0 or port_index >= len(self._port_devices):
            raise Exception(f"port index {port_index} is out of bound")
        return self._port_devices[port_index]

    def get_port_counts(self) -> int:
        return len(self._port_devices)

    def get_port_devices(self) -> List[CxlPortDevice]:
        return self._port_devices

    def get_ppb_devices(self) -> List[PpbDevice]:
        return self._ppb_devices

    def get_ppb_binds(self) -> List[PpbDspBindProcessor]:
        return self._ppb_binds

    def get_usp_hdm_decoder_count(self) -> int:
        hdm_decoder_count = 0
        for port in self._port_devices:
            if port.get_device_type() == CXL_COMPONENT_TYPE.USP:
                usp = cast(UpstreamPortDevice, port)
                hdm_decoder_count = usp.get_hdm_decoder_count()
        return hdm_decoder_count

    def get_connected_devices(self) -> List[MemoryDeviceInfo]:
        if self._device_configs is None:
            return []

        # TODO: CE-35, device enumeration from DSP is not supported yet.
        # This is a temporary implementation that finds connected device's info
        # from an environment file.
        device_configs_by_port_id: Dict[int, LogicalDeviceConfig] = {}
        for device_config in self._device_configs:
            device_configs_by_port_id[device_config.port_index] = device_config

        connected_devices = []
        switch_ports = self._switch_connection_manager.get_switch_ports()
        for port_index, switch_port in enumerate(switch_ports):
            if switch_port.port_config.type != PORT_TYPE.DSP:
                continue
            if port_index not in device_configs_by_port_id:
                raise Exception(f"Device config for port {port_index} is not found")
            switch_config = device_configs_by_port_id[port_index]
            switch_port = switch_ports[port_index]
            if switch_port.connected:
                if isinstance(switch_config, SingleLogicalDeviceConfig):
                    serial_number = switch_config.serial_number
                    total_capacity = switch_config.memory_size
                elif isinstance(switch_config, MultiLogicalDeviceConfig):
                    # Use the first serial number for now
                    serial_number = switch_config.serial_numbers[0]
                    total_capacity = sum(switch_config.memory_sizes)
                else:
                    raise Exception(f"Invalid device config type: {type(switch_config)}")

                device_info = MemoryDeviceInfo(
                    vendor_id=switch_config.vendor_id,
                    device_id=switch_config.device_id,
                    subsystem_vendor_id=switch_config.subsystem_vendor_id,
                    subsystem_id=switch_config.subsystem_id,
                    serial_number=serial_number,
                    bound_port_id=port_index,
                    total_capacity=total_capacity,
                )
                connected_devices.append(device_info)
        return connected_devices

    async def _run(self):
        run_tasks = []
        wait_tasks = []
        for port_device in self._port_devices:
            run_tasks.append(create_task(port_device.run()))
            wait_tasks.append(create_task(port_device.wait_for_ready()))
        for ppb_device in self._ppb_devices:
            run_tasks.append(create_task(ppb_device.run()))
            wait_tasks.append(create_task(ppb_device.wait_for_ready()))

        for ppb_bind in self._ppb_binds:
            if ppb_bind is not None:
                run_tasks.append(create_task(ppb_bind.run()))
                wait_tasks.append(create_task(ppb_bind.wait_for_ready()))

        await gather(*wait_tasks)
        await self._change_status_to_running()
        await gather(*run_tasks)

    async def _stop(self):
        tasks = []
        for port_device in self._port_devices:
            tasks.append(create_task(port_device.stop()))
        for ppb_device in self._ppb_devices:
            tasks.append(create_task(ppb_device.stop()))
        for ppb_bind in self._ppb_binds:
            if ppb_bind is not None:
                tasks.append(create_task(ppb_bind.stop()))
        await gather(*tasks)
