"""
 Copyright (c) 2024, Eeum, Inc.

 This software is licensed under the terms of the Revised BSD License.
 See LICENSE for details.
"""

from asyncio import gather, create_task, run
from typing import List, cast

from opencis.util.logger import logger
from opencis.util.component import RunnableComponent
from opencis.cxl.component.switch_connection_manager import SwitchConnectionManager
from opencis.cxl.component.physical_port_manager import PhysicalPortManager
from opencis.cxl.component.virtual_switch_manager import (
    VirtualSwitchManager,
    VirtualSwitchConfig,
)
from opencis.cxl.component.cxl_component import PortConfig, PORT_TYPE
from opencis.cxl.component.cxl_host import CxlHost
from opencis.apps.accelerator import MyType1Accelerator
from opencis.drivers.pci_bus_driver import PciBusDriver
from opencis.drivers.cxl_bus_driver import CxlBusDriver
from opencis.drivers.cxl_mem_driver import CxlMemDriver

# pylint: disable=duplicate-code


class TestRunner:
    def __init__(self, apps: List[RunnableComponent]):
        self._apps = apps

    async def run(self):
        tasks = []
        for app in self._apps:
            tasks.append(create_task(app.run()))
        tasks.append(create_task(self.run_test()))
        await gather(*tasks)

    async def wait_for_ready(self):
        tasks = []
        for app in self._apps:
            tasks.append(create_task(app.wait_for_ready()))
        await gather(*tasks)

    async def run_test(self):
        logger.info("Waiting for Apps to be ready")
        await self.wait_for_ready()
        host = cast(CxlHost, self._apps[3])
        pci_bus_driver = PciBusDriver(host.get_root_complex())
        logger.info("Starting PCI bus driver init")
        await pci_bus_driver.init(mmio_base_address=0)
        logger.info("Completed PCI bus driver init")
        cxl_bus_driver = CxlBusDriver(pci_bus_driver, host.get_root_complex())
        logger.info("Starting CXL bus driver init")
        await cxl_bus_driver.init()
        logger.info("Completed CXL bus driver init")
        cxl_mem_driver = CxlMemDriver(cxl_bus_driver, host.get_root_complex())
        await cxl_mem_driver.init()

        logger.info("Start CXL.cache Host/Device cache coherency test")
        logger.info("================================================")


def main():
    # Set up logger
    log_file = "cxl_type1_test.log"
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

    switch_port = 8000
    port_configs = [
        PortConfig(PORT_TYPE.USP),
        PortConfig(PORT_TYPE.DSP),
        PortConfig(PORT_TYPE.DSP),
        PortConfig(PORT_TYPE.DSP),
        PortConfig(PORT_TYPE.DSP),
    ]
    sw_conn_manager = SwitchConnectionManager(port_configs, port=switch_port)
    apps.append(sw_conn_manager)

    physical_port_manager = PhysicalPortManager(
        switch_connection_manager=sw_conn_manager, port_configs=port_configs
    )
    apps.append(physical_port_manager)

    switch_configs = [
        VirtualSwitchConfig(
            upstream_port_index=0,
            vppb_counts=4,
            initial_bounds=[1, 2, 3, 4],
            irq_host="0.0.0.0",
            irq_port=8500,
        )
    ]
    virtual_switch_manager = VirtualSwitchManager(
        switch_configs=switch_configs, physical_port_manager=physical_port_manager, allocated_ld=[]
    )
    apps.append(virtual_switch_manager)

    # 256 MB
    # host_config = CxlHostConfig(
    #     host_name="CXLHost",
    #     root_bus=0,
    #     root_port_switch_type=ROOT_PORT_SWITCH_TYPE.PASS_THROUGH,
    #     root_ports=[RootPortClientConfig(0, "0.0.0.0", 8000)],
    #     coh_type=COH_POLICY_TYPE.DotMemBI,
    #     memory_controller=RootComplexMemoryControllerConfig(
    #         memory_size=memory_size, memory_filename="memory_dram.bin"
    #     ),
    #     memory_ranges=[],
    # )
    # host = CxlHost(host_config)
    # apps.append(host)

    accel_t1_1 = MyType1Accelerator(
        port_index=1,
        port=switch_port,
        device_id=0,
    )
    apps.append(accel_t1_1)
    accel_t1_2 = MyType1Accelerator(
        port_index=2,
        port=switch_port,
        device_id=1,
    )
    apps.append(accel_t1_2)
    accel_t1_3 = MyType1Accelerator(
        port_index=3,
        port=switch_port,
        device_id=2,
    )
    apps.append(accel_t1_3)
    accel_t1_4 = MyType1Accelerator(
        port_index=4,
        port=switch_port,
        device_id=3,
    )
    apps.append(accel_t1_4)

    test_runner = TestRunner(apps)
    run(test_runner.run())


if __name__ == "__main__":
    main()
