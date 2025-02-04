"""
 Copyright (c) 2024, Eeum, Inc.

 This software is licensed under the terms of the Revised BSD License.
 See LICENSE for details.
"""

import asyncio

from opencis.cxl.transport.transaction import CXL_MEM_M2SBIRSP_OPCODE
from opencis.util.logger import logger
from opencis.util.component import RunnableComponent
from opencis.cxl.device.root_port_device import CxlRootPortDevice
from opencis.cxl.component.switch_connection_client import SwitchConnectionClient
from opencis.cxl.component.host_manager import HostMgrConnClient, Result
from opencis.cxl.component.common import CXL_COMPONENT_TYPE


class CxlSimpleHost(RunnableComponent):
    def __init__(
        self,
        port_index: int,
        switch_host: str = "0.0.0.0",
        switch_port: int = 8000,
        host_host: str = "0.0.0.0",
        host_port: int = 8300,
        hm_mode: bool = True,
        test_mode: bool = False,
    ):
        label = f"Port{port_index}"
        super().__init__(label)
        self._test_mode = test_mode
        self._sw_conn_client = SwitchConnectionClient(
            port_index, CXL_COMPONENT_TYPE.R, host=switch_host, port=switch_port
        )
        self._methods = {
            "HOST_CXL_MEM_READ": self._cxl_mem_read,
            "HOST_CXL_MEM_WRITE": self._cxl_mem_write,
            "HOST_CXL_MEM_BIRSP": self._cxl_mem_birsp,
        }
        if hm_mode:
            self._host_mgr_conn_client = HostMgrConnClient(
                port_index=port_index, host=host_host, port=host_port, methods=self._methods
            )
        else:
            logger.debug(
                self._create_message(
                    "HostMgrConnClient is not starting because of the --no-hm arg."
                )
            )
        self._root_port_device = CxlRootPortDevice(
            downstream_connection=self._sw_conn_client.get_cxl_connection(),
            label=label,
            test_mode=self._test_mode,
        )
        self._port_index = port_index
        self._hm_mode = hm_mode

    def _is_valid_addr(self, addr: int) -> bool:
        return 0 <= addr <= self._root_port_device.get_used_hpa_size() and (addr % 0x40 == 0)

    async def _cxl_mem_read(self, addr: int) -> Result:
        logger.info(self._create_message(f"CXL.mem Read: addr=0x{addr:x}"))
        if self._is_valid_addr(addr) is False:
            logger.error(
                self._create_message(f"CXL.mem Read: Error - 0x{addr:x} is not a valid address")
            )
            return Result(f"Invalid Params: 0x{addr:x} is not a valid address")
        op_addr = addr + self._root_port_device.get_hpa_base()
        res = await self._root_port_device.cxl_mem_read(op_addr)
        return Result(res)

    async def _cxl_mem_write(self, addr: int, data: int) -> Result:
        logger.info(self._create_message(f"CXL.mem Write: addr=0x{addr:x} data=0x{data:x}"))
        if self._is_valid_addr(addr) is False:
            logger.error(
                self._create_message(f"CXL.mem Write: Error - 0x{addr:x} is not a valid address")
            )
            return Result(f"Invalid Params: 0x{addr:x} is not a valid address")
        op_addr = addr + self._root_port_device.get_hpa_base()
        res = await self._root_port_device.cxl_mem_write(op_addr, data)
        return Result(res)

    async def _cxl_mem_birsp(
        self, opcode: CXL_MEM_M2SBIRSP_OPCODE, bi_id: int = 0, bi_tag: int = 0
    ) -> Result:
        logger.info(self._create_message(f"CXL.mem BI-RSP: opcode=0x{opcode:x}"))
        res = await self._root_port_device.cxl_mem_birsp(opcode, bi_id, bi_tag)
        return Result(res)

    async def _run(self):
        tasks = [
            asyncio.create_task(self._sw_conn_client.run()),
            asyncio.create_task(self._root_port_device.run()),
        ]
        if self._hm_mode:
            tasks.append(asyncio.create_task(self._host_mgr_conn_client.run()))
            await self._host_mgr_conn_client.wait_for_ready()
        await self._sw_conn_client.wait_for_ready()
        await self._root_port_device.wait_for_ready()
        await self._change_status_to_running()
        await asyncio.gather(*tasks)

    async def _stop(self):
        tasks = [
            asyncio.create_task(self._sw_conn_client.stop()),
            asyncio.create_task(self._root_port_device.stop()),
        ]
        if self._hm_mode:
            tasks.append(asyncio.create_task(self._host_mgr_conn_client.stop()))
        await asyncio.gather(*tasks)
