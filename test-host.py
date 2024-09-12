import asyncio
from opencxl.apps.cxl_complex_host import CxlComplexHost
from opencxl.cpu import CPU
from opencxl.util.logger import logger

import asyncio
from opencxl.drivers.cxl_bus_driver import CxlBusDriver
from opencxl.drivers.cxl_mem_driver import CxlMemDriver
from opencxl.drivers.pci_bus_driver import PciBusDriver
from opencxl.cxl.component.cxl_memory_hub import CxlMemoryHub, ADDR_TYPE


async def my_sys_sw_app(cxl_memory_hub: CxlMemoryHub):
    # Max addr for CFG for 0x9FFFFFFF, given max num bus = 8
    # Therefore, 0xFE000000 for MMIO does not overlap
    pci_cfg_base_addr = 0x10000000
    pci_mmio_base_addr = 0xFE000000
    cxl_hpa_base_addr = 0x100000000000

    # PCI Device
    root_complex = cxl_memory_hub.get_root_complex()
    pci_bus_driver = PciBusDriver(root_complex)
    await pci_bus_driver.init(pci_mmio_base_addr)
    pci_cfg_size = 0x10000000  # assume bus bits n = 8
    for i, device in enumerate(pci_bus_driver.get_devices()):
        cxl_memory_hub.add_mem_range(
            pci_cfg_base_addr + (i * pci_cfg_size), pci_cfg_size, ADDR_TYPE.CFG
        )
        for bar_info in device.bars:
            if bar_info.base_address == 0:
                continue
            cxl_memory_hub.add_mem_range(bar_info.base_address, bar_info.size, ADDR_TYPE.MMIO)

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
        if await device.get_bi_enable():
            cxl_memory_hub.add_mem_range(hpa_base, size, ADDR_TYPE.CXL_BI)
        else:
            cxl_memory_hub.add_mem_range(hpa_base, size, ADDR_TYPE.CXL)
        hpa_base += size

    for range in cxl_memory_hub.get_memory_ranges():
        # logger.info(
        #     self._create_message(
        #         f"base: 0x{range.base_addr:X}, size: 0x{range.size:X}, type: {str(range.type)}"
        #     )
        # )
        logger.info(
            f"[SYS-SW] base: 0x{range.base_addr:X}, size: 0x{range.size:X}, type: {str(range.addr_type)}"
        )


async def sample_app(cpu: CPU, value: str):
    logger.info(f"[USER-APP] {value} I AM HERE!")
    await cpu.store(0x100000000000, 0x40, 0xDEADBEEF)
    val = await cpu.load(0x100000000000, 0x40)
    logger.info(f"0x{val:X}")
    val = await cpu.load(0x100000000040, 0x40)
    logger.info(f"0x{val:X}")


async def main():
    host = CxlComplexHost(0, 256 * 1024 * 1024, sys_sw_app=my_sys_sw_app, user_app=sample_app)
    logger.info("STARTING")
    await host.run()


if __name__ == "__main__":
    asyncio.run(main())
