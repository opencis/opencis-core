"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from asyncio import gather, create_task

from opencis.util.component import RunnableComponent
from opencis.cxl.device.cxl_type3_device import CxlType3Device, CXL_T3_DEV_TYPE
from opencis.cxl.component.switch_connection_client import SwitchConnectionClient
from opencis.cxl.component.common import CXL_COMPONENT_TYPE


class SingleLogicalDevice(RunnableComponent):
    def __init__(
        self,
        memory_size: int,
        memory_file: str,
        serial_number: str,
        host: str = "0.0.0.0",
        port: int = 8000,
        port_index: int = -1,
        test_mode: bool = False,
        cxl_connection=None,
    ):
        label = f"Port{port_index}"
        super().__init__(label)

        self._test_mode = test_mode

        assert (
            not test_mode or cxl_connection is not None
        ), "cxl_connection must be passed in test mode"
        assert (
            test_mode or cxl_connection is None
        ), "cxl_connection must not be passed in non-test mode"

        if cxl_connection is not None:
            self._cxl_connection = cxl_connection
        else:
            self._sw_conn_client = SwitchConnectionClient(
                port_index, CXL_COMPONENT_TYPE.D2, host=host, port=port
            )
            self._cxl_connection = self._sw_conn_client.get_cxl_connection()

        self._cxl_type3_device = CxlType3Device(
            transport_connection=self._cxl_connection,
            memory_size=memory_size,
            memory_file=memory_file,
            serial_number=serial_number,
            dev_type=CXL_T3_DEV_TYPE.SLD,
            label=label,
        )

    async def _run(self):
        # pylint: disable=duplicate-code
        run_tasks = [create_task(self._cxl_type3_device.run())]
        wait_tasks = [create_task(self._cxl_type3_device.wait_for_ready())]
        if not self._test_mode:
            run_tasks += [create_task(self._sw_conn_client.run())]
            wait_tasks += [create_task(self._sw_conn_client.wait_for_ready())]

        await gather(*wait_tasks)
        await self._change_status_to_running()
        await gather(*run_tasks)

    async def _stop(self):
        stop_tasks = [create_task(self._cxl_type3_device.stop())]
        if not self._test_mode:
            stop_tasks += [create_task(self._sw_conn_client.stop())]

        await gather(*stop_tasks)

    def get_reg_vals(self):
        return self._cxl_type3_device.get_reg_vals()
