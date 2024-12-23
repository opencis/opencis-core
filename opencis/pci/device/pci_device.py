"""
 Copyright (c) 2024, Eeum, Inc.

 This software is licensed under the terms of the Revised BSD License.
 See LICENSE for details.
"""

from asyncio import create_task, gather
from typing import Optional

from opencis.pci.component.pci import (
    PciComponentIdentity,
    PciComponent,
    EEUM_VID,
    SW_EP_DID,
    PCI_CLASS,
    PCI_SYSTEM_PERIPHERAL_SUBCLASS,
)
from opencis.pci.component.pci_connection import PciConnection
from opencis.pci.component.mmio_manager import MmioManager, BarEntry
from opencis.pci.component.config_space_manager import (
    ConfigSpaceManager,
    PCI_DEVICE_TYPE,
)
from opencis.util.component import RunnableComponent
from opencis.util.unaligned_bit_structure import (
    ShareableByteArray,
    UnalignedBitStructure,
)
from opencis.pci.config_space import (
    PciExpressConfigSpace,
    PciExpressDeviceConfigSpaceOptions,
)


class PciDevice(RunnableComponent):
    def __init__(
        self,
        transport_connection: PciConnection,
        identity: Optional[PciComponentIdentity] = None,
        bar_size: int = 0,
        label: Optional[str] = None,
    ):
        super().__init__()
        if identity is None:
            identity = PciComponentIdentity(
                vendor_id=EEUM_VID,
                device_id=SW_EP_DID,
                base_class_code=PCI_CLASS.SYSTEM_PERIPHERAL,
                sub_class_coce=PCI_SYSTEM_PERIPHERAL_SUBCLASS.OTHER,
            )
        self._upstream_connection = transport_connection
        self._label = label
        self._mmio_manager = MmioManager(
            upstream_fifo=self._upstream_connection.mmio_fifo, label=label
        )
        pci_component = PciComponent(identity, self._mmio_manager)
        self._config_space_manager = ConfigSpaceManager(
            upstream_fifo=self._upstream_connection.cfg_fifo,
            label=self._label,
            device_type=PCI_DEVICE_TYPE.ENDPOINT,
        )
        if bar_size > 0:
            register = UnalignedBitStructure(data=ShareableByteArray(bar_size))
            self._mmio_manager.set_bar_entries([BarEntry(register=register)])
        pci_register_options = PciExpressDeviceConfigSpaceOptions(pci_component=pci_component)
        pci_register = PciExpressConfigSpace(options=pci_register_options)
        self._config_space_manager.set_register(pci_register)

    async def _run(self):
        tasks = [
            create_task(self._mmio_manager.run()),
            create_task(self._config_space_manager.run()),
        ]
        wait_tasks = [
            create_task(self._mmio_manager.wait_for_ready()),
            create_task(self._config_space_manager.wait_for_ready()),
        ]
        await gather(*wait_tasks)
        await self._change_status_to_running()
        await gather(*tasks)

    async def _stop(self):
        tasks = [
            create_task(self._mmio_manager.stop()),
            create_task(self._config_space_manager.stop()),
        ]
        await gather(*tasks)
