#!/usr/bin/env python3

import logging
from signal import *
import asyncio
import sys, os

from opencis.apps.synth_cxl_image_classification_host import (
    CxlImageClassificationHost,
    CxlImageClassificationHostConfig,
)
from opencis.cxl.component.common import CXL_COMPONENT_TYPE
from opencis.cxl.component.root_complex.home_agent import MEMORY_RANGE_TYPE, MemoryRange
from opencis.cxl.component.root_complex.root_complex import RootComplexMemoryControllerConfig
from opencis.cxl.component.root_complex.root_port_client_manager import RootPortClientConfig
from opencis.cxl.component.root_complex.root_port_switch import (
    COH_POLICY_TYPE,
    ROOT_PORT_SWITCH_TYPE,
)
from opencis.drivers.cxl_bus_driver import CxlBusDriver
from opencis.drivers.cxl_mem_driver import CxlMemDriver
from opencis.drivers.pci_bus_driver import PciBusDriver
from opencis.util.logger import logger

logger.setLevel(logging.INFO)

host: CxlImageClassificationHost = None

start_tasks = []
stop_signal = asyncio.Event()

host_starter: asyncio.Task = None


async def shutdown(signame=None):
    global host
    global start_tasks
    global stop_signal
    try:
        stop_tasks = [
            asyncio.create_task(host.stop()),
        ]
    except Exception as exc:
        logger.debug("[HOST]", exc.__traceback__)
        quit()
    await asyncio.gather(*stop_tasks, return_exceptions=True)
    await asyncio.gather(*start_tasks)
    logger.debug("Host quitted")
    os._exit(0)


async def start_host(signame=None):
    global host
    global stop_signal
    await host.start_job()
    stop_signal.set()


async def main():
    # install signal handlers
    lp = asyncio.get_event_loop()
    lp.add_signal_handler(SIGINT, lambda signame="SIGINT": asyncio.create_task(shutdown(signame)))
    lp.add_signal_handler(SIGIO, lambda signame="SIGIO": asyncio.create_task(start_host(signame)))

    sw_portno = int(sys.argv[1])
    train_data_path = sys.argv[2]
    logger.debug(f"[HOST] listening on port {sw_portno}, train_data_path: {train_data_path}")

    global host
    global start_tasks
    host_mem_size = 0x8000  # Needs to be big enough to test cache eviction

    host_name = "foo"
    root_port_switch_type = ROOT_PORT_SWITCH_TYPE.PASS_THROUGH
    memory_controller = RootComplexMemoryControllerConfig(host_mem_size, "foo.bin")
    root_ports = [RootPortClientConfig(0, "localhost", sw_portno)]
    memory_ranges = [MemoryRange(MEMORY_RANGE_TYPE.DRAM, 0x0, host_mem_size)]

    config = CxlImageClassificationHostConfig(
        host_name,
        0,
        root_port_switch_type,
        train_data_path,
        memory_controller,
        memory_ranges,
        root_ports,
        coh_type=COH_POLICY_TYPE.DotCache,
        device_type=CXL_COMPONENT_TYPE.T1,
    )

    host = CxlImageClassificationHost(config)

    pci_bus_driver = PciBusDriver(host.get_root_complex())
    cxl_bus_driver = CxlBusDriver(pci_bus_driver, host.get_root_complex())
    cxl_mem_driver = CxlMemDriver(cxl_bus_driver, host.get_root_complex())

    start_tasks = [
        asyncio.create_task(host.run()),
    ]
    ready_tasks = [
        asyncio.create_task(host.wait_for_ready()),
    ]

    os.kill(os.getppid(), SIGCONT)

    await asyncio.gather(*ready_tasks)

    await pci_bus_driver.init()
    await cxl_bus_driver.init()
    await cxl_mem_driver.init()

    cache_dev_count = 0
    for device in cxl_bus_driver.get_devices():
        if device.device_dvsec:
            if device.device_dvsec.cache_capable:
                cache_dev_count += 1
    logger.debug(f"cache_dev_count: {cache_dev_count}")

    host.set_device_count(cache_dev_count)
    host.get_root_complex().set_cache_coh_dev_count(cache_dev_count)

    for device in cxl_mem_driver.get_devices():
        # NOTE: The list should match the dev order
        # otherwise the dev base may not match the IRQ ports
        host.append_dev_mmio_range(
            device.pci_device_info.bars[0].base_address, device.pci_device_info.bars[0].size
        )

    logger.debug("[HOST] ready!")

    await stop_signal.wait()

    os.kill(os.getppid(), SIGINT)


if __name__ == "__main__":
    asyncio.run(main())
