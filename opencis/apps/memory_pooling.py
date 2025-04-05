"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

import asyncio
from dataclasses import dataclass

from opencis.cxl.component.fabric_manager.socketio_server import HostFMMsg
from opencis.cxl.component.short_msg_conn import ShortMsgConn
from opencis.util.logger import logger
from opencis.drivers.cxl_bus_driver import CxlBusDriver
from opencis.drivers.cxl_mem_driver import CxlMemDriver
from opencis.drivers.pci_bus_driver import PciBusDriver
from opencis.cxl.component.cxl_memory_hub import CxlMemoryHub, MEM_ADDR_TYPE
from opencis.cxl.component.cxl_host import CxlHost, CxlHostConfig
from opencis.cxl.component.hdm_decoder import INTERLEAVE_GRANULARITY, INTERLEAVE_WAYS
from opencis.cpu import CPU
from opencis.util.number_const import MB


@dataclass
class MemoryStruct:
    base: int
    size: int


class CxlDeviceMemTracker:
    def __init__(self, cxl_memory_hub: CxlMemoryHub):
        self._ld_tracker: dict[str, dict[MEM_ADDR_TYPE, MemoryStruct]] = {}
        self._cxl_memory_hub = cxl_memory_hub

    def _create_key(self, device_port):
        return f"{device_port}".lower()

    def _add_device(self, key):
        self._ld_tracker[key] = {k: MemoryStruct(0, 0) for k in MEM_ADDR_TYPE}

    def check_device_added(self, device_port):
        key = self._create_key(device_port)
        return key in self._ld_tracker

    def add_mem_range(self, device_port: int, base: int, size: int, type: MEM_ADDR_TYPE):
        key = self._create_key(device_port)
        if key not in self._ld_tracker:
            self._add_device(key)
        self._ld_tracker[key][type].base = base
        self._ld_tracker[key][type].size = size
        self._cxl_memory_hub.add_mem_range(base, size, type)

    def remove_mem_range(self, device_port):
        key = self._create_key(device_port)
        if key in self._ld_tracker:
            for type, mem_info in self._ld_tracker[key].items():
                if mem_info.size > 0:
                    self._cxl_memory_hub.remove_mem_range(mem_info.base, mem_info.size, type)
            del self._ld_tracker[key]
        else:
            logger.warning(f"No record for device @ port {device_port}")

    def __str__(self):
        return str(self._ld_tracker)


@dataclass
class MemoryBaseTracker:
    hpa_base: int
    cfg_base: int
    mmio_base: int


host_fm_conn = None


async def my_sys_sw_app(ig: int = None, iw: int = None, host_fm_conn_port: int = 8700, **kwargs):
    cxl_memory_hub: CxlMemoryHub

    # Max addr for CFG is 0x9FFFFFFF, given max num bus = 8
    # Therefore, 0xFE000000 for MMIO does not overlap
    pci_cfg_base_addr = 0x10000000
    pci_mmio_base_addr = 0xFE000000
    cxl_hpa_base_addr = 0x100000000000
    sys_mem_base_addr = 0xFFFF888000000000
    cxl_memory_hub = kwargs["cxl_memory_hub"]

    # PCI Device
    mem_tracker = CxlDeviceMemTracker(cxl_memory_hub)
    root_complex = cxl_memory_hub.get_root_complex()
    root_port = cxl_memory_hub.get_root_port()
    host_fm_conn_client = ShortMsgConn(
        "FM_Client",
        port=host_fm_conn_port,
        server=False,
        msg_width=16,
        msg_type=HostFMMsg,
        device_id=root_port,
    )
    # pylint: disable=global-statement
    global host_fm_conn  # To prevent the connection from GC'ed after function's done
    host_fm_conn = host_fm_conn_client
    pci_bus_driver = PciBusDriver(root_complex)
    mmio_base = await pci_bus_driver.init(pci_mmio_base_addr)

    # CXL Device
    cxl_bus_driver = CxlBusDriver(pci_bus_driver, root_complex)
    cxl_mem_driver = CxlMemDriver(cxl_bus_driver, root_complex)
    await cxl_bus_driver.init()
    await cxl_mem_driver.init()

    pci_cfg_size = 0x10000000  # assume bus bits n = 8
    memory_base_tracker = MemoryBaseTracker(cxl_hpa_base_addr, pci_cfg_base_addr, mmio_base)

    for device in pci_bus_driver.get_devices():
        if not device.is_bridge:
            continue

        cxl_memory_hub.add_mem_range(memory_base_tracker.cfg_base, pci_cfg_size, MEM_ADDR_TYPE.CFG)
        memory_base_tracker.cfg_base += pci_cfg_size
        for bar_info in device.bars:
            if bar_info.base_address == 0:
                continue
            cxl_memory_hub.add_mem_range(bar_info.base_address, bar_info.size, MEM_ADDR_TYPE.MMIO)

    ig = INTERLEAVE_GRANULARITY(int(ig)) if ig is not None else INTERLEAVE_GRANULARITY(0)
    iw = INTERLEAVE_WAYS(int(iw)) if iw is not None else INTERLEAVE_WAYS(0)
    iw_in_int = int(iw.name.rsplit("_", maxsplit=1)[-1])

    dev_mem_sizes = []
    vppbs = []
    for device in cxl_mem_driver.get_devices():
        dev_mem_sizes.append(device.get_memory_size())
        vppb = cxl_mem_driver.get_port_number(device)
        if vppb < 0:
            logger.info(f"[SYS-SW] {vppb} is invalid")
            return False
        vppbs.append(vppb)

    hpa_base = memory_base_tracker.hpa_base
    if iw_in_int > 1:
        # interleaving enabled
        # The smallest memory size is used for determining interleaved memory size
        # Only support all DSP device interleaving.
        # TODO: add partial VCS interleaving.
        min_size = min(dev_mem_sizes)
        interleaved_mem_size = min_size * len(dev_mem_sizes)
        logger.info(f"{dev_mem_sizes}, {interleaved_mem_size:x}")

        # setup HDM decoder for devices
        for device in cxl_mem_driver.get_devices():
            successful = await cxl_mem_driver.config_cxl_mem_device(
                device, hpa_base, interleaved_mem_size, ig=ig, iw=iw
            )
            if not successful:
                raise Exception("[SYS-SW] Failed to Configure CXL.mem Device")

        # setup HDM decoder for USP
        upstream_port = device.parent.parent
        # usp = dsp.parent
        successful = await cxl_mem_driver.config_usp(
            upstream_port, hpa_base, interleaved_mem_size, vppbs, ig=ig, iw=iw
        )
        if not successful:
            raise Exception("[SYS-SW] Failed to Configure USP")

        # Add CXL.mem ranges
        if await device.get_bi_enable():
            mem_tracker.add_mem_range(
                vppbs[0],
                memory_base_tracker.hpa_base,
                interleaved_mem_size,
                MEM_ADDR_TYPE.CXL_CACHED_BI,
            )
        else:
            mem_tracker.add_mem_range(
                vppbs[0],
                memory_base_tracker.hpa_base,
                interleaved_mem_size,
                MEM_ADDR_TYPE.CXL_UNCACHED,
            )
    else:
        # interleave disabled
        for device in cxl_mem_driver.get_devices():
            size = device.get_memory_size()
            successful = await cxl_mem_driver.attach_single_mem_device(
                device, memory_base_tracker.hpa_base, size
            )
            sn = device.pci_device_info.serial_number
            vppb = cxl_mem_driver.get_port_number(device)
            if not successful:
                logger.info(f"[SYS-SW] Failed to attach device {device}")
                continue
            logger.info(f"[SYS-SW] Attached to device, SN: {sn}, port: {vppb}")

            # Add CXL.mem ranges
            if await device.get_bi_enable():
                mem_tracker.add_mem_range(
                    vppb, memory_base_tracker.hpa_base, size, MEM_ADDR_TYPE.CXL_CACHED_BI
                )
            else:
                mem_tracker.add_mem_range(
                    vppb, memory_base_tracker.hpa_base, size, MEM_ADDR_TYPE.CXL_UNCACHED
                )
            memory_base_tracker.hpa_base += size

    # System Memory
    sys_mem_size = root_complex.get_sys_mem_size()
    cxl_memory_hub.add_mem_range(sys_mem_base_addr, sys_mem_size, MEM_ADDR_TYPE.DRAM)

    for range in cxl_memory_hub.get_memory_ranges():
        logger.info(
            f"[SYS-SW] MemoryRange: base: 0x{range.base_addr:X} "
            f"size: 0x{range.size:X}, type: {str(range.addr_type)}"
        )

    logger.debug(f"[SYS-SW] Creating connection for host with root port {root_port}")

    await host_fm_conn_client.start_connection()

    def bind():
        async def _bind(_: int, data: HostFMMsg):
            logger.info(
                f"[SYS-SW] Received {data.readable}, val {data.real_val} from FM, vPPB: {data.vppb}"
            )
            if data.root_port != root_port:
                logger.info(
                    f"[SYS-SW] But this request (root_port {data.root_port}) "
                    f"is not for this host (root_port {root_port})."
                )
                return

            existing_mem_devices = cxl_mem_driver.get_devices()
            existing_mem_bdfs = [device.pci_device_info.bdf for device in existing_mem_devices]
            mmio_base = await pci_bus_driver.scan_bus_bind(memory_base_tracker.mmio_base)
            await cxl_bus_driver.init()
            await cxl_mem_driver.init()
            memory_base_tracker.mmio_base = mmio_base

            current_mem_devices = cxl_mem_driver.get_devices()
            # TODO: Add sanity check and make sure this loop is only run once
            for device in current_mem_devices:
                if device.pci_device_info.bdf not in existing_mem_bdfs:
                    port = cxl_mem_driver.get_port_number(device)
                    mem_tracker.add_mem_range(
                        port,
                        memory_base_tracker.cfg_base,
                        pci_cfg_size,
                        MEM_ADDR_TYPE.CFG,
                    )
                    memory_base_tracker.cfg_base += pci_cfg_size
                    for bar_info in device.pci_device_info.bars:
                        if bar_info.base_address == 0:
                            continue
                        mem_tracker.add_mem_range(
                            port,
                            bar_info.base_address,
                            bar_info.size,
                            MEM_ADDR_TYPE.MMIO,
                        )

                    if await device.get_bi_enable():
                        mem_tracker.add_mem_range(
                            port,
                            memory_base_tracker.hpa_base,
                            size,
                            MEM_ADDR_TYPE.CXL_CACHED_BI,
                        )
                    else:
                        mem_tracker.add_mem_range(
                            port,
                            memory_base_tracker.hpa_base,
                            size,
                            MEM_ADDR_TYPE.CXL_UNCACHED,
                        )
                    memory_base_tracker.hpa_base += size

                    confirmation = HostFMMsg.create(data.vppb, root_port, True, True)
                    await host_fm_conn_client.send_irq_request(confirmation)
                    return
            logger.error(f"[SYS-SW] FM unable to bind device @ vppb: {data.vppb}")

        return _bind

    def unbind():
        async def _unbind(_: int, data: HostFMMsg):
            logger.info(f"[SYS-SW] Received {data.readable} from FM")
            if data.root_port != root_port:
                logger.info(
                    f"[SYS-SW] But this request (root_port {data.root_port}) "
                    f"is not for this host (root_port {root_port})."
                )
                return
            logger.info(f"[SYS-SW] FM unbind device @ port: {data.vppb}")
            mem_tracker.remove_mem_range(data.vppb)
            # Remove removed devices
            await pci_bus_driver.scan_bus_unbind()
            await cxl_bus_driver.init()
            await cxl_mem_driver.init()
            confirmation = HostFMMsg.create(data.vppb, root_port, True, False)
            await host_fm_conn_client.send_irq_request(confirmation)

        return _unbind

    host_fm_conn_client.register_general_handler(HostFMMsg.BIND, bind())
    host_fm_conn_client.register_general_handler(HostFMMsg.UNBIND, unbind())

    # TODO: Sort and merge ranges


async def sample_app(keepalive: bool, **kwargs):
    cpu: CPU

    cpu = kwargs["cpu"]
    logger.info("[USER-APP] Starting...")
    await cpu.store(0x100000000000, 0x40, 0xDEADBEEF)
    val = await cpu.load(0x100000000000, 0x40)
    logger.info(f"0x{val:X}")
    val = await cpu.load(0x100000000040, 0x40)
    logger.info(f"0x{val:X}")

    if keepalive:
        await asyncio.Event().wait()


async def run_host(port_index: int, irq_port: int, ig: int, iw: int):
    cxl_host_config = CxlHostConfig(
        port_index=port_index,
        sys_mem_size=(16 * MB),
        sys_sw_app=lambda **kwargs: my_sys_sw_app(ig=ig, iw=iw, **kwargs),
        user_app=lambda **kwargs: sample_app(keepalive=True, **kwargs),
        irq_port=irq_port,
    )
    host = CxlHost(cxl_host_config)
    await host.run()


if __name__ == "__main__":
    asyncio.run(run_host(port_index=0, irq_port=8500, ig=0, iw=2))
