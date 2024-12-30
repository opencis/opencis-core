"""
 Copyright (c) 2024, Eeum, Inc.

 This software is licensed under the terms of the Revised BSD License.
 See LICENSE for details.
"""

from asyncio import gather, create_task
from typing import List

from opencis.cxl.component.cxl_connection import CxlConnection
from opencis.util.component import RunnableComponent
from opencis.cxl.device.cxl_type3_device import CxlType3Device, CXL_T3_DEV_TYPE
from opencis.cxl.component.switch_connection_client import SwitchConnectionClient
from opencis.cxl.component.cxl_component import CXL_COMPONENT_TYPE
from opencis.cxl.component.cxl_packet_processor import FifoGroup


class MultiLogicalDevice(RunnableComponent):
    def __init__(
        self,
        port_index: int,
        memory_sizes: List[int],
        memory_files: List[str],
        serial_numbers: List[str],
        host: str = "0.0.0.0",
        port: int = 8000,
        test_mode: bool = False,
        cxl_connections: List[CxlConnection] = None,
    ):
        label = f"Port{port_index}"
        super().__init__(label)

        self._cxl_type3_devices: List[CxlType3Device] = []
        self._test_mode = test_mode

        assert len(memory_sizes) == len(
            memory_files
        ), "memory_sizes, and memory_files must have the same length"
        ld_count = len(memory_sizes)

        assert (
            not test_mode or cxl_connections is not None
        ), "cxl_connections must be passed in test mode"
        assert (
            test_mode or cxl_connections is None
        ), "cxl_connections must not be passed in non-test mode"

        if cxl_connections is not None:
            self._cxl_connections = cxl_connections
        else:
            self._sw_conn_client = SwitchConnectionClient(
                port_index, CXL_COMPONENT_TYPE.LD, ld_count=ld_count, host=host, port=port
            )
            self._cxl_connections = self._sw_conn_client.get_cxl_connection()

        base_outgoing = FifoGroup(
            self._cxl_connections[0].cfg_fifo.target_to_host,
            self._cxl_connections[0].mmio_fifo.target_to_host,
            self._cxl_connections[0].cxl_mem_fifo.target_to_host,
            self._cxl_connections[0].cxl_cache_fifo.target_to_host,
            self._cxl_connections[0].cci_fifo.target_to_host,
        )

        # Share the outgoing queue across multiple LDs
        # TODO: avoid creation at all
        if ld_count > 1:
            for i in range(1, ld_count):
                connection = self._cxl_connections[i]
                connection.cfg_fifo.target_to_host = base_outgoing.cfg_space
                connection.mmio_fifo.target_to_host = base_outgoing.mmio
                connection.cxl_mem_fifo.target_to_host = base_outgoing.cxl_mem
                connection.cxl_cache_fifo.target_to_host = base_outgoing.cxl_cache
                connection.cci_fifo.target_to_host = base_outgoing.cci_fifo

        for ld in range(ld_count):
            cxl_type3_device = CxlType3Device(
                transport_connection=self._cxl_connections[ld],
                memory_size=memory_sizes[ld],
                memory_file=memory_files[ld],
                serial_number=serial_numbers[ld],
                dev_type=CXL_T3_DEV_TYPE.MLD,
                label=label,
            )
            self._cxl_type3_devices.append(cxl_type3_device)

    async def _run(self):
        # pylint: disable=duplicate-code
        run_tasks = [create_task(device.run()) for device in self._cxl_type3_devices]
        wait_tasks = [create_task(device.wait_for_ready()) for device in self._cxl_type3_devices]
        if not self._test_mode:
            run_tasks += [create_task(self._sw_conn_client.run())]
            wait_tasks += [create_task(self._sw_conn_client.wait_for_ready())]

        await gather(*wait_tasks)
        await self._change_status_to_running()
        await gather(*run_tasks)

    async def _stop(self):
        stop_tasks = [create_task(device.stop()) for device in self._cxl_type3_devices]
        if not self._test_mode:
            stop_tasks += [create_task(self._sw_conn_client.stop())]

        await gather(*stop_tasks)
