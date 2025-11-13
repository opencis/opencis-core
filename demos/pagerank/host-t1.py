#!/usr/bin/env python
"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

import asyncio
from dataclasses import dataclass, field
import os
from signal import SIGCONT, SIGINT, SIGIO
import sys
from typing import Dict, List
from tqdm.auto import tqdm

from opencis.util.logger import logger
from opencis.cxl.component.cxl_host import CxlHost, CxlHostConfig
from opencis.cpu import CPU
from opencis.util.number_const import MB
from opencis.cxl.component.cxl_memory_hub import CxlMemoryHub, MEM_ADDR_TYPE
from opencis.cxl.component.irq_manager import Irq
from opencis.drivers.cxl_bus_driver import CxlBusDriver
from opencis.drivers.cxl_mem_driver import CxlMemDriver
from opencis.drivers.pci_bus_driver import PciBusDriver
from opencis.apps.pagerank import CustomList, CustomListInt


# pylint: disable=global-statement, duplicate-code
@dataclass
class ImageClassificationConfigs:
    train_data_path: str
    accel_count: int
    samples_from_each_category: int
    pci_cfg_base_addr: int = 0x10000000
    pci_cfg_size = 0x10000000  # assuming bus bits n = 8
    pci_mmio_base_addr: int = 0xFE000000
    cxl_hpa_base_addr: int = 0x100000000000
    sys_mem_base_addr: int = 0


@dataclass
class AccelInfo:
    hpa_base_addr: Dict[int, int] = field(default_factory=dict)
    mmio_base_addr: Dict[int, int] = field(default_factory=dict)
    training_done: Dict[int, bool] = field(default_factory=dict)
    one_iter_done: Dict[int, bool] = field(default_factory=dict)
    total_iters_done: int = 0


accel_info = AccelInfo()
host_irq_handler = None
total_samples = 0
validation_results = []
sampled_file_categories = []
cpu: CPU = None
mem_hub: CxlMemoryHub = None
config = None
start_signal = None
stop_signal = None
host = None
host_task = None
START_ADDR = 0x1800
pageRank = CustomList(0, START_ADDR)
pageRankSecondBuffer = CustomList(0, START_ADDR)


async def my_sys_sw_app(**kwargs):
    cxl_memory_hub = kwargs["cxl_memory_hub"]
    pci_cfg_base_addr = config.pci_cfg_base_addr
    pci_mmio_base_addr = config.pci_mmio_base_addr
    cxl_hpa_base_addr = config.cxl_hpa_base_addr
    sys_mem_base_addr = config.sys_mem_base_addr

    global accel_info
    accel_info = AccelInfo()

    # PCI Device
    root_complex = cxl_memory_hub.get_root_complex()
    pci_bus_driver = PciBusDriver(root_complex)
    await pci_bus_driver.init(pci_mmio_base_addr)
    pci_cfg_size = config.pci_cfg_size
    accel_id = 0
    for i, device in enumerate(pci_bus_driver.get_devices()):
        if not device.is_bridge:
            accel_info.mmio_base_addr[accel_id] = device.bars[0].base_address
            accel_id += 1
        cxl_memory_hub.add_mem_range(
            pci_cfg_base_addr + (i * pci_cfg_size), pci_cfg_size, MEM_ADDR_TYPE.CFG
        )
        for bar_info in device.bars:
            if bar_info.base_address == 0:
                continue
            cxl_memory_hub.add_mem_range(bar_info.base_address, bar_info.size, MEM_ADDR_TYPE.MMIO)

    # CXL Device
    cxl_bus_driver = CxlBusDriver(pci_bus_driver, root_complex)
    cxl_mem_driver = CxlMemDriver(cxl_bus_driver, root_complex)
    await cxl_bus_driver.init()
    await cxl_mem_driver.init()
    hpa_base = cxl_hpa_base_addr
    for device in cxl_mem_driver.get_devices():
        size = device.get_memory_size()
        successful = await cxl_mem_driver.attach_single_mem_device(device, hpa_base, size)
        if not successful:
            logger.info(f"[SYS-SW] Failed to attach device {device}")
            continue
    root_complex.set_cache_coh_dev_count(config.accel_count)

    # System Memory
    sys_mem_size = root_complex.get_sys_mem_size()
    cxl_memory_hub.add_mem_range(sys_mem_base_addr, sys_mem_size, MEM_ADDR_TYPE.DRAM)

    for range in cxl_memory_hub.get_memory_ranges():
        logger.info(
            f"[SYS-SW] MemoryRange: base: 0x{range.base_addr:X}, "
            f"size: 0x{range.size:X}, type: {str(range.addr_type)}"
        )

    global host_irq_handler
    host_irq_handler = host.get_irq_manager()


def to_sys_mem_addr(addr: int) -> int:
    return config.sys_mem_base_addr + addr


def to_accel_mmio_addr(dev_id: int, addr: int) -> int:
    return accel_info.mmio_base_addr[dev_id] + addr


async def barrier_one_iter_finished_type1(dev_id: int):
    accel_info.one_iter_done[dev_id] = True
    if len(accel_info.one_iter_done) == config.accel_count:
        accel_info.one_iter_done = {}
        for dev_id in range(config.accel_count):
            await host_irq_handler.send_irq_request(Irq.HOST_SENT, dev_id)


async def check_final_iter_ready(dev_id: int):
    accel_info.training_done[dev_id] = True
    if len(accel_info.training_done) == config.accel_count:
        await check_final_results()


async def check_final_results():
    global pageRank, pageRankSecondBuffer
    print("Done calculating PageRank")
    results = await pageRank.getAllElements()
    print(f"Results sum: {sum(results)}")
    # print(await pageRank.getAllElements())
    # print(await pageRankSecondBuffer.getAllElements())
    stop_signal.set()


def read_file(path):
    mapping: Dict[int, List[int]] = {}
    reverse_mapping: Dict[int, List[int]] = {}
    all_ids: Dict[int, int] = {}
    max_id = 0
    with open(path) as f:
        for l in f.readlines():
            l = l.strip()
            ls = l.split(" ")
            idFrom = int(ls[0])
            idTo = int(ls[1])
            all_ids[idFrom] = 0
            all_ids[idTo] = 0
            if idFrom not in mapping:
                mapping[idFrom] = [idTo]
            else:
                mapping[idFrom].append(idTo)

            if idTo not in reverse_mapping:
                reverse_mapping[idTo] = [idFrom]
            else:
                reverse_mapping[idTo].append(idFrom)
            if idFrom > max_id:
                max_id = idFrom
            if idTo > max_id:
                max_id = idTo
    max_id += 1  # id may start from 0

    final_array: List[int] = []
    final_array.append(0)  # Total number of elements
    final_array.append(len(mapping))  # Total number of elements w/ outgoing edges
    final_array.append(max_id - len(mapping))  # Total number of elements w/o outgoing edges

    # Offset + 3
    for i in mapping.keys():
        final_array.append(i)
    for i in range(max_id):
        if i not in mapping:
            final_array.append(i)

    # Mapping length
    # Offset + Len
    for i in range(max_id):
        if i not in mapping:
            mapping[i] = []
        final_array.append(len(mapping[i]))

    # Reverse Mapping start/end addr
    # Offset + 2xLen
    prev_count = 0
    for i in range(max_id):
        if i not in reverse_mapping:
            reverse_mapping[i] = []
        final_array.append(prev_count + len(reverse_mapping[i]))
        # for out in self._adj_list[i]:
        #     if self._components[out] != self._components[i]:
        #         self._components[out] = self._components[i]

        prev_count += len(reverse_mapping[i])

    # Reverse mapping contents
    # Offset + 3xLen
    for i in range(max_id):
        final_array += reverse_mapping[i]
    final_array[0] = len(final_array)
    return mapping, max_id, final_array


async def my_img_classification_app(**kwargs):
    global cpu, pageRank, pageRankSecondBuffer
    cpu = kwargs["cpu"]

    global mem_hub
    mem_hub = kwargs["cxl_memory_hub"]

    # Pass init-info mem location to the remote using MMIO
    logger.info("Host main process waiting...")
    await start_signal.wait()
    logger.info("Host main process running!")

    corpus, total_users, graph_array = read_file("./links-anon-sampled-condensed-60000.txt")
    # corpus, total_users, graph_array = read_file("./links-anon-4.txt")
    # corpus, total_users, graph_array = read_file("./links-anon-sampled-condensed-5000.txt")

    total_user_info = CustomListInt(16, 0x0)
    total_user_info.setReadFunc(cpu.load_bytes)
    total_user_info.setWriteFunc(cpu.store)
    await total_user_info.host_setitem(0, total_users)

    print(f"Total users: {total_users}")
    pageRank = CustomList(total_users, START_ADDR)
    pageRank.setReadFunc(cpu.load_bytes)
    pageRank.setWriteFunc(cpu.store)
    pageRankSecondBuffer = CustomList(total_users, pageRank.getAlignedEndingAddr())
    pageRankSecondBuffer.setReadFunc(cpu.load_bytes)
    pageRankSecondBuffer.setWriteFunc(cpu.store)

    graph_array_len = len(graph_array)
    graph = CustomListInt(graph_array_len, pageRankSecondBuffer.getAlignedEndingAddr())
    graph.setReadFunc(cpu.load_bytes)
    graph.setWriteFunc(cpu.store)
    print("File finished reading")

    # assigning each page a rank of 1/n, where n is total number of pages in the corpus
    with tqdm(
        total=total_users,
        desc=f"Setting up initial PR array",
        position=0,
        leave=False,
    ) as pbar:
        for i in range(total_users):
            await pageRank.host_setitem(i, 1 / total_users)
            pbar.update()

        for i in range(graph_array_len):
            e = graph_array[i]
            await graph.host_setitem(i, e)
        #     if i % 8 == 7:
        #         await cpu.flush_data(pageRank.getAddr(i - 7), 64)
        # if i % 8 != 7:
        #     await cpu.flush_data(pageRank.getAddr(i - (i % 8)), 64)

    for dev_id in range(config.accel_count):
        host_irq_handler.register_interrupt_handler(
            Irq.ACCEL_TRAINING_FINISHED, barrier_one_iter_finished_type1, dev_id
        )
        host_irq_handler.register_interrupt_handler(
            Irq.ACCEL_VALIDATION_FINISHED, check_final_iter_ready, dev_id
        )
    for dev_id in range(config.accel_count):
        await host_irq_handler.send_irq_request(Irq.HOST_READY, dev_id)

    await stop_signal.wait()


async def shutdown(signame=None):
    # pylint: disable=unused-argument
    try:
        stop_tasks = [
            asyncio.create_task(host.stop()),
        ]
        await asyncio.gather(*stop_tasks, return_exceptions=True)
        host_task.cancel()
    except Exception as exc:
        print("[HOST]", exc.__traceback__)
    finally:
        os._exit(0)


async def run_demo(signame=None):
    # pylint: disable=unused-argument
    start_signal.set()
    await stop_signal.wait()
    os.kill(os.getppid(), SIGINT)


async def main():
    sw_portno = int(sys.argv[1])
    accel_count = int(sys.argv[2])
    train_data_path = sys.argv[3] if len(sys.argv) > 3 else None

    global config
    config = ImageClassificationConfigs(
        train_data_path=train_data_path,
        accel_count=accel_count,
        samples_from_each_category=1,
        pci_cfg_base_addr=0x10000000,
        pci_mmio_base_addr=0xFE000000,
        cxl_hpa_base_addr=0x100000000000,
        sys_mem_base_addr=0,
    )

    # app specific sync
    global start_signal
    start_signal = asyncio.Event()

    global stop_signal
    stop_signal = asyncio.Event()

    global host
    global host_task

    cxl_host_config = CxlHostConfig(
        port_index=0,
        sys_mem_size=(200 * MB),
        sys_sw_app=my_sys_sw_app,
        user_app=my_img_classification_app,
        host_name="PageRankHostType1",
        switch_port=sw_portno,
        enable_hm=False,
    )
    host = CxlHost(cxl_host_config)
    host_task = asyncio.create_task(host.run())

    # install signal handlers
    lp = asyncio.get_event_loop()
    lp.add_signal_handler(SIGINT, lambda signame="SIGINT": asyncio.create_task(shutdown(signame)))
    lp.add_signal_handler(SIGIO, lambda signame="SIGIO": asyncio.create_task(run_demo(signame)))

    os.kill(os.getppid(), SIGCONT)
    await asyncio.Event().wait()  # blocks


if __name__ == "__main__":
    asyncio.run(main())
