#!/usr/bin/env python
"""
 Copyright (c) 2024, Eeum, Inc.

 This software is licensed under the terms of the Revised BSD License.
 See LICENSE for details.
"""

import asyncio
from dataclasses import dataclass, field
import json
import glob
import os
import sys
from random import sample
from signal import SIGCONT, SIGINT, SIGIO
from typing import Dict

from opencis.util.logger import logger
from opencis.cxl.component.cxl_host import CxlHost
from opencis.cpu import CPU
from opencis.util.number_const import MB
from opencis.cxl.component.cxl_memory_hub import CxlMemoryHub, MEM_ADDR_TYPE
from opencis.cxl.component.irq_manager import Irq
from opencis.drivers.cxl_bus_driver import CxlBusDriver
from opencis.drivers.cxl_mem_driver import CxlMemDriver
from opencis.drivers.pci_bus_driver import PciBusDriver


# pylint: disable=global-statement, duplicate-code


@dataclass
class ImageClassificationConfigs:
    train_data_path: str
    accel_count: int
    sample_from_each_category: int
    pci_cfg_base_addr: int = 0x10000000
    pci_cfg_size = 0x10000000  # assuming bus bits n = 8
    pci_mmio_base_addr: int = 0xFE000000
    cxl_hpa_base_addr: int = 0x100000000000
    sys_mem_base_addr: int = 0xFFFF888000000000


@dataclass
class AccelInfo:
    hpa_base_addr: Dict[int, int] = field(default_factory=dict)
    mmio_base_addr: Dict[int, int] = field(default_factory=dict)
    training_done: Dict[int, bool] = field(default_factory=dict)


accel_info = AccelInfo()
host_irq_handler = None
total_samples = 0
validation_results = []
sampled_file_categories = []
cpu = None
mem_hub = None
config = None
start_signal = None
stop_signal = None
host = None
start_tasks = None


async def my_sys_sw_app(cxl_memory_hub: CxlMemoryHub):
    pci_cfg_base_addr = config.pci_cfg_base_addr
    pci_mmio_base_addr = config.pci_mmio_base_addr
    cxl_hpa_base_addr = config.cxl_hpa_base_addr
    sys_mem_base_addr = config.sys_mem_base_addr

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
    dev_id = 0
    for device in cxl_mem_driver.get_devices():
        size = device.get_memory_size()
        successful = await cxl_mem_driver.attach_single_mem_device(device, hpa_base, size)
        if not successful:
            logger.info(f"[SYS-SW] Failed to attach device {device}")
            continue

        cxl_memory_hub.add_mem_range(hpa_base, size, MEM_ADDR_TYPE.CXL_CACHED_BI)
        accel_info.hpa_base_addr[dev_id] = hpa_base
        dev_id += 1
        hpa_base += size

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


def to_accel_mem_addr(dev_id: int, addr: int) -> int:
    return accel_info.hpa_base_addr[dev_id] + addr


def to_accel_mmio_addr(dev_id: int, addr: int) -> int:
    return accel_info.mmio_base_addr[dev_id] + addr


async def check_training_finished_type2(dev_id: int):
    accel_info.training_done[dev_id] = True
    if len(accel_info.training_done) == config.accel_count:
        await do_img_classification_type2()


async def do_img_classification_type2():
    categories = glob.glob(config.train_data_path + "/val/*")
    global total_samples
    total_samples = len(categories) * config.sample_from_each_category

    global validation_results
    validation_results = [[] for i in range(total_samples)]

    pic_id = 0
    IMAGE_WRITE_ADDR = 0x8000
    global sampled_file_categories
    sampled_file_categories = []
    for c in categories:
        category_pics = glob.glob(f"{c}/*.JPEG")
        sample_pics = sample(category_pics, config.sample_from_each_category)
        category_name = c.split(os.path.sep)[-1]
        sampled_file_categories += [category_name] * config.sample_from_each_category
        for s in sample_pics:
            with open(s, "rb") as f:
                pic_data = f.read()
            pic_data_int = int.from_bytes(pic_data, "little")
            pic_data_len = len(pic_data)
            pic_data_len_rounded = (((pic_data_len - 1) // 64) + 1) * 64
            for dev_id in range(config.accel_count):
                event = asyncio.Event()
                write_addr = to_accel_mem_addr(dev_id, IMAGE_WRITE_ADDR)
                logger.debug(f"dev_id:{dev_id} img_addr:{write_addr:x} len:{pic_data_len:x}")
                await cpu.store(
                    write_addr,
                    pic_data_len_rounded,
                    pic_data_int,
                    prog_bar=True,
                )
                await cpu.store(to_accel_mmio_addr(dev_id, 0x1810), 8, IMAGE_WRITE_ADDR)
                await cpu.store(to_accel_mmio_addr(dev_id, 0x1818), 8, pic_data_len)
                while True:
                    pic_data_mem_loc_rb = await cpu.load(to_accel_mmio_addr(dev_id, 0x1810), 8)
                    pic_data_len_rb = await cpu.load(to_accel_mmio_addr(dev_id, 0x1818), 8)
                    if pic_data_mem_loc_rb == IMAGE_WRITE_ADDR and pic_data_len_rb == pic_data_len:
                        break
                    await asyncio.sleep(0.1)

                host_irq_handler.register_interrupt_handler(
                    Irq.ACCEL_VALIDATION_FINISHED,
                    save_results_type2(pic_id, event),
                    dev_id,
                )
                await host_irq_handler.send_irq_request(Irq.HOST_SENT, dev_id)
                await event.wait()

                # Currently we don't send the picture information to the device
                # and to prevent race condition, we need to send pics synchronously
            pic_id += 1

    merge_validation_results()
    stop_signal.set()


def save_results_type2(pic_id: int, event: asyncio.Event):
    async def _func(dev_id: int):
        logger.info(f"Saving validation results for pic: {pic_id} from dev: {dev_id}")
        host_result_addr = await cpu.load(to_accel_mmio_addr(dev_id, 0x1820), 8)
        host_result_len = await cpu.load(to_accel_mmio_addr(dev_id, 0x1828), 8)

        host_result_addr = to_accel_mem_addr(dev_id, host_result_addr)
        data_bytes = await cpu.load_bytes(host_result_addr, host_result_len)
        validate_result = json.loads(data_bytes.decode())
        validation_results[pic_id].append(validate_result)
        event.set()

    return _func


def merge_validation_results():
    correct_count = 0
    for pic_id in range(total_samples):
        merged_result = {}
        max_v = 0
        max_k = 0
        assert len(validation_results[pic_id]) == config.accel_count
        real_category = sampled_file_categories[pic_id]
        for dev_result in validation_results[pic_id]:
            for k, v in dev_result.items():
                if k not in merged_result:
                    merged_result[k] = v
                else:
                    merged_result[k] += v
                if merged_result[k] > max_v:
                    max_v = merged_result[k]
                    max_k = k
        if max_k == real_category:
            correct_count += 1

        logger.info(f"Picture {pic_id} category: Real: {real_category}, validated: {max_k}")

    logger.info("Validation finished. Results:")
    logger.info(
        f"Correct/Total: {correct_count}/{total_samples} "
        f"({100 * correct_count / total_samples:.2f}%)"
    )


async def my_img_classification_app(_cpu: CPU, _mem_hub: CxlMemoryHub):
    global cpu
    cpu = _cpu

    global mem_hub
    mem_hub = _mem_hub

    # Pass init-info mem location to the remote using MMIO
    CSV_DATA_MEM_OFFSET = 0x4000

    logger.info(cpu.create_message("Host main process waiting..."))
    await start_signal.wait()
    logger.info(cpu.create_message("Host main process running!"))

    with open(f"{config.train_data_path}/noisy_imagenette.csv", "rb") as f:
        csv_data = f.read()
    csv_data_int = int.from_bytes(csv_data, "little")
    csv_data_len = len(csv_data)
    csv_data_len_rounded = (((csv_data_len - 1) // 64) + 1) * 64

    for dev_id in range(config.accel_count):
        logger.info(cpu.create_message(f"Sending Metadata to dev {dev_id}"))
        write_addr = to_accel_mem_addr(dev_id, CSV_DATA_MEM_OFFSET)
        await cpu.store(write_addr, csv_data_len_rounded, csv_data_int, prog_bar=True)

        await mem_hub.write_mmio(to_accel_mmio_addr(dev_id, 0x1800), 8, CSV_DATA_MEM_OFFSET)
        await mem_hub.write_mmio(to_accel_mmio_addr(dev_id, 0x1808), 8, csv_data_len)
        while True:
            csv_data_mem_loc_rb = await mem_hub.read_mmio(to_accel_mmio_addr(dev_id, 0x1800), 8)
            csv_data_len_rb = await mem_hub.read_mmio(to_accel_mmio_addr(dev_id, 0x1808), 8)
            if csv_data_mem_loc_rb == CSV_DATA_MEM_OFFSET and csv_data_len_rb == csv_data_len:
                break
            await asyncio.sleep(0.1)

        host_irq_handler.register_interrupt_handler(
            Irq.ACCEL_TRAINING_FINISHED, check_training_finished_type2, dev_id
        )

    # kick off accel training
    logger.info("[APP] Notifying Host Ready to Accelerators")
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
        await asyncio.gather(*start_tasks)
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
        sample_from_each_category=1,
        pci_cfg_base_addr=0x10000000,
        pci_mmio_base_addr=0xFE000000,
        cxl_hpa_base_addr=0x100000000000,
        sys_mem_base_addr=0xFFFF888000000000,
    )

    # app specific sync
    global start_signal
    start_signal = asyncio.Event()

    global stop_signal
    stop_signal = asyncio.Event()

    global host
    global start_tasks

    host = CxlHost(
        port_index=0,
        sys_mem_size=(2 * MB),
        sys_sw_app=my_sys_sw_app,
        user_app=my_img_classification_app,
        host_name="ImageHostType2",
        switch_port=sw_portno,
        enable_hm=False,
    )
    start_tasks = [
        asyncio.create_task(host.run()),
    ]
    await host.wait_for_ready()

    # install signal handlers
    lp = asyncio.get_event_loop()
    lp.add_signal_handler(SIGINT, lambda signame="SIGINT": asyncio.create_task(shutdown(signame)))
    lp.add_signal_handler(SIGIO, lambda signame="SIGIO": asyncio.create_task(run_demo(signame)))

    os.kill(os.getppid(), SIGCONT)
    await asyncio.Event().wait()  # blocks


if __name__ == "__main__":
    asyncio.run(main())
