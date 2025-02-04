"""
 Copyright (c) 2024, Eeum, Inc.

 This software is licensed under the terms of the Revised BSD License.
 See LICENSE for details.
"""

import asyncio
from typing import Callable, Awaitable

from opencis.util.logger import logger
from opencis.util.component import RunnableComponent
from opencis.cpu import CPU
from opencis.cxl.component.cxl_memory_hub import CxlMemoryHub, CxlMemoryHubConfig
from opencis.cxl.component.root_complex.root_port_client_manager import RootPortClientConfig
from opencis.cxl.component.root_complex.root_port_switch import ROOT_PORT_SWITCH_TYPE
from opencis.cxl.component.root_complex.root_complex import SystemMemControllerConfig
from opencis.cxl.component.irq_manager import IrqManager
from opencis.cxl.component.host_manager import HostMgrConnClient, Result


class CxlHost(RunnableComponent):
    def __init__(
        self,
        port_index: int,
        sys_mem_size: int,
        sys_sw_app: Callable[[], Awaitable[None]],
        user_app: Callable[[], Awaitable[None]],
        host_name: str = None,
        switch_host: str = "0.0.0.0",
        switch_port: int = 8000,
        irq_host: str = "0.0.0.0",
        irq_port: int = 8500,
        host_conn_host: str = "0.0.0.0",
        host_conn_port: int = 8300,
        enable_hm: int = True,
    ):
        label = f"Port{port_index}"
        super().__init__(label)
        self._port_index = port_index
        root_ports = [RootPortClientConfig(port_index, switch_host, switch_port)]
        host_name = host_name if host_name else f"CxlHostPort{port_index}"

        self._sys_mem_config = SystemMemControllerConfig(
            memory_size=sys_mem_size,
            memory_filename=f"sys-mem{port_index}.bin",
        )
        self._irq_manager = IrqManager(
            device_name=host_name,
            addr=irq_host,
            port=irq_port,
            server=True,
            device_id=port_index,
        )
        self._cxl_memory_hub_config = CxlMemoryHubConfig(
            host_name=host_name,
            root_bus=port_index,
            root_port_switch_type=ROOT_PORT_SWITCH_TYPE.PASS_THROUGH,
            root_ports=root_ports,
            sys_mem_controller=self._sys_mem_config,
            irq_handler=self._irq_manager,
        )
        self._cxl_memory_hub = CxlMemoryHub(self._cxl_memory_hub_config)
        self._cpu = CPU(self._cxl_memory_hub, sys_sw_app, user_app)

        self._enable_hm = enable_hm
        if self._enable_hm:
            methods = {
                "HOST:CXL_HOST_READ": self._cxl_host_read,
                "HOST:CXL_HOST_WRITE": self._cxl_host_write,
            }
            self._host_mgr_conn_client = HostMgrConnClient(
                port_index=port_index,
                host=host_conn_host,
                port=host_conn_port,
                methods=methods,
            )

    def get_irq_manager(self):
        return self._irq_manager

    async def _cxl_host_read(self, addr: int):
        res = await self._cpu.load(addr, 64)
        if res is False:
            logger.error(self._create_message(f"Host Read: Error - 0x{addr:x} is invalid address"))
            return Result(f"Invalid Params: 0x{addr:x} is not a valid address")
        return Result(res)

    async def _cxl_host_write(self, addr: int, data: int):
        res = await self._cpu.store(addr, 64, data)
        if res is False:
            logger.error(self._create_message(f"Host Write: Error - 0x{addr:x} is invalid address"))
            return Result(f"Invalid Params: 0x{addr:x} is not a valid address")
        return Result(res)

    async def _run(self):
        tasks = [
            asyncio.create_task(self._irq_manager.run()),
            asyncio.create_task(self._cxl_memory_hub.run()),
        ]
        await self._irq_manager.wait_for_ready()
        await self._cxl_memory_hub.wait_for_ready()
        tasks.append(asyncio.create_task(self._cpu.run()))
        if self._enable_hm:
            tasks.append(asyncio.create_task(self._host_mgr_conn_client.run()))
            await self._host_mgr_conn_client.wait_for_ready()

        await self._change_status_to_running()
        await asyncio.gather(*tasks)

    async def _stop(self):
        tasks = [
            asyncio.create_task(self._cxl_memory_hub.stop()),
            asyncio.create_task(self._cpu.stop()),
            asyncio.create_task(self._irq_manager.stop()),
        ]
        await asyncio.gather(*tasks)
