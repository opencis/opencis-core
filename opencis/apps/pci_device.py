"""
Copyright (c) 2024, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from asyncio import gather, create_task
from opencis.util.component import RunnableComponent
from opencis.pci.device.pci_device import PciDevice as PciDeviceInternal
from opencis.pci.component.pci import (
    PciComponentIdentity,
    EEUM_VID,
    SW_EP_DID,
    PCI_CLASS,
    PCI_SYSTEM_PERIPHERAL_SUBCLASS,
)
from opencis.cxl.component.switch_connection_client import SwitchConnectionClient
from opencis.cxl.component.common import CXL_COMPONENT_TYPE


class PciDevice(RunnableComponent):
    def __init__(
        self,
        port_index: int,
        bar_size: int,
        host: str = "0.0.0.0",
        port: int = 8000,
    ):
        label = f"Port{port_index}"
        super().__init__(label)
        self._sw_conn_client = SwitchConnectionClient(
            port_index,
            CXL_COMPONENT_TYPE.P,
            host=host,
            port=port,
            parent_name=f"PciDevice{port_index}",
        )
        self._pci_device = PciDeviceInternal(
            transport_connection=self._sw_conn_client.get_cxl_connection(),
            identity=PciComponentIdentity(
                EEUM_VID,
                SW_EP_DID,
                PCI_CLASS.SYSTEM_PERIPHERAL,
                PCI_SYSTEM_PERIPHERAL_SUBCLASS.OTHER,
            ),
            bar_size=bar_size,
            label=f"PCIDevice{port_index}",
        )

    async def _run(self):
        tasks = [
            create_task(self._sw_conn_client.run()),
            create_task(self._pci_device.run()),
        ]
        wait_tasks = [
            create_task(self._sw_conn_client.wait_for_ready()),
            create_task(self._pci_device.wait_for_ready()),
        ]
        await gather(*wait_tasks)
        await self._change_status_to_running()
        await gather(*tasks)

    async def _stop(self):
        tasks = [
            create_task(self._sw_conn_client.stop()),
            create_task(self._pci_device.stop()),
        ]
        await gather(*tasks)
