"""
 Copyright (c) 2024, Eeum, Inc.

 This software is licensed under the terms of the Revised BSD License.
 See LICENSE for details.
"""

import asyncio
import jsonrpcclient
from jsonrpcclient import parse_json, request_json
import websockets
from websockets import WebSocketClientProtocol


from opencis.cxl.transport.transaction import CXL_MEM_M2SBIRSP_OPCODE
from opencis.util.logger import logger
from opencis.util.component import RunnableComponent
from opencis.cxl.component.host_manager_conn import HostConnServer, UtilConnServer


class CxlHostManager(RunnableComponent):
    def __init__(
        self,
        host_host: str = "0.0.0.0",
        host_port: int = 8300,
        util_host: str = "0.0.0.0",
        util_port: int = 8400,
    ):
        super().__init__()
        self._host_connections = {}
        self._host_conn_server = HostConnServer(host_host, host_port, self._set_host_conn_callback)
        self._util_conn_server = UtilConnServer(util_host, util_port, self._get_host_conn_callback)

    async def _set_host_conn_callback(self, port: int, ws) -> WebSocketClientProtocol:
        self._host_connections[port] = ws

    async def _get_host_conn_callback(self, port: int) -> WebSocketClientProtocol:
        return self._host_connections.get(port)

    async def _run(self):
        tasks = [
            asyncio.create_task(self._host_conn_server.run()),
            asyncio.create_task(self._util_conn_server.run()),
        ]
        wait_tasks = [
            asyncio.create_task(self._host_conn_server.wait_for_ready()),
            asyncio.create_task(self._util_conn_server.wait_for_ready()),
        ]
        await asyncio.gather(*wait_tasks)
        await self._change_status_to_running()
        await asyncio.gather(*tasks)

    async def _stop(self):
        tasks = [
            asyncio.create_task(self._host_conn_server.stop()),
            asyncio.create_task(self._util_conn_server.stop()),
        ]
        await asyncio.gather(*tasks)


class CxlHostUtilClient:
    def __init__(self, host: str = "0.0.0.0", port: int = 8400):
        self._uri = f"ws://{host}:{port}"

    async def _process_cmd(self, cmd: str) -> str:
        async with websockets.connect(self._uri) as ws:
            logger.debug(f"Issuing: {cmd}")
            await ws.send(str(cmd))
            resp = await ws.recv()
            logger.debug(f"Received: {resp}")
            resp = parse_json(resp)
            match resp:
                case jsonrpcclient.Ok(result, _):
                    return result["result"]
                case jsonrpcclient.Error(_, err, _, _):
                    raise Exception(f"{err}")

    async def cxl_mem_write(self, port: int, addr: int, data: int) -> str:
        logger.info(f"CXL-Host[Port{port}]: Start CXL.mem Write: addr=0x{addr:x} data=0x{data:x}")
        cmd = request_json("UTIL_CXL_HOST_WRITE", params={"port": port, "addr": addr, "data": data})
        return await self._process_cmd(cmd)

    async def cxl_mem_read(self, port: int, addr: int) -> str:
        logger.info(f"CXL-Host[Port{port}]: Start CXL.mem Read: addr=0x{addr:x}")
        cmd = request_json("UTIL_CXL_HOST_READ", params={"port": port, "addr": addr})
        return await self._process_cmd(cmd)

    async def cxl_mem_birsp(
        self, port: int, opcode: CXL_MEM_M2SBIRSP_OPCODE, bi_id: int = 0, bi_tag: int = 0
    ) -> str:
        logger.info(
            f"CXL-Host[Port{port}]: Start CXL.mem BIRsp: opcode: 0x{opcode:x}"
            f" id: {bi_id}, tag: {bi_tag}"
        )
        cmd = request_json(
            "UTIL_CXL_MEM_BIRSP",
            params={"port": port, "opcode": opcode, "bi_id": bi_id, "bi_tag": bi_tag},
        )
        return await self._process_cmd(cmd)
