"""
 Copyright (c) 2024, Eeum, Inc.

 This software is licensed under the terms of the Revised BSD License.
 See LICENSE for details.
"""

import asyncio
import json
from typing import Dict, Any, Callable
import jsonrpcclient
import jsonrpcserver
from jsonrpcserver.result import ERROR_INTERNAL_ERROR
import websockets
from websockets import WebSocketClientProtocol

from opencis.cxl.transport.transaction import CXL_MEM_M2SBIRSP_OPCODE
from opencis.util.logger import logger
from opencis.util.component import RunnableComponent


class Result:
    def __new__(cls, res: Any):
        if isinstance(res, str):
            return jsonrpcserver.Error(ERROR_INTERNAL_ERROR, res)
        return jsonrpcserver.Success({"result": res})


class HostConnServer(RunnableComponent):
    def __init__(
        self,
        host: str,
        port: int,
        set_host_conn_callback: Callable[[int, WebSocketClientProtocol], None] = None,
    ):
        super().__init__()
        self._host = host
        self._port = port
        self._set_host_conn_callback = set_host_conn_callback
        self._fut = None
        self._host_server = None
        self._methods = {
            "HOST_INIT": self._host_init,
        }

    async def _host_init(self, port: int) -> jsonrpcserver.Result:
        logger.info(self._create_message(f"Connection opened by CxlHost:Port{port}"))
        return jsonrpcserver.Success({"port": port})

    async def _serve(self, ws: WebSocketClientProtocol):
        cmd = await ws.recv()
        resp = await jsonrpcserver.async_dispatch(cmd, methods=self._methods)
        port = json.loads(resp)["result"]["port"]
        await self._set_host_conn_callback(port, ws)
        await ws.send(resp)
        await ws.wait_closed()

    async def serve(self):
        self._fut = asyncio.Future()
        self._host_server = await websockets.serve(self._serve, self._host, self._port)
        await self._change_status_to_running()
        res = await self._fut
        logger.debug(self._create_message(f"{res}"))

    async def _run(self):
        tasks = [
            asyncio.create_task(self.serve()),
        ]
        await asyncio.gather(*tasks)

    async def _stop(self):
        self._fut.set_result("Host Done")
        self._host_server.close()
        await self._host_server.wait_closed()


class UtilConnServer(RunnableComponent):
    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 8400,
        get_host_conn_callback: Callable[[int], WebSocketClientProtocol] = None,
    ):
        super().__init__()
        self._server_uri = f"ws://{host}:{port}"
        self._host = host
        self._port = port
        self._util_methods = {
            "UTIL_CXL_HOST_READ": self._util_cxl_host_read,
            "UTIL_CXL_HOST_WRITE": self._util_cxl_host_write,
        }
        self._fut = None
        self._util_server = None
        self._get_host_conn_callback = get_host_conn_callback

    async def _process_cmd(self, cmd: str, port: int) -> jsonrpcserver.Result:
        ws = await self._get_host_conn_callback(port)
        if ws is None:
            return jsonrpcserver.Error(
                ERROR_INTERNAL_ERROR, f"Invalid Params: Port{port} is not a USP"
            )
        logger.debug(self._create_message(f"cmd: {cmd}"))
        await ws.send(cmd)
        resp = jsonrpcclient.parse_json(await ws.recv())
        logger.debug(self._create_message(f"resp: {resp}"))
        match resp:
            case jsonrpcclient.Ok(result, _):
                return jsonrpcserver.Success(result)
            case jsonrpcclient.Error(code, message, data, _):
                return jsonrpcserver.Error(code, message, data)

    async def _util_cxl_host_write(self, port: int, addr: int, data: int) -> jsonrpcserver.Result:
        cmd = jsonrpcclient.request_json("HOST_CXL_HOST_WRITE", params={"addr": addr, "data": data})
        return await self._process_cmd(cmd, port)

    async def _util_cxl_host_read(self, port: int, addr: int) -> jsonrpcserver.Result:
        cmd = jsonrpcclient.request_json("HOST_CXL_HOST_READ", params={"addr": addr})
        return await self._process_cmd(cmd, port)

    async def _serve(self, ws):
        cmd = await ws.recv()
        resp = await jsonrpcserver.async_dispatch(cmd, methods=self._util_methods)
        await ws.send(resp)

    async def serve(self):
        self._fut = asyncio.Future()
        self._util_server = await websockets.serve(self._serve, self._host, self._port)
        await self._change_status_to_running()
        res = await self._fut
        logger.debug(self._create_message(f"{res}"))

    async def _run(self):
        tasks = [
            asyncio.create_task(self.serve()),
        ]
        await asyncio.gather(*tasks)

    async def _stop(self):
        self._fut.set_result("Host Done")
        self._util_server.close()
        await self._util_server.wait_closed()


class HostManagerConnClient(RunnableComponent):
    def __init__(
        self,
        port_index: int,
        host: str = "0.0.0.0",
        port: int = 8300,
        methods: Dict = None,
    ):
        super().__init__(f"Port{port_index}")
        self._port_index = port_index
        self._server_uri = f"ws://{host}:{port}"
        self._methods = methods
        self._event = asyncio.Event()
        self._ws = None

    async def _open_connection(self, port: int):
        logger.info(self._create_message("Connecting to HostManager"))
        while True:
            try:
                # send + receive init message from CxlHostManager
                ws = await websockets.connect(self._server_uri)
                cmd = jsonrpcclient.request_json("HOST_INIT", params={"port": port})
                await ws.send(str(cmd))
                resp = await ws.recv()
                resp_port = json.loads(resp)["result"]["port"]
                assert resp_port == port
                self._ws = ws
                self._event.set()
                break
            except OSError as _:
                logger.error(self._create_message("HostManager not ready. Reconnecting..."))
                await asyncio.sleep(0.2)

        # keep the connection alive and receive / process messages from CxlHostManager
        try:
            while True:
                cmd = await self._ws.recv()
                logger.debug(self._create_message(f"received cmd: {cmd}"))
                resp = await jsonrpcserver.async_dispatch(cmd, methods=self._methods)
                logger.debug(self._create_message(f"sending resp: {resp}"))
                await self._ws.send(resp)
        except websockets.exceptions.ConnectionClosed as _:
            logger.info(self._create_message("Disconnected from HostManager"))

    async def _close_connection(self):
        await self._ws.close()

    async def _run(self):
        tasks = [
            asyncio.create_task(self._open_connection(self._port_index)),
        ]
        await self._event.wait()
        await self._change_status_to_running()
        await asyncio.gather(*tasks)

    async def _stop(self):
        await self._close_connection()
