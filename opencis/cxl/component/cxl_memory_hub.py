"""
 Copyright (c) 2024, Eeum, Inc.

 This software is licensed under the terms of the Revised BSD License.
 See LICENSE for details.
"""

import asyncio
from dataclasses import dataclass, field
from typing import Callable, List
from opencis.cxl.component.irq_manager import Irq, IrqManager
from opencis.util.component import RunnableComponent
from opencis.cxl.component.root_complex.root_complex import (
    RootComplex,
    RootComplexConfig,
    SystemMemControllerConfig,
)
from opencis.cxl.component.cache_controller import (
    CacheController,
    CacheControllerConfig,
    MEM_ADDR_TYPE,
)
from opencis.cxl.component.root_complex.root_port_client_manager import (
    RootPortClientManager,
    RootPortClientManagerConfig,
    RootPortClientConfig,
)
from opencis.cxl.component.root_complex.root_port_switch import (
    RootPortSwitchPortConfig,
    ROOT_PORT_SWITCH_TYPE,
)
from opencis.cxl.transport.cache_fifo import CacheFifoPair
from opencis.cxl.transport.memory_fifo import (
    MemoryFifoPair,
    MemoryRequest,
    MemoryResponse,
    MEMORY_REQUEST_TYPE,
    MEMORY_RESPONSE_STATUS,
)
from opencis.util.pci import create_bdf


@dataclass
class CxlMemoryHubConfig:
    host_name: str
    root_bus: int
    sys_mem_controller: SystemMemControllerConfig
    irq_handler: IrqManager
    root_port_switch_type: ROOT_PORT_SWITCH_TYPE
    root_ports: List[RootPortClientConfig] = field(default_factory=list)


class CxlMemoryHub(RunnableComponent):
    def __init__(self, config: CxlMemoryHubConfig):
        super().__init__(lambda class_name: f"{config.host_name}:{class_name}")

        self._processor_to_cache_fifo = MemoryFifoPair()
        cache_to_home_agent_fifo = CacheFifoPair()
        home_agent_to_cache_fifo = CacheFifoPair()
        cache_to_coh_bridge_fifo = CacheFifoPair()
        coh_bridge_to_cache_fifo = CacheFifoPair()

        # Create Root Port Client Manager
        root_port_client_manager_config = RootPortClientManagerConfig(
            client_configs=config.root_ports, host_name=config.host_name
        )
        self._root_port_client_manager = RootPortClientManager(root_port_client_manager_config)

        # Create Root Complex
        root_complex_root_ports = [
            RootPortSwitchPortConfig(
                port_index=connection.port_index, downstream_connection=connection.connection
            )
            for connection in self._root_port_client_manager.get_cxl_connections()
        ]
        root_complex_config = RootComplexConfig(
            host_name=config.host_name,
            root_bus=config.root_bus,
            root_port_switch_type=config.root_port_switch_type,
            cache_to_home_agent_fifo=cache_to_home_agent_fifo,
            home_agent_to_cache_fifo=home_agent_to_cache_fifo,
            cache_to_coh_bridge_fifo=cache_to_coh_bridge_fifo,
            coh_bridge_to_cache_fifo=coh_bridge_to_cache_fifo,
            sys_mem_controller=config.sys_mem_controller,
            root_ports=root_complex_root_ports,
        )
        self._root_complex = RootComplex(root_complex_config)
        self._root_port = config.root_bus
        cache_controller_config = CacheControllerConfig(
            component_name=config.host_name,
            processor_to_cache_fifo=self._processor_to_cache_fifo,
            cache_to_coh_agent_fifo=cache_to_home_agent_fifo,
            coh_agent_to_cache_fifo=home_agent_to_cache_fifo,
            cache_to_coh_bridge_fifo=cache_to_coh_bridge_fifo,
            coh_bridge_to_cache_fifo=coh_bridge_to_cache_fifo,
            cache_num_assoc=4,
            cache_num_set=8,
        )
        self._cache_controller = CacheController(cache_controller_config)
        self._irq_handler = config.irq_handler

    def create_message(self, message):
        return self._create_message(message)

    def get_memory_ranges(self):
        return self._cache_controller.get_memory_ranges()

    def register_fm_add_mem_range(
        self, addr: int, size: int, addr_type: MEM_ADDR_TYPE, cb: Callable
    ):
        """
        This function is for registering Irq Handlers if the host wants the FM
        to handle host hot-plug requests.
        """

        def add_dev_callback():
            async def _cb(_):
                self._cache_controller.add_mem_range(addr, size, addr_type)
                cb()

            return _cb

        self._irq_handler.register_general_handler(
            Irq.DEV_ADDED,
            add_dev_callback(),
            True,
        )

    def register_fm_remove_mem_range(
        self, addr: int, size: int, addr_type: MEM_ADDR_TYPE, cb: Callable
    ):
        """
        This function is for registering Irq Handlers if the host wants the FM
        to handle host hot-plug requests.
        """
        self._cache_controller.remove_mem_range(addr, size, addr_type)

        def remove_dev_callback():
            async def _cb(_):
                cb()

            return _cb

        self._irq_handler.register_general_handler(
            Irq.DEV_REMOVED,
            remove_dev_callback(),
            True,
        )

    def add_mem_range(self, addr: int, size: int, addr_type: MEM_ADDR_TYPE):
        self._cache_controller.add_mem_range(addr, size, addr_type)

    def remove_mem_range(self, addr: int, size: int, addr_type: MEM_ADDR_TYPE):
        self._cache_controller.remove_mem_range(addr, size, addr_type)

    def _cfg_addr_to_bdf(self, cfg_addr: int) -> int:
        mem_range = self._cache_controller.get_mem_range(cfg_addr)
        cfg_addr -= mem_range.base_addr
        return create_bdf(
            (cfg_addr >> 20) & 0xFF,  # bus bits, n = 8
            (cfg_addr >> 15) & 0x1F,
            (cfg_addr >> 12) & 0x07,
        )

    async def _send_mem_request(self, packet: MemoryRequest) -> MemoryResponse:
        await self._processor_to_cache_fifo.request.put(packet)
        resp = await self._processor_to_cache_fifo.response.get()
        assert resp.status == MEMORY_RESPONSE_STATUS.OK
        return resp

    async def load(self, addr: int, size: int) -> int:
        addr_type = self._cache_controller.get_mem_addr_type(addr)
        match addr_type:
            case MEM_ADDR_TYPE.DRAM | MEM_ADDR_TYPE.CXL_CACHED | MEM_ADDR_TYPE.CXL_CACHED_BI:
                packet = MemoryRequest(MEMORY_REQUEST_TYPE.READ, addr, size)
                resp = await self._send_mem_request(packet)
                return resp.data
            case MEM_ADDR_TYPE.CXL_UNCACHED:
                packet = MemoryRequest(MEMORY_REQUEST_TYPE.UNCACHED_READ, addr, size)
                resp = await self._send_mem_request(packet)
                return resp.data
            case MEM_ADDR_TYPE.MMIO:
                return await self._root_complex.read_mmio(addr, size)
            case MEM_ADDR_TYPE.CFG:
                bdf = self._cfg_addr_to_bdf(addr)
                offset = addr & 0xFFF
                return await self._root_complex.read_config(bdf, offset, size)
            case MEM_ADDR_TYPE.OOB:
                return False

    async def store(self, addr: int, size: int, data: int):
        addr_type = self._cache_controller.get_mem_addr_type(addr)
        match addr_type:
            case MEM_ADDR_TYPE.DRAM | MEM_ADDR_TYPE.CXL_CACHED | MEM_ADDR_TYPE.CXL_CACHED_BI:
                packet = MemoryRequest(MEMORY_REQUEST_TYPE.WRITE, addr, size, data)
                await self._send_mem_request(packet)
            case MEM_ADDR_TYPE.CXL_UNCACHED:
                packet = MemoryRequest(MEMORY_REQUEST_TYPE.UNCACHED_WRITE, addr, size, data)
                await self._send_mem_request(packet)
            case MEM_ADDR_TYPE.MMIO:
                await self._root_complex.write_mmio(addr, size, data)
            case MEM_ADDR_TYPE.CFG:
                bdf = self._cfg_addr_to_bdf(addr)
                offset = addr & 0xFFF
                await self._root_complex.write_config(bdf, offset, size, data)
            case MEM_ADDR_TYPE.OOB:
                return False
        return True

    def get_root_complex(self):
        return self._root_complex

    def get_root_port(self):
        return self._root_port

    async def write_config(self, bdf: int, offset: int, size: int, value: int):
        await self._root_complex.write_config(bdf, offset, size, value)

    async def read_config(self, bdf: int, offset: int, size: int) -> int:
        return await self._root_complex.read_config(bdf, offset, size)

    async def write_mmio(self, address: int, size: int, value: int):
        await self._root_complex.write_mmio(address, size, value)

    async def read_mmio(self, address: int, size: int) -> int:
        return await self._root_complex.read_mmio(address, size)

    async def _run(self):
        run_tasks = [
            asyncio.create_task(self._root_port_client_manager.run()),
            asyncio.create_task(self._root_complex.run()),
            asyncio.create_task(self._cache_controller.run()),
        ]
        wait_tasks = [
            asyncio.create_task(self._root_port_client_manager.wait_for_ready()),
            asyncio.create_task(self._root_complex.wait_for_ready()),
            asyncio.create_task(self._cache_controller.wait_for_ready()),
        ]
        await asyncio.gather(*wait_tasks)
        await self._change_status_to_running()
        await asyncio.gather(*run_tasks)

    async def _stop(self):
        tasks = [
            asyncio.create_task(self._root_port_client_manager.stop()),
            asyncio.create_task(self._root_complex.stop()),
            asyncio.create_task(self._cache_controller.stop()),
        ]
        await asyncio.gather(*tasks)
