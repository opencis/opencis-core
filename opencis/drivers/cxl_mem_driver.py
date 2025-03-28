"""
 Copyright (c) 2024, Eeum, Inc.

 This software is licensed under the terms of the Revised BSD License.
 See LICENSE for details.
"""

from typing import List

from opencis.util.component import LabeledComponent, Label
from opencis.cxl.component.root_complex.root_complex import RootComplex
from opencis.cxl.component.hdm_decoder import INTERLEAVE_GRANULARITY, INTERLEAVE_WAYS
from opencis.drivers.cxl_bus_driver import CxlBusDriver, CxlDeviceInfo
from opencis.util.logger import logger


class CxlMemDriver(LabeledComponent):
    def __init__(
        self, cxl_bus_driver: CxlBusDriver, root_complex: RootComplex, label: Label = None
    ):
        super().__init__(label)
        self._root_complex = root_complex
        self._cxl_bus_driver = cxl_bus_driver
        self._devices: List[CxlDeviceInfo] = []

    async def init(self):
        self.scan_mem_devices()

    def scan_mem_devices(self):
        self._devices = []
        for device in self._cxl_bus_driver.get_devices():
            if device.device_dvsec:
                self._devices.append(device)

    def get_devices(self):
        return self._devices

    def get_port_number(self, device: CxlDeviceInfo):
        downstream_port = device.parent
        if not downstream_port.is_downstream_port():
            bdf_str = downstream_port.pci_device_info.get_bdf_string()
            logger.warning(self._create_message(f"{bdf_str} is not upstream port"))
            return -1
        return downstream_port.pci_device_info.get_port_number()

    async def attach_single_mem_device(
        self, device: CxlDeviceInfo, hpa_base: int, size: int
    ) -> bool:
        # should only be used for non-interleave setup
        successful = await self.config_cxl_mem_device(device, hpa_base, size)
        if not successful:
            return False

        downsream_port = device.parent
        upstream_port = downsream_port.parent
        port_number = self.get_port_number(device)
        successful = await self.config_usp(upstream_port, hpa_base, size, [port_number])
        if not successful:
            return False

        return True

    async def config_cxl_mem_device(
        self,
        device: CxlDeviceInfo,
        hpa_base: int,
        size: int,
        ig: INTERLEAVE_GRANULARITY = INTERLEAVE_GRANULARITY.SIZE_256B,
        iw: INTERLEAVE_WAYS = INTERLEAVE_WAYS.WAY_1,
    ) -> bool:
        device.log_prefix = "CxlMemDriver"
        successful = await device.configure_hdm_decoder_device(
            hpa_base=hpa_base,
            hpa_size=size,
            interleaving_granularity=ig.value,
            interleaving_way=iw.value,
        )
        if not successful:
            bdf_str = device.pci_device_info.get_bdf_string()
            logger.warning(self._create_message(f"Failed to configure HDM decoder of {bdf_str}"))
            return False

        port_number = self.get_port_number(device)
        if port_number < 0:
            return False
        return True

    async def config_usp(
        self,
        upstream_port: CxlDeviceInfo,
        hpa_base: int,
        size: int,
        target_list: list[int],
        ig: INTERLEAVE_GRANULARITY = INTERLEAVE_GRANULARITY.SIZE_256B,
        iw: INTERLEAVE_WAYS = INTERLEAVE_WAYS.WAY_1,
    ) -> bool:
        upstream_port.log_prefix = "CxlMemDriver"
        if not upstream_port.is_upstream_port():
            bdf_str = upstream_port.pci_device_info.get_bdf_string()
            logger.warning(self._create_message(f"{bdf_str} is not upstream port"))
            return False

        successful = await upstream_port.configure_hdm_decoder_switch(
            hpa_base=hpa_base,
            hpa_size=size,
            target_list=target_list,
            interleaving_granularity=ig.value,
            interleaving_way=iw.value,
        )
        if not successful:
            bdf_str = upstream_port.pci_device_info.get_bdf_string()
            logger.warning(self._create_message(f"Failed to configure HDM decoder of {bdf_str}"))
            return False
        return True
