"""
 Copyright (c) 2024, Eeum, Inc.

 This software is licensed under the terms of the Revised BSD License.
 See LICENSE for details.
"""

import asyncio
from typing import Dict, Tuple
import pytest

from opencis.cxl.component.cache_controller import (
    CacheController,
    CacheControllerConfig,
    MEM_ADDR_TYPE,
)
from opencis.cxl.transport.memory_fifo import (
    MemoryFifoPair,
    MemoryRequest,
    MemoryResponse,
    MEMORY_REQUEST_TYPE,
    MEMORY_RESPONSE_STATUS,
)
from opencis.cxl.transport.cache_fifo import (
    CacheFifoPair,
    CacheRequest,
    CACHE_REQUEST_TYPE,
    CacheResponse,
    CACHE_RESPONSE_STATUS,
)
from opencis.cxl.component.cxl_memory_hub import CxlMemoryHub, CxlMemoryHubConfig
from opencis.cxl.component.root_complex.root_port_switch import ROOT_PORT_SWITCH_TYPE
from opencis.util.number_const import KB
from opencis.cxl.component.root_complex.root_port_client_manager import (
    RootPortClientManager,
    RootPortClientManagerConfig,
    RootPortClientConfig,
)

from opencis.cxl.transport.transaction import (
    CXL_MEM_M2SBIRSP_OPCODE,
)
from opencis.apps.cxl_simple_host import CxlHostManager, CxlSimpleHost, CxlHostUtilClient
from opencis.cxl.component.switch_connection_manager import SwitchConnectionManager
from opencis.cxl.component.cxl_component import PortConfig, PORT_TYPE
from opencis.cxl.component.physical_port_manager import PhysicalPortManager
from opencis.cxl.component.virtual_switch_manager import (
    VirtualSwitchManager,
    VirtualSwitchConfig,
)
from opencis.apps.single_logical_device import SingleLogicalDevice
from opencis.util.number_const import MB

BASE_TEST_PORT = 9400


# async def load(self, addr: int, size: int) -> int:
#     addr_type = self._cache_controller.get_mem_addr_type(addr)
#     match addr_type:
#         case MEM_ADDR_TYPE.DRAM | MEM_ADDR_TYPE.CXL_CACHED | MEM_ADDR_TYPE.CXL_CACHED_BI:
#             packet = MemoryRequest(MEMORY_REQUEST_TYPE.READ, addr, size)
#             resp = await self._send_mem_request(packet)
#             return resp.data
#         case MEM_ADDR_TYPE.CXL_UNCACHED:
#             packet = MemoryRequest(MEMORY_REQUEST_TYPE.UNCACHED_READ, addr, size)
#             resp = await self._send_mem_request(packet)
#             return resp.data
#         case MEM_ADDR_TYPE.MMIO:
#             return await self._root_complex.read_mmio(addr, size)
#         case MEM_ADDR_TYPE.CFG:
#             bdf = self._cfg_addr_to_bdf(addr)
#             offset = addr & 0xFFF
#             return await self._root_complex.read_config(bdf, offset, size)
#         case _:
#             raise Exception(self._create_message(f"Address 0x{addr:x} is OOB."))

# async def store(self, addr: int, size: int, data: int):
#     addr_type = self._cache_controller.get_mem_addr_type(addr)
#     match addr_type:
#         case MEM_ADDR_TYPE.DRAM | MEM_ADDR_TYPE.CXL_CACHED | MEM_ADDR_TYPE.CXL_CACHED_BI:
#             packet = MemoryRequest(MEMORY_REQUEST_TYPE.WRITE, addr, size, data)
#             await self._send_mem_request(packet)
#         case MEM_ADDR_TYPE.CXL_UNCACHED:
#             packet = MemoryRequest(MEMORY_REQUEST_TYPE.UNCACHED_WRITE, addr, size, data)
#             await self._send_mem_request(packet)
#         case MEM_ADDR_TYPE.MMIO:
#             await self._root_complex.write_mmio(addr, size, data)
#         case MEM_ADDR_TYPE.CFG:
#             bdf = self._cfg_addr_to_bdf(addr)
#             offset = addr & 0xFFF
#             await self._root_complex.write_config(bdf, offset, size, data)
#         case _:
#             raise Exception(self._create_message(f"Address 0x{addr:x} is OOB."))


@pytest.fixture
def cxl_host_cache_controller():
    config = CacheControllerConfig(
        component_name="MyDevice",
        processor_to_cache_fifo=MemoryFifoPair(),
        cache_to_coh_agent_fifo=CacheFifoPair(),
        coh_agent_to_cache_fifo=CacheFifoPair(),
        cache_num_assoc=4,
        cache_num_set=16 * KB // 4,
    )
    return CacheController(config)


@pytest.fixture
def cxl_dcoh_cache_controller():
    config = CacheControllerConfig(
        component_name="MyDevice",
        processor_to_cache_fifo=None,
        cache_to_coh_agent_fifo=CacheFifoPair(),
        coh_agent_to_cache_fifo=CacheFifoPair(),
        cache_num_assoc=4,
        cache_num_set=16 * KB // 4,
    )
    return CacheController(config)


async def send_mem_request(cache_controller, packet: MemoryRequest) -> MemoryResponse:
    await cache_controller._processor_to_cache_fifo.request.put(packet)
    resp = await cache_controller._processor_to_cache_fifo.response.get()
    assert resp.status == MEMORY_RESPONSE_STATUS.OK
    return resp


@pytest.mark.asyncio
async def test_cxl_host_cache_controller(cxl_host_cache_controller):
    cxl_host_cache_controller: CacheController
    cxl_host_cache_controller.add_mem_range(0x0, 0x1000, MEM_ADDR_TYPE.CXL_CACHED)
    req = MemoryRequest(MEMORY_REQUEST_TYPE.WRITE, 0x0, 0x8, 0xDEADBEEFDEADBEEF)
    resp = await send_mem_request(cxl_host_cache_controller, req)
    print("here")


# @pytest.mark.asyncio
# async def test_cxl_dcoh_cache_controller():
#     cache_contoller = CacheController
#     await host_manager.stop()


# @pytest.mark.asyncio
# async def test_cxl_host_manager_handle_res():
#     host_port = BASE_TEST_PORT + pytest.PORT.TEST_2
#     util_port = BASE_TEST_PORT + pytest.PORT.TEST_2 + 50

#     host_manager = CxlHostManager(host_port=host_port, util_port=util_port)
#     asyncio.create_task(host_manager.run())
#     await host_manager.wait_for_ready()
#     host = DummyHost()
#     asyncio.create_task(host.conn_open(port=host_port))
#     util_client = SimpleJsonClient(port=util_port)
#     await host.wait_connected()

#     addr = 0x40
#     data = 0xA5A5
#     cmd = request_json("UTIL_CXL_MEM_READ", params={"port": 0, "addr": addr})
#     await send_and_check_res(util_client, cmd, addr)
#     cmd = request_json("UTIL_CXL_MEM_WRITE", params={"port": 0, "addr": addr, "data": data})
#     await send_and_check_res(util_client, cmd, data)
#     cmd = request_json(
#         "UTIL_CXL_MEM_BIRSP",
#         params={"port": 0, "low_addr": 0x00, "opcode": CXL_MEM_M2SBIRSP_OPCODE.BIRSP_E},
#     )
#     await util_client.connect()
#     await util_client.send(cmd)

#     await host.conn_close()
#     await util_client.close()
#     await host_manager.stop()


# async def send_and_check_err(util_client: SimpleJsonClient, cmd: str, err_expected):
#     await util_client.connect()
#     await util_client.send(cmd)
#     resp = await util_client.recv()
#     resp = json.loads(resp)
#     assert resp["error"]["message"][:14] == err_expected


# @pytest.mark.asyncio
# async def test_cxl_host_manager_handle_err():
#     host_port = BASE_TEST_PORT + pytest.PORT.TEST_3
#     util_port = BASE_TEST_PORT + pytest.PORT.TEST_3 + 50

#     host_manager = CxlHostManager(host_port=host_port, util_port=util_port)
#     asyncio.create_task(host_manager.run())
#     await host_manager.wait_for_ready()
#     dummy_host = DummyHost()
#     asyncio.create_task(dummy_host.conn_open(port=host_port))
#     util_client = SimpleJsonClient(port=util_port)
#     await dummy_host.wait_connected()
#     data = 0xA5A5
#     valid_addr = 0x40
#     invalid_addr = 0x41

#     # Invalid USP port
#     err_expected = "Invalid Params"
#     cmd = request_json("UTIL_CXL_MEM_READ", params={"port": 10, "addr": valid_addr})
#     await send_and_check_err(util_client, cmd, err_expected)

#     # Invalid read address
#     err_expected = "Invalid Params"
#     cmd = request_json("UTIL_CXL_MEM_READ", params={"port": 0, "addr": invalid_addr})
#     await send_and_check_err(util_client, cmd, err_expected)

#     # Invalid write address
#     err_expected = "Invalid Params"
#     cmd = request_json("UTIL_CXL_MEM_WRITE", params={"port": 0, "addr": invalid_addr, "data": data})
#     await send_and_check_err(util_client, cmd, err_expected)

#     await dummy_host.conn_close()
#     await util_client.close()
#     await host_manager.stop()


# @pytest.mark.asyncio
# async def test_cxl_host_util_client():
#     host_port = BASE_TEST_PORT + pytest.PORT.TEST_4
#     util_port = BASE_TEST_PORT + pytest.PORT.TEST_4 + 50

#     host_manager = CxlHostManager(host_port=host_port, util_port=util_port)
#     asyncio.create_task(host_manager.run())
#     await host_manager.wait_for_ready()
#     dummy_host = DummyHost()
#     asyncio.create_task(dummy_host.conn_open(port=host_port))
#     await dummy_host.wait_connected()
#     util_client = CxlHostUtilClient(port=util_port)

#     data = 0xA5A5
#     valid_addr = 0x40
#     invalid_addr = 0x41
#     assert valid_addr == await util_client.cxl_mem_read(0, valid_addr)
#     assert data == await util_client.cxl_mem_write(0, valid_addr, data)
#     assert valid_addr == await util_client.reinit(0, valid_addr)
#     try:
#         await util_client.cxl_mem_read(0, invalid_addr)
#     except Exception as e:
#         assert str(e)[:14] == "Invalid Params"

#     await host_manager.stop()
#     await dummy_host.conn_close()


# @pytest.mark.asyncio
# async def test_cxl_host_type3_ete():
#     # pylint: disable=protected-access
#     host_port = BASE_TEST_PORT + pytest.PORT.TEST_5
#     util_port = BASE_TEST_PORT + pytest.PORT.TEST_5 + 50
#     switch_port = BASE_TEST_PORT + pytest.PORT.TEST_5 + 60

#     port_configs = [
#         PortConfig(PORT_TYPE.USP),
#         PortConfig(PORT_TYPE.DSP),
#     ]
#     sw_conn_manager = SwitchConnectionManager(port_configs, port=switch_port)
#     physical_port_manager = PhysicalPortManager(
#         switch_connection_manager=sw_conn_manager, port_configs=port_configs
#     )

#     switch_configs = [
#         VirtualSwitchConfig(
#             upstream_port_index=0,
#             vppb_counts=1,
#             initial_bounds=[1],
#             irq_host="127.0.0.1",
#             irq_port=BASE_TEST_PORT + pytest.PORT.TEST_1 + 60,
#         )
#     ]
#     allocated_ld = {}
#     allocated_ld[1] = [0]
#     virtual_switch_manager = VirtualSwitchManager(
#         switch_configs=switch_configs,
#         physical_port_manager=physical_port_manager,
#         allocated_ld=allocated_ld,
#     )
#     sld = SingleLogicalDevice(
#         port_index=1,
#         memory_size=0x1000000,
#         memory_file=f"mem{switch_port}.bin",
#         serial_number="DDDDDDDDDDDDDDDD",
#         port=switch_port,
#     )

#     host_manager = CxlHostManager(host_port=host_port, util_port=util_port)
#     host = CxlSimpleHost(port_index=0, switch_port=switch_port, host_port=host_port)
#     test_mode_host = CxlSimpleHost(
#         port_index=2, switch_port=switch_port, host_port=host_port, test_mode=True
#     )

#     start_tasks = [
#         asyncio.create_task(host.run()),
#         asyncio.create_task(host_manager.run()),
#         asyncio.create_task(sw_conn_manager.run()),
#         asyncio.create_task(physical_port_manager.run()),
#         asyncio.create_task(virtual_switch_manager.run()),
#         asyncio.create_task(sld.run()),
#     ]

#     wait_tasks = [
#         asyncio.create_task(sw_conn_manager.wait_for_ready()),
#         asyncio.create_task(physical_port_manager.wait_for_ready()),
#         asyncio.create_task(virtual_switch_manager.wait_for_ready()),
#         asyncio.create_task(host_manager.wait_for_ready()),
#         asyncio.create_task(host.wait_for_ready()),
#         asyncio.create_task(sld.wait_for_ready()),
#     ]
#     await asyncio.gather(*wait_tasks)

#     data = 0xA5A5
#     valid_addr = 0x40
#     invalid_addr = 0x41
#     test_tasks = [
#         asyncio.create_task(host._cxl_mem_read(valid_addr)),
#         asyncio.create_task(host._cxl_mem_read(invalid_addr)),
#         asyncio.create_task(host._cxl_mem_write(valid_addr, data)),
#         asyncio.create_task(host._cxl_mem_write(invalid_addr, data)),
#         asyncio.create_task(test_mode_host._reinit()),
#         asyncio.create_task(test_mode_host._reinit(valid_addr)),
#         asyncio.create_task(test_mode_host._reinit(invalid_addr)),
#     ]
#     await asyncio.gather(*test_tasks)

#     stop_tasks = [
#         asyncio.create_task(sw_conn_manager.stop()),
#         asyncio.create_task(physical_port_manager.stop()),
#         asyncio.create_task(virtual_switch_manager.stop()),
#         asyncio.create_task(host_manager.stop()),
#         asyncio.create_task(host.stop()),
#         asyncio.create_task(sld.stop()),
#     ]
#     await asyncio.gather(*stop_tasks)
#     await asyncio.gather(*start_tasks)


# TODO: This is a test for BI packets for now.
# Should be merged with test_cxl_host_type3_ete after
# the real BI logics are implemented.
# @pytest.mark.asyncio
# async def test_cxl_host_type3_ete_bi_only():
#     # pylint: disable=protected-access
#     host_port = BASE_TEST_PORT + pytest.PORT.TEST_6
#     util_port = BASE_TEST_PORT + pytest.PORT.TEST_6 + 50
#     switch_port = BASE_TEST_PORT + pytest.PORT.TEST_6 + 60

#     port_configs = [
#         PortConfig(PORT_TYPE.USP),
#         PortConfig(PORT_TYPE.DSP),
#     ]
#     sw_conn_manager = SwitchConnectionManager(port_configs, port=switch_port)
#     physical_port_manager = PhysicalPortManager(
#         switch_connection_manager=sw_conn_manager, port_configs=port_configs
#     )

#     switch_configs = [
#         VirtualSwitchConfig(
#             upstream_port_index=0,
#             vppb_counts=1,
#             initial_bounds=[1],
#         )
#     ]

#     virtual_switch_manager1 = VirtualSwitchManager(
#         switch_configs=switch_configs,
#         physical_port_manager=physical_port_manager,
#         bi_enable_override_for_test=1,
#         bi_forward_override_for_test=0,
#     )

#     virtual_switch_manager2 = VirtualSwitchManager(
#         switch_configs=switch_configs,
#         physical_port_manager=physical_port_manager,
#         bi_enable_override_for_test=0,
#         bi_forward_override_for_test=1,
#     )

#     virtual_switch_manager3 = VirtualSwitchManager(
#         switch_configs=switch_configs, physical_port_manager=physical_port_manager
#     )

#     async def run(virtual_switch_manager: VirtualSwitchManager):
#         DSP_2ND_BUS_NUM = 3
#         sld = SingleLogicalDevice(
#             port_index=1,
#             memory_size=0x1000000,
#             memory_file=f"mem{switch_port}.bin",
#             port=switch_port,
#         )

#         host_manager = CxlHostManager(host_port=host_port, util_port=util_port)
#         host = CxlSimpleHost(port_index=0, switch_port=switch_port, host_port=host_port)

#         start_tasks = [
#             asyncio.create_task(host.run()),
#             asyncio.create_task(host_manager.run()),
#             asyncio.create_task(sw_conn_manager.run()),
#             asyncio.create_task(physical_port_manager.run()),
#             asyncio.create_task(virtual_switch_manager.run()),
#             asyncio.create_task(sld.run()),
#         ]

#         wait_tasks = [
#             asyncio.create_task(sw_conn_manager.wait_for_ready()),
#             asyncio.create_task(physical_port_manager.wait_for_ready()),
#             asyncio.create_task(virtual_switch_manager.wait_for_ready()),
#             asyncio.create_task(host_manager.wait_for_ready()),
#             asyncio.create_task(host.wait_for_ready()),
#             asyncio.create_task(sld.wait_for_ready()),
#         ]
#         await asyncio.gather(*wait_tasks)

#         test_tasks = [
#             asyncio.create_task(sld._cxl_type3_device.init_bi_snp()),
#             asyncio.create_task(
#                 host._cxl_mem_birsp(
#                     CXL_MEM_M2SBIRSP_OPCODE.BIRSP_E, bi_id=DSP_2ND_BUS_NUM, bi_tag=0x00
#                 )
#             ),
#             # Required, or otherwise the queues will be stopped before handling anything
#             asyncio.create_task(asyncio.sleep(2, result="Blocker")),
#         ]
#         await asyncio.gather(*test_tasks)

#         stop_tasks = [
#             asyncio.create_task(sw_conn_manager.stop()),
#             asyncio.create_task(physical_port_manager.stop()),
#             asyncio.create_task(virtual_switch_manager.stop()),
#             asyncio.create_task(host_manager.stop()),
#             asyncio.create_task(host.stop()),
#             asyncio.create_task(sld.stop()),
#         ]
#         await asyncio.gather(*stop_tasks)
#         await asyncio.gather(*start_tasks)

#     await run(virtual_switch_manager1)
#     await run(virtual_switch_manager2)
#     await run(virtual_switch_manager3)


# pylint: disable=line-too-long
# @pytest.mark.asyncio
# async def test_cxl_host_type2_ete():
#     # pylint: disable=protected-access
#     host_port = BASE_TEST_PORT + pytest.PORT.TEST_7
#     util_port = BASE_TEST_PORT + pytest.PORT.TEST_7 + 50
#     switch_port = BASE_TEST_PORT + pytest.PORT.TEST_7 + 60

#     port_configs = [
#         PortConfig(PORT_TYPE.USP),
#         PortConfig(PORT_TYPE.DSP),
#     ]
#     sw_conn_manager = SwitchConnectionManager(port_configs, port=switch_port)
#     physical_port_manager = PhysicalPortManager(
#         switch_connection_manager=sw_conn_manager, port_configs=port_configs
#     )

#     switch_configs = [VirtualSwitchConfig(upstream_port_index=0, vppb_counts=1, initial_bounds=[1])]
#     virtual_switch_manager = VirtualSwitchManager(
#         switch_configs=switch_configs, physical_port_manager=physical_port_manager
#     )

#     accel_t2 = MyType2Accelerator(
#         port_index=1,
#         memory_size=0x1000000,
#         memory_file=f"mem{switch_port + 1}.bin",
#         port=switch_port,
#     )

#     host_manager = CxlHostManager(host_port=host_port, util_port=util_port)
#     host = CxlSimpleHost(port_index=0, switch_port=switch_port, host_port=host_port)
#     test_mode_host = CxlSimpleHost(
#         port_index=2, switch_port=switch_port, host_port=host_port, test_mode=True
#     )

#     start_tasks = [
#         asyncio.create_task(host.run()),
#         asyncio.create_task(host_manager.run()),
#         asyncio.create_task(sw_conn_manager.run()),
#         asyncio.create_task(physical_port_manager.run()),
#         asyncio.create_task(virtual_switch_manager.run()),
#         asyncio.create_task(accel_t2.run()),
#     ]

#     wait_tasks = [
#         asyncio.create_task(sw_conn_manager.wait_for_ready()),
#         asyncio.create_task(physical_port_manager.wait_for_ready()),
#         asyncio.create_task(virtual_switch_manager.wait_for_ready()),
#         asyncio.create_task(host_manager.wait_for_ready()),
#         asyncio.create_task(host.wait_for_ready()),
#         asyncio.create_task(accel_t2.wait_for_ready()),
#     ]
#     await asyncio.gather(*wait_tasks)

#     data = 0xA5A5
#     valid_addr = 0x40
#     invalid_addr = 0x41
#     test_tasks = [
#         asyncio.create_task(host._cxl_mem_read(valid_addr)),
#         asyncio.create_task(host._cxl_mem_read(invalid_addr)),
#         asyncio.create_task(host._cxl_mem_write(valid_addr, data)),
#         asyncio.create_task(host._cxl_mem_write(invalid_addr, data)),
#         asyncio.create_task(test_mode_host._reinit()),
#         asyncio.create_task(test_mode_host._reinit(valid_addr)),
#         asyncio.create_task(test_mode_host._reinit(invalid_addr)),
#     ]
#     await asyncio.gather(*test_tasks)

#     stop_tasks = [
#         asyncio.create_task(sw_conn_manager.stop()),
#         asyncio.create_task(physical_port_manager.stop()),
#         asyncio.create_task(virtual_switch_manager.stop()),
#         asyncio.create_task(host_manager.stop()),
#         asyncio.create_task(host.stop()),
#         asyncio.create_task(accel_t2.stop()),
#     ]
#     await asyncio.gather(*stop_tasks)
#     await asyncio.gather(*start_tasks)
import pytest
from unittest.mock import MagicMock, AsyncMock

# from  import (
#     CxlMemoryHub,
#     CxlMemoryHubConfig,
#     MemoryFifoPair,
#     CacheFifoPair,
#     RootPortClientManager,
#     RootComplex,
#     CacheController,
#     Irq,
#     MEM_ADDR_TYPE,
#     MEMORY_REQUEST_TYPE,
#     MemoryRequest,
#     RootPortClientManagerConfig,
#     RootPortSwitchPortConfig,
#     RootComplexConfig,
#     CacheControllerConfig,
# )


# @pytest.fixture
# def cxl_memory_hub():
#     # Setup the necessary mock configurations
#     config = MagicMock(spec=CxlMemoryHubConfig)
#     port_idx = 0
#     config.host_name = "test_host"
#     # config.root_ports = []  # Add appropriate mock config for root_ports
#     config.root_ports = [RootPortClientConfig(port_idx, "0.0.0.0", 8000)]
#     config.sys_mem_controller = MagicMock()
#     config.root_bus = port_idx
#     config.root_port_switch_type = ROOT_PORT_SWITCH_TYPE.PASS_THROUGH
#     config.irq_handler = MagicMock()

#     return CxlMemoryHub(config)


# # Test initialization and constructor
# def test_init(cxl_memory_hub):
#     # Ensure that all components are initialized correctly
#     assert cxl_memory_hub._processor_to_cache_fifo
#     assert isinstance(cxl_memory_hub._root_port_client_manager, RootPortClientManager)
#     assert isinstance(cxl_memory_hub._root_complex, RootComplex)
#     assert isinstance(cxl_memory_hub._cache_controller, CacheController)
#     assert cxl_memory_hub._irq_handler == cxl_memory_hub._irq_handler


# # Test create_message method
# def test_create_message(cxl_memory_hub):
#     message = "test_message"
#     result = cxl_memory_hub.create_message(message)
#     assert result == cxl_memory_hub._create_message(message)


# # Test get_memory_ranges method
# def test_get_memory_ranges(cxl_memory_hub):
#     cxl_memory_hub._cache_controller.get_memory_ranges = MagicMock(return_value=[1, 2, 3])
#     result = cxl_memory_hub.get_memory_ranges()
#     assert result == [1, 2, 3]


# # Test add_mem_range method
# def test_add_mem_range(cxl_memory_hub):
#     addr, size, addr_type = 0x1000, 1024, MEM_ADDR_TYPE.DRAM
#     cxl_memory_hub._cache_controller.add_mem_range = MagicMock()
#     cxl_memory_hub.add_mem_range(addr, size, addr_type)
#     cxl_memory_hub._cache_controller.add_mem_range.assert_called_once_with(addr, size, addr_type)


# # Test remove_mem_range method
# def test_remove_mem_range(cxl_memory_hub):
#     addr, size, addr_type = 0x1000, 1024, MEM_ADDR_TYPE.DRAM
#     cxl_memory_hub._cache_controller.remove_mem_range = MagicMock()
#     cxl_memory_hub.remove_mem_range(addr, size, addr_type)
#     cxl_memory_hub._cache_controller.remove_mem_range.assert_called_once_with(addr, size, addr_type)


# # Test register_fm_add_mem_range method
# def test_register_fm_add_mem_range(cxl_memory_hub):
#     addr, size, addr_type = 0x1000, 1024, MEM_ADDR_TYPE.DRAM
#     cb = MagicMock()
#     cxl_memory_hub.register_fm_add_mem_range(addr, size, addr_type, cb)
#     cxl_memory_hub._irq_handler.register_general_handler.assert_called_once()


# # Test register_fm_remove_mem_range method
# def test_register_fm_remove_mem_range(cxl_memory_hub):
#     addr, size, addr_type = 0x1000, 1024, MEM_ADDR_TYPE.DRAM
#     cb = MagicMock()
#     cxl_memory_hub.register_fm_remove_mem_range(addr, size, addr_type, cb)
#     cxl_memory_hub._irq_handler.register_general_handler.assert_called_once()


# # Test async load method (simulating async call)
# @pytest.mark.asyncio
# async def test_load(cxl_memory_hub):
#     addr, size = 0x1000, 1024
#     cxl_memory_hub._cache_controller.get_mem_addr_type = MagicMock(return_value=MEM_ADDR_TYPE.DRAM)
#     cxl_memory_hub._send_mem_request = AsyncMock(return_value=MagicMock(data=42))

#     result = await cxl_memory_hub.load(addr, size)
#     assert result == 42


# # Test async store method (simulating async call)
# @pytest.mark.asyncio
# async def test_store(cxl_memory_hub):
#     addr, size, data = 0x1000, 1024, 256
#     cxl_memory_hub._cache_controller.get_mem_addr_type = MagicMock(return_value=MEM_ADDR_TYPE.DRAM)
#     cxl_memory_hub._send_mem_request = AsyncMock()

#     await cxl_memory_hub.store(addr, size, data)
#     cxl_memory_hub._send_mem_request.assert_called_once()


# # Test _cfg_addr_to_bdf method (testing internal address translation)
# def test_cfg_addr_to_bdf(cxl_memory_hub):
#     cfg_addr = 0x100000
#     cxl_memory_hub._cache_controller.get_mem_range = MagicMock(
#         return_value=MagicMock(base_addr=0x1000)
#     )

#     bdf = cxl_memory_hub._cfg_addr_to_bdf(cfg_addr)
#     assert isinstance(bdf, int)


# # Test exception handling in store/load methods
# @pytest.mark.asyncio
# async def test_store_load_exception(cxl_memory_hub):
#     addr, size, data = 0x1000, 1024, 256
#     addr_type = MEM_ADDR_TYPE.UNKNOWN

#     with pytest.raises(Exception):
#         await cxl_memory_hub.store(addr, size, data)

#     with pytest.raises(Exception):
#         await cxl_memory_hub.load(addr, size)


# # Test async _run method (simulate async run)
# @pytest.mark.asyncio
# async def test_run(cxl_memory_hub):
#     cxl_memory_hub._root_port_client_manager.run = AsyncMock()
#     cxl_memory_hub._root_complex.run = AsyncMock()
#     cxl_memory_hub._cache_controller.run = AsyncMock()

#     await cxl_memory_hub._run()

#     cxl_memory_hub._root_port_client_manager.run.assert_called_once()
#     cxl_memory_hub._root_complex.run.assert_called_once()
#     cxl_memory_hub._cache_controller.run.assert_called_once()


# # Test async _stop method (simulate async stop)
# @pytest.mark.asyncio
# async def test_stop(cxl_memory_hub):
#     cxl_memory_hub._root_port_client_manager.stop = AsyncMock()
#     cxl_memory_hub._root_complex.stop = AsyncMock()
#     cxl_memory_hub._cache_controller.stop = AsyncMock()

#     await cxl_memory_hub._stop()

#     cxl_memory_hub._root_port_client_manager.stop.assert_called_once()
#     cxl_memory_hub._root_complex.stop.assert_called_once()
#     cxl_memory_hub._cache_controller.stop.assert_called_once()
