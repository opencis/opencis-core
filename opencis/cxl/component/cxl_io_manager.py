"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

import asyncio
from typing import Optional, Callable

from opencis.cxl.component.cxl_io_callback_data import CxlIoCallbackData
from opencis.pci.component.mmio_manager import MmioManager
from opencis.pci.component.config_space_manager import ConfigSpaceManager, PCI_DEVICE_TYPE
from opencis.pci.component.fifo_pair import FifoPair
from opencis.util.component import RunnableComponent


class CxlIoManager(RunnableComponent):
    def __init__(
        self,
        mmio_upstream_fifo: FifoPair,
        mmio_downstream_fifo: Optional[FifoPair],
        cfg_upstream_fifo: FifoPair,
        cfg_downstream_fifo: Optional[FifoPair],
        device_type: PCI_DEVICE_TYPE,
        init_callback: Callable[[CxlIoCallbackData], None],
        label: Optional[str] = None,
        ld_id: int = 0,
    ):
        super().__init__(label)
        self._mmio_manager = MmioManager(
            mmio_upstream_fifo,
            mmio_downstream_fifo,
            label=label,
        )
        self._config_space_manager = ConfigSpaceManager(
            cfg_upstream_fifo,
            cfg_downstream_fifo,
            device_type=device_type,
            label=label,
        )
        init_callback(CxlIoCallbackData(self._mmio_manager, self._config_space_manager, ld_id))

    def get_cfg_reg_vals(self):
        return self._config_space_manager.get_register()

    async def _run(self):
        run_tasks = [
            asyncio.create_task(self._mmio_manager.run()),
            asyncio.create_task(self._config_space_manager.run()),
        ]
        wait_tasks = [
            asyncio.create_task(self._mmio_manager.wait_for_ready()),
            asyncio.create_task(self._config_space_manager.wait_for_ready()),
        ]
        await asyncio.gather(*wait_tasks)
        await self._change_status_to_running()
        await asyncio.gather(*run_tasks)

    async def _stop(self):
        tasks = [
            asyncio.create_task(self._mmio_manager.stop()),
            asyncio.create_task(self._config_space_manager.stop()),
        ]
        await asyncio.gather(*tasks)
