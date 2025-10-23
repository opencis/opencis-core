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
import pyshark, time
from pyshark.packet.packet import Packet

from opencis.util.logger import logger
from opencis.cxl.component.cxl_host import CxlHost, CxlHostConfig
from opencis.cpu import CPU
from opencis.util.number_const import MB
from opencis.cxl.component.cxl_memory_hub import CxlMemoryHub, MEM_ADDR_TYPE
from opencis.cxl.component.irq_manager import Irq
from opencis.drivers.cxl_bus_driver import CxlBusDriver
from opencis.drivers.cxl_mem_driver import CxlMemDriver
from opencis.drivers.pci_bus_driver import PciBusDriver
from opencis.apps.packet_processor import CustomList
import nest_asyncio

nest_asyncio.apply()


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
TOTAL_MEM_SIZE = 200 * MB
INITIAL_PACKET_ADDR = 0x2000
packet_data = CustomList(2, START_ADDR)
continue_signal = asyncio.Event()

# Path to your pcap file
pcap_file_path = "/Users/zhxq/Downloads/50000-t1n2f1u-cache8-32.pcap"
# Define custom parameters to load the Lua script
# custom_params = {'-X': f'lua_script:{lua_script_path}'}

# Open the pcap file with custom parameters
# cap = pyshark.FileCapture(input_file=pcap_file_path, custom_parameters=custom_params)
cap = pyshark.FileCapture(
    input_file=pcap_file_path, display_filter="opencis.cache", include_raw=True, use_json=True
)
# assigning each page a rank of 1/n, where n is total number of pages in the corpus
i = 0

current_offset = INITIAL_PACKET_ADDR


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
    continue_signal.set()


async def check_final_iter_ready():
    print("All packets handled!!")
    stop_signal.set()


async def process_packet_async(packet):
    pass


async def my_img_classification_app(**kwargs):
    global cpu, packet_data, host_irq_handler, current_offset
    cpu = kwargs["cpu"]

    global mem_hub
    mem_hub = kwargs["cxl_memory_hub"]

    # 0: location
    # 1: len
    packet_data.setReadFunc(cpu.load_bytes)
    packet_data.setWriteFunc(cpu.store)

    # Pass init-info mem location to the remote using MMIO
    logger.info("Host main process waiting...")
    await start_signal.wait()
    logger.info("Host main process running!")

    # One iteration finished
    host_irq_handler.register_interrupt_handler(
        Irq.ACCEL_TRAINING_FINISHED, barrier_one_iter_finished_type1, 0
    )

    packet: Packet
    count = 0
    for packet in cap:
        if count == 10000:
            break
        raw_data = packet.get_raw_packet()
        # processor.parse_packet(raw_data)
        # print(raw_data)
        raw_data_len = packet.length
        assert len(raw_data) == raw_data_len

        raw_data_padded = raw_data + (bytes(b"\x00") * (64 - (raw_data_len % 64)))
        raw_data_padded_len = len(raw_data_padded)

        await packet_data.host_setitem(0, current_offset)
        await packet_data.host_setitem(1, raw_data_len)

        # print(
        #     f"Storing addr 0x{current_offset:08x}, len 0x{raw_data_len:08x}, padded_len 0x{raw_data_padded_len:08x}"
        # )

        await cpu.store_bin(current_offset, raw_data_padded_len, raw_data_padded)

        for i in range(raw_data_padded_len // 64):
            await cpu.flush_data(current_offset + i * 64, 64)

        current_offset += raw_data_len
        current_offset = ((current_offset - 1) // 64 + 1) * 64

        if current_offset >= TOTAL_MEM_SIZE:
            current_offset = INITIAL_PACKET_ADDR

        host_irq_handler = host.get_irq_manager()
        await host_irq_handler.send_irq_request(Irq.HOST_SENT, 0)
        continue_signal.clear()
        await continue_signal.wait()

        count += 1
        if count % 1000 == 0:
            print(f"{count} packets processed...")

    await host_irq_handler.send_irq_request(Irq.HOST_READY, 0)
    await check_final_iter_ready()


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
        sys_mem_size=TOTAL_MEM_SIZE,
        sys_sw_app=my_sys_sw_app,
        user_app=my_img_classification_app,
        host_name="PacketProcessorHostType1",
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
