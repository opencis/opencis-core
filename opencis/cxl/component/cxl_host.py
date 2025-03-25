"""
 Copyright (c) 2024, Eeum, Inc.

 This software is licensed under the terms of the Revised BSD License.
 See LICENSE for details.
"""

import asyncio
from typing import Callable, Awaitable
from dataclasses import dataclass, field
import inspect

from opencis.util.logger import logger
from opencis.util.component import RunnableComponent
from opencis.cpu import CPU
from opencis.cxl.component.cxl_memory_hub import CxlMemoryHub, CxlMemoryHubConfig
from opencis.cxl.component.root_complex.root_port_client_manager import RootPortClientConfig
from opencis.cxl.component.root_complex.root_port_switch import ROOT_PORT_SWITCH_TYPE
from opencis.cxl.component.root_complex.root_complex import SystemMemControllerConfig
from opencis.cxl.component.irq_manager import IrqManager
from opencis.cxl.component.host_manager import HostMgrConnClient, Result


@dataclass
class CxlHostConfig:
    port_index: int
    sys_mem_size: int
    sys_sw_app: Callable[[], Awaitable[None]]
    user_app: Callable[[], Awaitable[None]]
    host_name: str = None
    switch_host: str = "0.0.0.0"
    switch_port: int = 8000
    irq_host: str = "0.0.0.0"
    irq_port: int = 8500
    host_conn_host: str = "0.0.0.0"
    host_conn_port: int = 8300
    enable_hm: bool = True


class CxlHost(RunnableComponent):
    def __init__(self, config: CxlHostConfig):
        label = f"Port{config.port_index}"
        super().__init__(label)
        self._port_index = config.port_index
        root_ports = [
            RootPortClientConfig(config.port_index, config.switch_host, config.switch_port)
        ]
        host_name = config.host_name if config.host_name else f"CxlHostPort{config.port_index}"

        self._sys_mem_config = SystemMemControllerConfig(
            memory_size=config.sys_mem_size,
            memory_filename=f"sys-mem{config.port_index}.bin",
        )
        self._irq_manager = IrqManager(
            device_name=host_name,
            addr=config.irq_host,
            port=config.irq_port,
            server=True,
            device_id=config.port_index,
        )
        self._cxl_memory_hub_config = CxlMemoryHubConfig(
            host_name=host_name,
            root_bus=config.port_index,
            root_port_switch_type=ROOT_PORT_SWITCH_TYPE.PASS_THROUGH,
            root_ports=root_ports,
            sys_mem_controller=self._sys_mem_config,
            irq_handler=self._irq_manager,
        )
        self._cxl_memory_hub = CxlMemoryHub(self._cxl_memory_hub_config)
        self._cpu = CPU(self._cxl_memory_hub, config.sys_sw_app, config.user_app)

        self._enable_hm = config.enable_hm
        if self._enable_hm:
            methods = {
                "HOST:CXL_HOST_READ": self._cxl_host_read,
                "HOST:CXL_HOST_WRITE": self._cxl_host_write,
            }
            self._host_mgr_conn_client = HostMgrConnClient(
                port_index=config.port_index,
                host=config.host_conn_host,
                port=config.host_conn_port,
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
            await self._irq_manager.run_wait_ready(),
            await self._cxl_memory_hub.run_wait_ready(),
        ]
        t = asyncio.create_task(self._cpu.run())
        await self._cpu.wait_for_ready()
        logger.info(f"File: {__file__}, Line: {inspect.currentframe().f_lineno}")
        if self._enable_hm:
            tasks.append(asyncio.create_task(self._host_mgr_conn_client.run()))
            await self._host_mgr_conn_client.wait_for_ready()

        await self._change_status_to_running()
        logger.info(f"File: {__file__}, Line: {inspect.currentframe().f_lineno}")
        logger.info(f"{tasks}")
        await asyncio.gather(*tasks)
        logger.info(f"File: {__file__}, Line: {inspect.currentframe().f_lineno}")
        await t
        logger.info(f"File: {__file__}, Line: {inspect.currentframe().f_lineno}")

    async def _stop(self):
        logger.info(f"File: {__file__}, Line: {inspect.currentframe().f_lineno}")
        t1 = asyncio.create_task(self._cxl_memory_hub.stop())
        t2 = asyncio.create_task(self._cpu.stop())
        t3 = asyncio.create_task(self._irq_manager.stop())
        logger.info(f"File: {__file__}, Line: {inspect.currentframe().f_lineno}")
        await t1
        logger.info(f"File: {__file__}, Line: {inspect.currentframe().f_lineno}")
        await t3
        logger.info(f"File: {__file__}, Line: {inspect.currentframe().f_lineno}")
        await t2
        logger.info(f"File: {__file__}, Line: {inspect.currentframe().f_lineno}")
