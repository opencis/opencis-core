"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

# pylint: disable=unused-import
from asyncio import CancelledError, gather, create_task, Event, sleep
from typing import Awaitable, Dict, List, Tuple, cast, Callable
import struct
import pyshark

from tqdm.auto import tqdm

from opencis.util.logger import logger
from opencis.cxl.device.cxl_type1_device import CxlType1Device, CxlType1DeviceConfig
from opencis.cxl.component.irq_manager import Irq, IrqManager
from opencis.cxl.component.switch_connection_client import SwitchConnectionClient
from opencis.cxl.component.common import CXL_COMPONENT_TYPE
from opencis.util.component import RunnableComponent
import nest_asyncio

nest_asyncio.apply()

START_ADDR = 0x1800


class CustomList:
    def __init__(self, numElmts: int = None, offset=0x0, numWidth=8):
        self._numElmts = numElmts
        self._numWidth = numWidth
        self._offset = offset
        self._read_func: Callable[[int, int], Awaitable[bytes]] = None
        self._write_func: Callable[[int, int, int], Awaitable[None]] = None
        self._format_char = "<q" if self._numWidth == 4 else "<i"

    def getAddr(self, i: int) -> int:
        assert i < self._numElmts
        return (i * self._numWidth) + self._offset

    def getnumWidth(self) -> int:
        return self._numWidth

    def setNumElmts(self, numElmts) -> None:
        self._numElmts = numElmts

    def getNumElmts(self) -> int:
        return self._numElmts

    def getEndingAddr(self) -> int:
        return self.getAddr(self._numElmts - 1) + self._numWidth

    async def __getitem__(self, i: int) -> int:
        assert i < self._numElmts
        addr = self.getAddr(i)
        addr_remainder = addr % 64
        cache_start = addr - addr_remainder
        cache_line = await self._read_func(cache_start, 64)
        data_bytes = cache_line[addr_remainder : addr_remainder + self._numWidth]
        unpacked_val = int.from_bytes(data_bytes, "little")
        return unpacked_val

    async def setitem(self, i: int, value: int) -> None:
        assert i < self._numElmts
        addr = self.getAddr(i)
        # print("SetItem 1")
        # addr_remainder = addr % 64
        # cache_start = addr - addr_remainder
        # cache_line = await self._read_func(cache_start, 64)
        # print("SetItem 2")
        # value_bytes = struct.pack(self._format_char, value)
        value_bytes = int.to_bytes(value, self._numWidth, "little")
        # new_cache_line = (
        #     cache_line[0:addr_remainder]
        #     + value_bytes
        #     + cache_line[addr_remainder + self._numWidth :]
        # )
        # final_value = int.from_bytes(new_cache_line, "little")
        # print("SetItem 3")
        final_value = int.from_bytes(value_bytes, "little")
        # print("SetItem 4")
        await self._write_func(addr, self._numWidth, final_value)
        # print("SetItem 5")

    async def host_setitem(self, i: int, value: int) -> None:
        if not i < self._numElmts:
            print(f"Error: user {i} is not smaller than num elements {self._numElmts}!")
        assert i < self._numElmts
        addr = self.getAddr(i)
        addr_remainder = addr % 64
        cache_start = addr - addr_remainder
        cache_line = await self._read_func(cache_start, 64)
        value_bytes = int.to_bytes(value, self._numWidth, "little")
        # value_bytes = struct.pack(self._format_char, value)
        new_cache_line = (
            cache_line[0:addr_remainder]
            + value_bytes
            + cache_line[addr_remainder + self._numWidth :]
        )
        final_value = int.from_bytes(new_cache_line, "little")
        await self._write_func(addr, 64, final_value)
        # print("SetItem 5")

    def setReadFunc(self, f: Callable[[int, int], Awaitable[bytes]]):
        self._read_func = f

    def setWriteFunc(self, f: Callable[[int, int, int], Awaitable[None]]):
        self._write_func = f

    async def getAllElements(self) -> List[float]:
        results = []
        for i in range(self._numElmts):
            val = await self.__getitem__(i)
            results.append(val)
        return results


class MyType1Accelerator(RunnableComponent):
    """
    This demo app uses CXL.cache to read metadata from the host memory, uses the
    metadata to train an image classification model, then finally uses CXL.cache
    to rewrite the training results to the host memory.

    The demo app also supports host "validation": the device can copy an image
    from some predefined address in host memory, run the trained model on the
    retrieved image, and write the class probabilities back to the host memory.
    """

    def __init__(
        self,
        port_index: int,
        host: str = "0.0.0.0",
        port: int = 8000,
        irq_port: int = 8500,
        device_id: int = 0,
        total_devs: int = 1,
    ):
        label = f"Port{port_index}"
        super().__init__(label)

        self._total_devs = total_devs

        self._sw_conn_client = SwitchConnectionClient(
            port_index, CXL_COMPONENT_TYPE.T1, host=host, port=port
        )
        self._cxl_type1_device = CxlType1Device(
            CxlType1DeviceConfig(
                transport_connection=self._sw_conn_client.get_cxl_connection(),
                device_name=label,
                device_id=device_id,
                cache_line_count=[8, 32],
            )
        )
        self._wait_tasks = []
        self._device_id = device_id
        self._count = 0

        self._twitter_user_mapping: Dict[int, List[int]] = {}
        self._damping_factor = 0.85

        self._irq_manager = IrqManager(
            addr="127.0.0.1", port=irq_port, device_name=label, device_id=device_id
        )

        self._stop_signal = Event()
        self._stop_flag = False

        self._processor = pyshark.InMemCapture()
        self._packet_data = CustomList(2, START_ADDR)
        self._packet_data.setReadFunc(self._cxl_type1_device.cxl_cache_read)
        self._packet_data.setWriteFunc(self._cxl_type1_device.cxl_partial_write)

        self._irq_manager.register_interrupt_handler(Irq.HOST_SENT, self._handle_packet)
        self._irq_manager.register_interrupt_handler(Irq.HOST_READY, self._stop)

    async def _handle_packet(self, _):
        packet_addr = await self._packet_data[0]
        packet_len = await self._packet_data[1]
        padded_len = (((packet_len - 1) // 64) + 1) * 64
        # if self._count > 3000:
        #     print(
        #         f"Received addr 0x{packet_addr:08x}, len 0x{packet_len:08x}, padded_len 0x{padded_len:08x}"
        #     )
        # if packet_addr == 0:
        #     exit()

        raw_packet_padded = await self._cxl_type1_device.cxl_cache_read(packet_addr, padded_len)
        raw_packet = raw_packet_padded[0:packet_len]
        data = self._processor.parse_packet(raw_packet)
        opencis_raw = data.opencis.raw_mode.to_bytes()
        # Read packet
        self._count += 1
        await self._irq_manager.send_irq_request(Irq.ACCEL_TRAINING_FINISHED)

    async def _run(self):
        tasks = [
            create_task(self._sw_conn_client.run()),
            create_task(self._cxl_type1_device.run()),
            create_task(self._irq_manager.run()),
            create_task(self._stop_signal.wait()),
        ]

        self._wait_tasks = [
            create_task(self._sw_conn_client.wait_for_ready()),
            create_task(self._cxl_type1_device.wait_for_ready()),
            create_task(self._irq_manager.wait_for_ready()),
            create_task(self._irq_manager.start_connection()),
        ]
        await self._change_status_to_running()
        await gather(*tasks)

    async def _stop(self, _):
        print("Device stopping")
        self._stop_flag = True
        for task in self._wait_tasks:
            task.cancel()
        self._stop_signal.set()
        tasks = [
            create_task(self._sw_conn_client.stop()),
            create_task(self._cxl_type1_device.stop()),
            create_task(self._irq_manager.stop()),
        ]
        await gather(*tasks)
