"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from asyncio import gather, create_task
from typing import List

from opencis.apps.single_logical_device import SingleLogicalDevice
from opencis.util.component import RunnableComponent


class MultiHeadedSingleLogicalDevice(RunnableComponent):
    def __init__(
        self,
        num_ports,
        memory_size: int,
        memory_file: str,
        serial_number: str,
        host: str = "0.0.0.0",
        port: int = 8000,
        port_indexes: List[int] = None,
        test_mode: bool = False,
        cxl_connection=None,
    ):
        if port_indexes is None:
            port_indexes = [-1] * num_ports

        label = f"Port{','.join(map(str, port_indexes))}"
        super().__init__(label)

        self._sld_devices = []
        for i in range(num_ports):
            _memory_file = f"multiheaded_{i}_{memory_file}"
            self._sld_devices.append(
                SingleLogicalDevice(
                    memory_size=memory_size,
                    memory_file=_memory_file,
                    serial_number=serial_number,
                    host=host,
                    port=port,
                    port_index=port_indexes[i],
                    test_mode=test_mode,
                    cxl_connection=cxl_connection,
                )
            )

    async def _run(self):
        run_tasks = []
        for sld_device in self._sld_devices:
            run_tasks.append(create_task(sld_device.run()))
        wait_tasks = []
        for sld_device in self._sld_devices:
            wait_tasks.append(create_task(sld_device.wait_for_ready()))

        await gather(*wait_tasks)
        await self._change_status_to_running()
        await gather(*run_tasks)

    async def _stop(self):
        tasks = []
        for sld_device in self._sld_devices:
            tasks.append(create_task(sld_device.stop()))
        await gather(*tasks)

    def get_sld_devices(self):
        return self._sld_devices
