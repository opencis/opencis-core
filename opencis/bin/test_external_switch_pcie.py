"""
 Copyright (c) 2024, Eeum, Inc.

 This software is licensed under the terms of the Revised BSD License.
 See LICENSE for details.
"""

import asyncio
from typing import List, cast

from opencis.cxl.component.cxl_host import CxlHost
from opencis.apps.pci_device import PciDevice
from opencis.util.logger import logger
from opencis.util.component import RunnableComponent
from opencis.drivers.pci_bus_driver import PciBusDriver

# pylint: disable=duplicate-code


class TestRunner:
    def __init__(self, apps: List[RunnableComponent]):
        self._apps = apps

    async def run(self):
        tasks = []
        for app in self._apps:
            tasks.append(asyncio.create_task(app.run()))
        tasks.append(asyncio.create_task(self.run_test()))
        await asyncio.gather(*tasks)

    async def wait_for_ready(self):
        tasks = []
        for app in self._apps:
            tasks.append(asyncio.create_task(app.wait_for_ready()))
        await asyncio.gather(*tasks)

    async def run_test(self):
        logger.info("Waiting for Apps to be ready")
        await self.wait_for_ready()
        host = cast(CxlHost, self._apps[0])
        pci_bus_driver = PciBusDriver(host.get_root_complex())
        logger.info("Starting PCI bus driver init")
        await pci_bus_driver.init(mmio_base_address=0)
        logger.info("Completed PCI bus driver init")


def main():
    # Set up logger
    log_file = "test.log"
    log_level = "DEBUG"
    show_timestamp = True
    show_loglevel = True
    show_linenumber = True
    logger.create_log_file(
        f"logs/{log_file}",
        loglevel=log_level if log_level else "INFO",
        show_timestamp=show_timestamp,
        show_loglevel=show_loglevel,
        show_linenumber=show_linenumber,
    )

    apps = []

    # Add Host
    # switch_host = "0.0.0.0"
    # switch_port = 8000
    # host_config = CxlHostConfig(
    #     host_name="CXLHost",
    #     root_bus=0,
    #     root_port_switch_type=ROOT_PORT_SWITCH_TYPE.PASS_THROUGH,
    #     root_ports=[
    #         RootPortClientConfig(port_index=0, switch_host=switch_host, switch_port=switch_port)
    #     ],
    #     memory_ranges=[],
    #     memory_controller=RootComplexMemoryControllerConfig(
    #         memory_size=0x10000, memory_filename="memory_dram.bin"
    #     ),
    # )
    # host = CxlHost(host_config)
    # apps.append(host)

    # Add PCI devices
    for port in range(1, 5):
        device = PciDevice(port, 0x1000)
        apps.append(device)

    test_runner = TestRunner(apps)
    asyncio.run(test_runner.run())


if __name__ == "__main__":
    main()
