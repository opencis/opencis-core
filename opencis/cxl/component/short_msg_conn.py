"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from asyncio import (
    Event,
    StreamReader,
    StreamWriter,
    Task,
    create_task,
    gather,
    start_server,
    open_connection,
    Lock,
)
import asyncio
from asyncio.exceptions import CancelledError
from enum import Enum
from typing import Callable

from opencis.util.component import RunnableComponent
from opencis.util.logger import logger


class ShortMsgBase(Enum):
    @property
    def real_val(self):
        return self.value


class ShortMsgConn(RunnableComponent):
    _msg_to_interrupt_event: dict[int, dict[ShortMsgBase, Callable]]
    _callbacks: list[Callable]
    _server_task: Task

    def __init__(
        self,
        device_name,
        addr: str = "0.0.0.0",
        port: int = 9050,
        server: bool = False,
        device_id: int = 0,
        msg_width: int = 2,
        msg_type=ShortMsgBase,
    ):
        super().__init__(f"{device_name}:ShortMsgConn")
        self._addr = addr
        self._port = port
        self._msg_width = msg_width + 1  # 1 extra byte for sending device ID
        self._callbacks = []
        self._msg_to_interrupt_event = {}
        self._general_interrupt_event = {}
        self._server = server
        self._connections: dict[int, tuple[StreamReader, StreamWriter]] = {}
        self._tasks: list[Task] = []
        self._msg_handlers: list[Task] = []
        self._lock = Lock()
        self._end_signal = Event()
        self._reader_id = {}
        self._writer_id = {}
        self._device_id = device_id
        self._run_status = False
        self._msg_tasks: list[Task] = []
        self._msg_type = msg_type

    def register_interrupt_handler(
        self, short_msg: ShortMsgBase, msg_recv_cb: Callable, dev_id: int = 0
    ):
        """
        Registers a callback on the arrival of a specific message.
        dev_id will be locked to 0 for a client.
        """

        device_name = f"device {dev_id}"
        if not self._server:
            dev_id = 0
            device_name = "host"

        async def _callback(dev_id):
            await msg_recv_cb(dev_id)

        cb_func = _callback
        logger.debug(
            self._create_message(
                f"Registering callback for ShortMsg {short_msg.name} for remote {device_name}"
            )
        )
        if dev_id not in self._msg_to_interrupt_event:
            self._msg_to_interrupt_event[dev_id] = {}
        self._msg_to_interrupt_event[dev_id][short_msg] = cb_func

    def register_general_handler(
        self, short_msg: ShortMsgBase, msg_recv_cb: Callable, persistent: bool = True
    ):
        """
        Registers a callback on the arrival of a specific interrupt.
        Handlers registered here will be triggered disregard of the device.
        """

        async def _callback(dev_id, data):
            await msg_recv_cb(dev_id, data)

        cb_func = _callback
        logger.debug(
            self._create_message(f"Registering a general interrupt for ShortMsg {short_msg.name}")
        )
        self._general_interrupt_event[short_msg] = (cb_func, persistent)

    async def _msg_handler(self, reader: StreamReader, _: StreamWriter):
        this_dev_name = f"Device {self._device_id}"
        if self._server:
            this_dev_name = "Host"
        logger.debug(self._create_message(f"{this_dev_name}: Creating ShortMsg handler"))
        while True:
            if not self._run_status:
                logger.debug(self._create_message(f"{this_dev_name} _msg_handler exiting"))
                return

            msg = await reader.readexactly(self._msg_width)
            if not msg:
                logger.debug(self._create_message(f"{this_dev_name} ShortMsg connection broken"))
                return
            msg_int = int.from_bytes(msg)
            remote_dev_id = msg_int & 0xFF
            remote_dev_name = f"device: {remote_dev_id}"
            if not self._server:
                remote_dev_id = 0
                remote_dev_name = "host"

            msg_num = msg_int >> 8
            msg = self._msg_type(msg_num)
            if remote_dev_id not in self._msg_to_interrupt_event:
                if msg not in self._general_interrupt_event:
                    raise RuntimeError(
                        f"ShortMsg: {msg} is not registered for remote {remote_dev_name}"
                    )
                func = self._general_interrupt_event[msg][0]
                persistent = self._general_interrupt_event[msg][1]
                if not persistent:
                    del self._general_interrupt_event[msg]
                t = create_task(func(remote_dev_id, msg))
                self._msg_tasks.append(t)
                continue

            if msg not in self._msg_to_interrupt_event[remote_dev_id]:
                raise RuntimeError(f"Invalid ShortMsg: {msg} for remote {remote_dev_name}")

            t = create_task(self._msg_to_interrupt_event[remote_dev_id][msg](remote_dev_id))
            self._msg_tasks.append(t)
            logger.debug(
                self._create_message(
                    f"ShortMsg handled for {msg.name} from remote {remote_dev_name}"
                )
            )

    async def _create_server(self):
        self._run_status = True

        async def _new_conn(reader: StreamReader, writer: StreamWriter):
            remote_dev_id = await reader.readexactly(16)
            remote_dev_id_int = int.from_bytes(remote_dev_id, "little")
            self._connections[remote_dev_id_int] = (reader, writer)
            self._msg_handlers.append(create_task(self._msg_handler(reader, writer)))

        server = await start_server(_new_conn, self._addr, self._port, limit=2)
        logger.debug(self._create_message(f"Starting ShortMsg server on {self._addr}:{self._port}"))
        return server

    async def send_irq_request(self, request: ShortMsgBase, device: int = 0):
        """
        Sends an ShortMsg request as the client.
        """
        info = f"host sending to device {device}"
        if not self._server:
            info = f"device {self._device_id} sending to host"
        logger.debug(self._create_message(info))
        _, writer = self._connections[device]
        val_w_dev_id = request.real_val << 8 | self._device_id
        writer.write(val_w_dev_id.to_bytes(length=self._msg_width))
        await writer.drain()

    async def start_connection(self):
        reader, writer = await open_connection(self._addr, self._port)
        writer.write(int.to_bytes(self._device_id, 16, "little"))
        await writer.drain()
        self._connections[0] = (reader, writer)
        self._run_status = True

        self._msg_handlers.append(create_task(self._msg_handler(reader, writer)))

    def num_connections(self):
        return len(self._connections.items())

    async def shutdown(self):
        self._run_status = False

    async def _run(self):
        try:
            if self._server:
                server = await self._create_server()
                self._server_task = create_task(server.serve_forever())
                while not server.is_serving():
                    await asyncio.sleep(0.1)
                self._tasks.append(self._server_task)
            else:
                pass
            await self._change_status_to_running()
            self._tasks.append(create_task(self._end_signal.wait()))

            await gather(*self._tasks)
        except CancelledError:
            logger.info(self._create_message("ShortMsg enable listener stopped"))
            for task in self._msg_tasks:
                task.cancel()
            logger.info(self._create_message("All ShortMsg tasks cancelled"))

    async def _stop(self):
        logger.debug(self._create_message("ShortMsg Manager Stopping"))
        for task in self._msg_tasks:
            task.cancel()
        self._end_signal.set()
        for task in self._tasks:
            task.cancel()
        logger.debug(self._create_message("ShortMsg tasks cancelled"))
        for handler in self._msg_handlers:
            handler.cancel()
        logger.debug(self._create_message("ShortMsg handlers cancelled"))
