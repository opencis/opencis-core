"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

# pylint: disable=unused-import
from asyncio import CancelledError, gather, create_task, Event, sleep
import traceback
from typing import Awaitable, Dict, List, Tuple, cast, Callable
import shutil
import struct

from tqdm.auto import tqdm

from opencis.util.logger import logger
from opencis.cxl.device.cxl_type1_device import CxlType1Device, CxlType1DeviceConfig
from opencis.cxl.component.irq_manager import Irq, IrqManager
from opencis.cxl.component.switch_connection_client import SwitchConnectionClient
from opencis.cxl.component.common import CXL_COMPONENT_TYPE
from opencis.util.component import RunnableComponent

# MAX_ITER should be an even number
# so the final result will be at the first buffer
MAX_ITER = 4


class CustomList:
    def __init__(self, numElmts: int = None, offset=0x0, numWidth=8):
        self._numElmts = numElmts
        self._numWidth = numWidth
        self._offset = offset
        self._read_func: Callable[[int, int], Awaitable[bytes]] = None
        self._write_func: Callable[[int, int, int], Awaitable[None]] = None
        self._format_char = "<f" if self._numWidth == 4 else "<d"

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

    def getAlignedEndingAddr(self) -> int:
        endingAddr = self.getEndingAddr()
        endingAddr = (((endingAddr - 1) // 64) + 1) * 64
        return endingAddr

    async def __getitem__(self, i: int) -> float:
        assert i < self._numElmts
        addr = self.getAddr(i)
        addr_remainder = addr % 64
        cache_start = addr - addr_remainder
        cache_line = await self._read_func(cache_start, 64)
        data_bytes = cache_line[addr_remainder : addr_remainder + self._numWidth]
        unpacked_val: float = struct.unpack(self._format_char, data_bytes)[0]
        return unpacked_val

    async def setitem(self, i: int, value: float) -> None:
        assert i < self._numElmts
        addr = self.getAddr(i)
        # print("SetItem 1")
        # addr_remainder = addr % 64
        # cache_start = addr - addr_remainder
        # cache_line = await self._read_func(cache_start, 64)
        # print("SetItem 2")
        value_bytes = struct.pack(self._format_char, value)
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

    async def host_setitem(self, i: int, value: float) -> None:
        if not i < self._numElmts:
            print(f"Error: user {i} is not smaller than num elements {self._numElmts}!")
        assert i < self._numElmts
        addr = self.getAddr(i)
        addr_remainder = addr % 64
        cache_start = addr - addr_remainder
        cache_line = await self._read_func(cache_start, 64)
        value_bytes = struct.pack(self._format_char, value)
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
        cache_friendly: int = 0,
        jacobi: int = 0,
        loop_unroll: bool = False,
    ):
        label = f"Port{port_index}"
        super().__init__(label)
        self._train_data_path = "./links-anon-sampled-condensed-50000.txt"
        # self._train_data_path = "./links-anon-4.txt"
        # self._train_data_path = "./links-anon-sampled-condensed-short.txt"

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

        self._twitter_user_mapping: Dict[int, List[int]] = {}
        self._damping_factor = 0.85

        self._irq_manager = IrqManager(
            addr="127.0.0.1", port=irq_port, device_name=label, device_id=device_id
        )

        self._stop_signal = Event()
        self._stop_flag = False

        self._iter_go_signal = Event()
        self._iter_go_signal.set()

        self._jacobi = jacobi
        self._loop_unroll = loop_unroll

        self._cache_friendly = cache_friendly
        self._irq_manager.register_interrupt_handler(Irq.HOST_SENT, self.set_go_signal)
        if self._loop_unroll:
            self._irq_manager.register_interrupt_handler(Irq.HOST_READY, self._run_app_unroll)
        else:
            self._irq_manager.register_interrupt_handler(Irq.HOST_READY, self._run_app_normal)

    async def set_go_signal(self, _):
        self._iter_go_signal.set()

    def set_stop_flag(self):
        self._stop_flag = True

    def _read_file(self):
        max_id = 0
        with open(self._train_data_path) as f:
            lines = f.readlines()
            with tqdm(
                total=len(lines),
                desc=f"Dev File Read Process",
                position=self._device_id,
                leave=False,
            ) as pbar:
                for l in lines:
                    l = l.strip()
                    ls = l.split(" ")
                    idFrom = int(ls[0])
                    idTo = int(ls[1])
                    if idFrom > max_id:
                        max_id = idFrom
                    if idTo > max_id:
                        max_id = idTo
                    if idFrom not in self._twitter_user_mapping:
                        self._twitter_user_mapping[idFrom] = [idTo]
                    else:
                        self._twitter_user_mapping[idFrom].append(idTo)
                    pbar.update()
        max_id += 1  # id may start from 0
        return max_id

    async def _run_app_unroll(self, _):
        # Loop unrolling
        try:
            logger.info(f"Cache friendly level: {self._cache_friendly}")
            logger.info(f"Method: {"Jacobi" if self._jacobi else "Gauss-Seigel"}")
            logger.info(f"Dev {self._device_id} Reading file...")
            total_users = self._read_file()
            old_dict = CustomList(total_users, 0x1800)
            old_dict.setNumElmts(total_users)
            print(
                f"Dev {self._device_id} Mapping created. Total users: {total_users}, Memory required: {total_users * old_dict.getnumWidth()} bytes."
            )
            corpus = self._twitter_user_mapping
            # print(corpus)
            old_dict = CustomList(total_users, 0x1800)
            old_dict.setReadFunc(self._cxl_type1_device.cxl_cache_read)
            old_dict.setWriteFunc(self._cxl_type1_device.cxl_partial_write)

            new_dict = old_dict
            # Jacobi method uses two arrays and exchange the two arrays after each iteration
            # Gauss-Seigel method uses one single array and do in-place updates
            if self._jacobi:
                new_dict = CustomList(total_users, old_dict.getAlignedEndingAddr())
                new_dict.setReadFunc(self._cxl_type1_device.cxl_cache_read)
                new_dict.setWriteFunc(self._cxl_type1_device.cxl_partial_write)
            logger.info(f"Dev {self._device_id} starting...")

            iteration_count = 0

            # repeatedly calculating new rank values basing on all of the current rank values
            with tqdm(
                total=MAX_ITER,
                desc=f"Dev {self._device_id} Iteration",
                position=2 * self._device_id,
                leave=False,
            ) as pbar:
                while iteration_count < MAX_ITER:
                    with tqdm(
                        total=total_users,
                        desc=f"Iteration Progress",
                        position=(2 * self._device_id) + 1,
                        leave=False,
                    ) as pbar2:
                        if iteration_count != 0:
                            await self._iter_go_signal.wait()
                        iteration_count += 1
                        for page in range(0, total_users, 8):
                            # print(f"Dev {self._device_id} now page {page}")
                            if self._cache_friendly == 1:
                                if (
                                    old_dict.getAddr(page) // 64
                                ) % self._total_devs != self._device_id:
                                    # print(f"Dev {self._device_id} skipping {page}")
                                    await sleep(0)
                                    pbar2.update(8)
                                    continue
                            # elif self._cache_friendly == 0:
                            #     if page % self._total_devs != self._device_id:
                            #         await sleep(0)
                            #         pbar2.update()
                            #         continue
                            # else:
                            #     raise Exception("Illegal cache friendly level! (can be 0, 1, or 2)")

                            temp = [0, 0, 0, 0, 0, 0, 0, 0]

                            for linking_page in range(total_users):
                                # check if page links to our page
                                for i in range(8):
                                    if page + i < total_users:
                                        if (
                                            linking_page in corpus
                                            and page + i in corpus[linking_page]
                                        ):
                                            temp[i] += await old_dict[linking_page] / len(
                                                corpus[linking_page]
                                            )
                                        # if page has no links, interpret it as having one link for every other page
                                        if (
                                            linking_page not in corpus
                                            or len(corpus[linking_page]) == 0
                                        ):
                                            temp[i] += (await old_dict[linking_page]) / total_users
                                await sleep(0)
                            for i in range(8):
                                if page + i < total_users:
                                    temp[i] *= self._damping_factor
                                    temp[i] += (1 - self._damping_factor) / total_users
                                    await new_dict.setitem(page + i, temp[i])
                            pbar2.update(8)
                        new_dict_temp = new_dict
                        new_dict = old_dict
                        old_dict = new_dict_temp

                    pbar.update()
                    await self._irq_manager.send_irq_request(Irq.ACCEL_TRAINING_FINISHED)
                    self._iter_go_signal.clear()
                    await sleep(0)
            await self._irq_manager.send_irq_request(Irq.ACCEL_VALIDATION_FINISHED)
        except CancelledError:
            logger.error(self._create_message(f"Runapp Cancelled: {traceback.format_exc()}"))
            return
        except Exception as e:
            print(e)

    async def _run_app_normal(self, _):
        # Normal
        try:
            logger.info(f"Cache friendly level: {self._cache_friendly}")
            logger.info(f"Method: {"Jacobi" if self._jacobi else "Gauss-Seigel"}")
            logger.info(f"Dev {self._device_id} Reading file...")
            total_users = self._read_file()
            old_dict = CustomList(total_users, 0x1800)
            old_dict.setNumElmts(total_users)
            print(
                f"Dev {self._device_id} Mapping created. Total users: {total_users}, Memory required: {total_users * old_dict.getnumWidth()} bytes."
            )
            corpus = self._twitter_user_mapping
            # print(corpus)
            old_dict = CustomList(total_users, 0x1800)
            old_dict.setReadFunc(self._cxl_type1_device.cxl_cache_read)
            old_dict.setWriteFunc(self._cxl_type1_device.cxl_partial_write)

            new_dict = old_dict
            # Jacobi method uses two arrays and exchange the two arrays after each iteration
            # Gauss-Seigel method uses one single array and do in-place updates
            if self._jacobi:
                new_dict = CustomList(total_users, old_dict.getAlignedEndingAddr())
                new_dict.setReadFunc(self._cxl_type1_device.cxl_cache_read)
                new_dict.setWriteFunc(self._cxl_type1_device.cxl_partial_write)
            logger.info(f"Dev {self._device_id} starting...")

            iteration_count = 0
            # MAX_ITER should be an even number
            # so the final result will be at the first buffer

            # repeatedly calculating new rank values basing on all of the current rank values
            with tqdm(
                total=MAX_ITER,
                desc=f"Dev {self._device_id} Iteration",
                position=2 * self._device_id,
                leave=False,
            ) as pbar:
                while iteration_count < MAX_ITER:
                    with tqdm(
                        total=total_users,
                        desc=f"Iteration Progress",
                        position=(2 * self._device_id) + 1,
                        leave=False,
                    ) as pbar2:
                        if iteration_count != 0:
                            await self._iter_go_signal.wait()
                        iteration_count += 1
                        for page in range(total_users):
                            if self._cache_friendly == 1:
                                if (
                                    old_dict.getAddr(page) // 64
                                ) % self._total_devs != self._device_id:
                                    await sleep(0)
                                    pbar2.update()
                                    continue
                            elif self._cache_friendly == 0:
                                if page % self._total_devs != self._device_id:
                                    await sleep(0)
                                    pbar2.update()
                                    continue
                            else:
                                raise Exception("Illegal cache friendly level! (can be 0, 1, or 2)")
                            temp = 0
                            for linking_page in range(total_users):
                                # check if page links to our page
                                if linking_page in corpus and page in corpus[linking_page]:
                                    temp += await old_dict[linking_page] / len(corpus[linking_page])
                                # if page has no links, interpret it as having one link for every other page
                                if linking_page not in corpus or len(corpus[linking_page]) == 0:
                                    temp += (await old_dict[linking_page]) / total_users
                                await sleep(0)
                            temp *= self._damping_factor
                            temp += (1 - self._damping_factor) / total_users
                            await new_dict.setitem(page, temp)
                            pbar2.update()
                        new_dict_temp = new_dict
                        new_dict = old_dict
                        old_dict = new_dict_temp

                    pbar.update()
                    await self._irq_manager.send_irq_request(Irq.ACCEL_TRAINING_FINISHED)
                    self._iter_go_signal.clear()
                    await sleep(0)
            await self._irq_manager.send_irq_request(Irq.ACCEL_VALIDATION_FINISHED)
        except CancelledError:
            logger.error(self._create_message(f"Runapp Cancelled: {traceback.format_exc()}"))
            return
        except Exception as e:
            print(e)

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

    async def _stop(self):
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
