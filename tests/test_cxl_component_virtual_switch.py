"""
 Copyright (c) 2024, Eeum, Inc.

 This software is licensed under the terms of the Revised BSD License.
 See LICENSE for details.
"""

from asyncio import create_task, gather
from typing import List, Tuple, cast
import pytest

from opencis.util.logger import logger
from opencis.cxl.component.bind_processor import PpbDspBindProcessor
from opencis.cxl.component.cxl_connection import CxlConnection
from opencis.cxl.device.pci_to_pci_bridge_device import PpbDevice
from opencis.cxl.device.port_device import CxlPortDevice
from opencis.cxl.device.upstream_port_device import UpstreamPortDevice
from opencis.cxl.device.downstream_port_device import DownstreamPortDevice
from opencis.cxl.device.root_port_device import (
    CxlRootPortDevice,
    MmioEnumerationInfo,
    EnumerationInfo,
)
from opencis.cxl.device.cxl_type3_device import CxlType3Device, CXL_T3_DEV_TYPE
from opencis.cxl.component.virtual_switch_manager import (
    CxlVirtualSwitch,
)
from opencis.util.unaligned_bit_structure import UnalignedBitStructure
from opencis.cxl.transport.transaction import (
    CXL_MEM_M2SBIRSP_OPCODE,
    BasePacket,
    CxlIoBasePacket,
    CxlIoCompletionWithDataPacket,
    is_cxl_io_completion_status_ur,
)
from opencis.util.pci import (
    create_bdf,
    bdf_to_string,
)


#
# HELPER FUNCTIONS
#
def check_if_unsupported_packet(packet):
    base_packet = cast(BasePacket, packet)
    assert is_cxl_io_completion_status_ur(base_packet)


def extract_cfg_read_value(packet):
    base_packet = cast(BasePacket, packet)
    assert base_packet.is_cxl_io()
    cxl_io_packet = cast(CxlIoBasePacket, packet)
    assert cxl_io_packet.is_cpld()
    cxl_io_cpld_packet = cast(CxlIoCompletionWithDataPacket, packet)
    return cxl_io_cpld_packet.data


def create_cxl_topology(bind: bool = False, memory_size: int = 0x100000) -> Tuple[
    CxlVirtualSwitch,
    List[CxlPortDevice],
    CxlRootPortDevice,
    List[CxlType3Device],
    List[DownstreamPortDevice],
    List[PpbDevice],
    List[PpbDspBindProcessor],
]:
    vcs_id = 0
    upstream_port_index = 0
    vppb_counts = 3
    initial_bounds = [-1, -1, -1] if not bind else [1, 2, 3]
    usp_transport = CxlConnection()
    root_port_device = CxlRootPortDevice(
        downstream_connection=usp_transport, label=f"Port{upstream_port_index}"
    )
    usp_device = UpstreamPortDevice(transport_connection=usp_transport, port_index=0)
    dsp_devices = []
    cxl_devices = []
    ppb_devices = []
    ppb_bind_processors = []
    allocated_ld = {}
    for port_index in range(1, vppb_counts + 1):
        connection = CxlConnection()
        dsp = DownstreamPortDevice(transport_connection=connection, port_index=port_index)
        ppb = PpbDevice(port_index)
        ppb_devices.append(ppb)
        bind = PpbDspBindProcessor(ppb.get_downstream_connection(), dsp.get_transport_connection())
        ppb_bind_processors.append(bind)
        dsp.set_ppb(ppb, bind)
        dsp_devices.append(dsp)
        sld = CxlType3Device(
            transport_connection=connection,
            memory_size=memory_size,
            memory_file=f"mem{port_index}.bin",
            serial_number="EEEEEEEEEEEEEEEE",
            dev_type=CXL_T3_DEV_TYPE.SLD,
        )
        cxl_devices.append(sld)
        allocated_ld[port_index] = [0]

    physical_ports: List[CxlPortDevice] = [usp_device] + dsp_devices
    vcs = CxlVirtualSwitch(
        id=vcs_id,
        upstream_port_index=upstream_port_index,
        vppb_counts=vppb_counts,
        initial_bounds=initial_bounds,
        physical_ports=physical_ports,
        allocated_ld=allocated_ld,
    )
    return (
        vcs,
        physical_ports,
        root_port_device,
        cxl_devices,
        dsp_devices,
        ppb_devices,
        ppb_bind_processors,
    )


def compare_enum_info(enum1: EnumerationInfo, enum2: EnumerationInfo, check_len: bool = True):
    enum1_bridges = [item for item in enum1.get_all_devices() if item.is_bridge]
    enum2_bridges = [item for item in enum2.get_all_devices() if item.is_bridge]
    logger.info(f"[PyTest] Number of bridges from enum1: {len(enum1_bridges)}")
    logger.info(f"[PyTest] Number of bridges from enum2: {len(enum2_bridges)}")
    if check_len:
        assert len(enum1_bridges) == len(enum2_bridges)
    for _, (enum1_bridge, enum2_bridge) in enumerate(zip(enum1_bridges, enum2_bridges)):
        assert enum1_bridge.bdf == enum2_bridge.bdf
        assert enum1_bridge.class_code == enum2_bridge.class_code
        assert enum1_bridge.mmio_range.memory_base == enum2_bridge.mmio_range.memory_base
        assert enum1_bridge.mmio_range.memory_limit == enum2_bridge.mmio_range.memory_limit


#
# END OF HELPER FUNCTIONS
#


def test_virtual_switch_manager_init():
    UnalignedBitStructure.make_quiet()
    vcs_id = 0
    vppb_counts = 3
    initial_bounds = [1, 2, 3]
    physical_ports = [
        UpstreamPortDevice(transport_connection=CxlConnection(), port_index=0),
        DownstreamPortDevice(transport_connection=CxlConnection(), port_index=1),
        DownstreamPortDevice(transport_connection=CxlConnection(), port_index=2),
        DownstreamPortDevice(transport_connection=CxlConnection(), port_index=3),
    ]
    allocated_ld = {}
    for index in range(vppb_counts):
        allocated_ld[index + 1] = [0]

    with pytest.raises(Exception, match="physical port 1 is not USP"):
        CxlVirtualSwitch(
            id=vcs_id,
            upstream_port_index=1,
            vppb_counts=vppb_counts,
            initial_bounds=initial_bounds,
            physical_ports=physical_ports,
            allocated_ld=allocated_ld,
        )
    with pytest.raises(Exception, match="length of initial_bounds and vppb_count must be the same"):
        CxlVirtualSwitch(
            id=vcs_id,
            upstream_port_index=1,
            vppb_counts=4,
            initial_bounds=initial_bounds,
            physical_ports=physical_ports,
            allocated_ld=allocated_ld,
        )

    with pytest.raises(Exception, match="Upstream Port Index is out of bound"):
        CxlVirtualSwitch(
            id=vcs_id,
            upstream_port_index=5,
            vppb_counts=vppb_counts,
            initial_bounds=initial_bounds,
            physical_ports=physical_ports,
            allocated_ld=allocated_ld,
        )


@pytest.mark.asyncio
async def test_virtual_switch_manager_run_and_stop(request):
    UnalignedBitStructure.make_quiet()

    vcs_id = 0
    upstream_port_index = 0
    vppb_counts = 3
    initial_bounds = [1, 2, -1]
    physical_ports = [
        UpstreamPortDevice(transport_connection=CxlConnection(), port_index=0),
        DownstreamPortDevice(transport_connection=CxlConnection(), port_index=1),
        DownstreamPortDevice(transport_connection=CxlConnection(), port_index=2),
        DownstreamPortDevice(transport_connection=CxlConnection(), port_index=3),
    ]
    allocated_ld = {}
    for index in range(vppb_counts):
        allocated_ld[index] = [0]

    # Add PPB relation
    ppb_devices = []
    ppb_bind_processors = []

    ppb = PpbDevice(1)
    bind = PpbDspBindProcessor(CxlConnection(), CxlConnection())
    physical_ports[1].set_ppb(ppb, bind)
    ppb_devices.append(ppb)
    ppb_bind_processors.append(bind)

    ppb = PpbDevice(2)
    bind = PpbDspBindProcessor(CxlConnection(), CxlConnection())
    physical_ports[2].set_ppb(ppb, bind)
    ppb_devices.append(ppb)
    ppb_bind_processors.append(bind)

    ppb = PpbDevice(3)
    bind = PpbDspBindProcessor(CxlConnection(), CxlConnection())
    physical_ports[3].set_ppb(ppb, bind)
    ppb_devices.append(ppb)
    ppb_bind_processors.append(bind)

    vcs = CxlVirtualSwitch(
        id=vcs_id,
        upstream_port_index=upstream_port_index,
        vppb_counts=vppb_counts,
        initial_bounds=initial_bounds,
        physical_ports=physical_ports,
        irq_port=8500 + request.config.PORT.TEST_1,
        allocated_ld=allocated_ld,
    )

    async def start_components():
        tasks = []
        tasks.append(create_task(vcs.run()))
        for port in physical_ports:
            tasks.append(create_task(port.run()))
        for ppb_bind_processor in ppb_bind_processors:
            tasks.append(create_task(ppb_bind_processor.run()))
        for ppb_device in ppb_devices:
            tasks.append(create_task(ppb_device.run()))
        await gather(*tasks)

    async def stop_components():
        await vcs.stop()
        for port in physical_ports:
            await port.stop()
        for ppb_bind_processor in ppb_bind_processors:
            await ppb_bind_processor.stop()
        for ppb_device in ppb_devices:
            await ppb_device.stop()

    async def wait_and_stop():
        wait_tasks = []
        wait_tasks.append(create_task(vcs.wait_for_ready()))
        for port in physical_ports:
            wait_tasks.append(create_task(port.wait_for_ready()))
        for ppb_bind_processor in ppb_bind_processors:
            wait_tasks.append(create_task(ppb_bind_processor.wait_for_ready()))
        for ppb_device in ppb_devices:
            wait_tasks.append(create_task(ppb_device.wait_for_ready()))
        await gather(*wait_tasks)

        with pytest.raises(Exception, match="port_index is out of bound"):
            await vcs.bind_vppb(port_index=4, vppb_index=1, ld_id=0)
        with pytest.raises(Exception, match="physical port 0 is not DSP"):
            await vcs.bind_vppb(port_index=0, vppb_index=1, ld_id=0)
        with pytest.raises(Exception, match="vPPB 4 is not bound to any physical port"):
            await vcs.unbind_vppb(vppb_index=4)
        await stop_components()

    tasks = [
        create_task(start_components()),
        create_task(wait_and_stop()),
    ]
    await gather(*tasks)


# Test initial bounds and runtime binding results are the same
@pytest.mark.asyncio
async def test_virtual_switch_manager_test_cxl_topology_bind_consistency():
    UnalignedBitStructure.make_quiet()

    vcs = None
    physical_ports = None
    root_port_device = None
    cxl_devices = None
    ppb_devices = None
    ppb_bind_processors = None

    base_address = 0xFE000000

    enum_info_initial_bound = None
    enum_info_runtime_binding = None

    async def start_components():
        tasks = []
        tasks.append(create_task(vcs.run()))
        for port in physical_ports:
            tasks.append(create_task(port.run()))
        for cxl_device in cxl_devices:
            tasks.append(create_task(cxl_device.run()))
        for ppb_bind_processor in ppb_bind_processors:
            tasks.append(create_task(ppb_bind_processor.run()))
        for ppb_device in ppb_devices:
            tasks.append(create_task(ppb_device.run()))
        await gather(*tasks)

    async def stop_components():
        await vcs.stop()
        for port in physical_ports:
            await port.stop()
        for cxl_device in cxl_devices:
            await cxl_device.stop()
        for ppb_bind_processor in ppb_bind_processors:
            await ppb_bind_processor.stop()
        for ppb_device in ppb_devices:
            await ppb_device.stop()

    async def wait_and_test_and_stop(bind: bool = False):
        wait_tasks = []
        wait_tasks.append(create_task(vcs.wait_for_ready()))
        for port in physical_ports:
            wait_tasks.append(create_task(port.wait_for_ready()))
        for cxl_device in cxl_devices:
            wait_tasks.append(create_task(cxl_device.wait_for_ready()))
        for ppb_bind_processor in ppb_bind_processors:
            wait_tasks.append(create_task(ppb_bind_processor.wait_for_ready()))
        for ppb_device in ppb_devices:
            wait_tasks.append(create_task(ppb_device.wait_for_ready()))
        await gather(*wait_tasks)

        if bind:
            await vcs.bind_vppb(1, 0, 0)
            await vcs.bind_vppb(2, 1, 0)
            await vcs.bind_vppb(3, 2, 0)
        await root_port_device.enumerate(base_address)
        if bind:
            nonlocal enum_info_runtime_binding
            enum_info_runtime_binding = await root_port_device.scan_devices()
        else:
            nonlocal enum_info_initial_bound
            enum_info_initial_bound = await root_port_device.scan_devices()
        await stop_components()

    logger.info("[PyTest] Testing initial bounds")
    (
        vcs,
        physical_ports,
        root_port_device,
        cxl_devices,
        _dsp_devices,
        ppb_devices,
        ppb_bind_processors,
    ) = create_cxl_topology(bind=True)

    tasks = [
        create_task(start_components()),
        create_task(wait_and_test_and_stop(bind=False)),
    ]
    await gather(*tasks)

    logger.info("[PyTest] Testing runtime binding")
    (
        vcs,
        physical_ports,
        root_port_device,
        cxl_devices,
        _dsp_devices,
        ppb_devices,
        ppb_bind_processors,
    ) = create_cxl_topology(bind=False)

    tasks = [
        create_task(start_components()),
        create_task(wait_and_test_and_stop(bind=True)),
    ]
    await gather(*tasks)

    # Compare initial bound and runtime binding results
    compare_enum_info(enum_info_runtime_binding, enum_info_initial_bound)


@pytest.mark.asyncio
async def test_virtual_switch_manager_test_cfg_routing():
    UnalignedBitStructure.make_quiet()

    (
        vcs,
        physical_ports,
        root_port_device,
        cxl_devices,
        _dsp_devices,
        ppb_devices,
        ppb_bind_processors,
    ) = create_cxl_topology(bind=True)

    base_address = 0xFE000000

    async def test_read_request(root_port_device: CxlRootPortDevice):
        test_table = [
            (create_bdf(1, 0, 0), 0xF0021DC5),
            (create_bdf(2, 0, 0), 0xF0031DC5),
            (create_bdf(2, 1, 0), 0xF0031DC5),
            (create_bdf(2, 2, 0), 0xF0031DC5),
            (create_bdf(3, 0, 0), 0xF0011DC5),
            (create_bdf(4, 0, 0), 0xF0011DC5),
            (create_bdf(5, 0, 0), 0xF0011DC5),
        ]

        for test_item in test_table:
            (bdf, vid_did_expected) = test_item
            logger.info(f"[PyTest] Testing VID/DID at {bdf_to_string(bdf)}")
            vid_did_received = await root_port_device.read_vid_did(bdf=bdf)
            assert vid_did_expected == vid_did_received
            if vid_did_received is not None:
                logger.info(
                    f"[PyTest] Received VID/DID:{vid_did_received:08x},"
                    "expected VID/DID:{vid_did_expected:08x}"
                )
            else:
                logger.info("[PyTest] Received VID/DID: None")

    async def start_components():
        tasks = []
        tasks.append(create_task(vcs.run()))
        for port in physical_ports:
            tasks.append(create_task(port.run()))
        for cxl_device in cxl_devices:
            tasks.append(create_task(cxl_device.run()))
        for ppb_bind_processor in ppb_bind_processors:
            tasks.append(create_task(ppb_bind_processor.run()))
        for ppb_device in ppb_devices:
            tasks.append(create_task(ppb_device.run()))
        await gather(*tasks)

    async def stop_components():
        await vcs.stop()
        for port in physical_ports:
            await port.stop()
        for cxl_device in cxl_devices:
            await cxl_device.stop()
        for ppb_bind_processor in ppb_bind_processors:
            await ppb_bind_processor.stop()
        for ppb_device in ppb_devices:
            await ppb_device.stop()

    async def wait_and_test_and_stop():
        wait_tasks = []
        wait_tasks.append(create_task(vcs.wait_for_ready()))
        for port in physical_ports:
            wait_tasks.append(create_task(port.wait_for_ready()))
        for cxl_device in cxl_devices:
            wait_tasks.append(create_task(cxl_device.wait_for_ready()))
        for ppb_bind_processor in ppb_bind_processors:
            wait_tasks.append(create_task(ppb_bind_processor.wait_for_ready()))
        for ppb_device in ppb_devices:
            wait_tasks.append(create_task(ppb_device.wait_for_ready()))
        await gather(*wait_tasks)

        await root_port_device.enumerate(base_address)
        await test_read_request(root_port_device)
        await stop_components()

    tasks = [
        create_task(start_components()),
        create_task(wait_and_test_and_stop()),
    ]
    await gather(*tasks)


@pytest.mark.asyncio
async def test_virtual_switch_manager_test_cfg_routing_oob():
    UnalignedBitStructure.make_quiet()

    (
        vcs,
        physical_ports,
        root_port_device,
        cxl_devices,
        _dsp_devices,
        ppb_devices,
        ppb_bind_processors,
    ) = create_cxl_topology(bind=True)

    base_address = 0xFE000000

    async def test_oob_request(root_port_device: CxlRootPortDevice):
        test_table = [
            create_bdf(1, 0, 1),
            create_bdf(2, 3, 0),
            create_bdf(2, 0, 1),
            create_bdf(3, 0, 1),
            create_bdf(3, 1, 0),
            create_bdf(4, 0, 1),
            create_bdf(4, 1, 0),
            create_bdf(5, 0, 1),
            create_bdf(5, 1, 0),
            create_bdf(6, 0, 0),
        ]

        for bdf in test_table:
            logger.info(f"[PyTest] Testing OOB at {bdf_to_string(bdf)}")
            vid_did = await root_port_device.read_vid_did(bdf=bdf)
            assert vid_did is None
            logger.info("[PyTest] Received expected unsupported completion")

    async def start_components():
        tasks = []
        tasks.append(create_task(vcs.run()))
        for port in physical_ports:
            tasks.append(create_task(port.run()))
        for cxl_device in cxl_devices:
            tasks.append(create_task(cxl_device.run()))
        for ppb_bind_processor in ppb_bind_processors:
            tasks.append(create_task(ppb_bind_processor.run()))
        for ppb_device in ppb_devices:
            tasks.append(create_task(ppb_device.run()))
        await gather(*tasks)

    async def stop_components():
        await vcs.stop()
        for port in physical_ports:
            await port.stop()
        for cxl_device in cxl_devices:
            await cxl_device.stop()
        for ppb_bind_processor in ppb_bind_processors:
            await ppb_bind_processor.stop()
        for ppb_device in ppb_devices:
            await ppb_device.stop()

    async def wait_and_test_and_stop():
        wait_tasks = []
        wait_tasks.append(create_task(vcs.wait_for_ready()))
        for port in physical_ports:
            wait_tasks.append(create_task(port.wait_for_ready()))
        for cxl_device in cxl_devices:
            wait_tasks.append(create_task(cxl_device.wait_for_ready()))
        for ppb_bind_processor in ppb_bind_processors:
            wait_tasks.append(create_task(ppb_bind_processor.wait_for_ready()))
        for ppb_device in ppb_devices:
            wait_tasks.append(create_task(ppb_device.wait_for_ready()))
        await gather(*wait_tasks)

        await root_port_device.enumerate(base_address)
        await test_oob_request(root_port_device)
        await stop_components()

    tasks = [
        create_task(start_components()),
        create_task(wait_and_test_and_stop()),
    ]
    await gather(*tasks)


@pytest.mark.asyncio
async def test_virtual_switch_manager_test_mmio_routing():
    UnalignedBitStructure.make_quiet()

    (
        vcs,
        physical_ports,
        root_port_device,
        cxl_devices,
        dsp_devices,
        ppb_devices,
        ppb_bind_processors,
    ) = create_cxl_topology(bind=True)

    base_address = 0xFE000000
    usp_memory_range = 0x100000
    dsp_memory_base = base_address + usp_memory_range
    dsp_memory_range = 0x200000

    async def test_mmio_request(root_port_device: CxlRootPortDevice, base_address: int):
        address = base_address
        data = 0xDEADBEEF

        # NOTE: Write 0xDEADBEEF
        await root_port_device.write_mmio(address, data)

        # NOTE: Confirm 0xDEADBEEF is written
        received_data = await root_port_device.read_mmio(address)
        assert received_data == data
        logger.info(f"[PyTest] Received expected 0xdeadbeef from {address:08x}")

        for index in range(len(dsp_devices)):
            address = dsp_memory_base + index * dsp_memory_range

            # NOTE: Write 0xDEADBEEF
            await root_port_device.write_mmio(address, data)

            # NOTE: Confirm 0xDEADBEEF is written
            received_data = await root_port_device.read_mmio(address)
            assert received_data == data
            logger.info(f"[PyTest] Received expected 0xdeadbeef from {address:08x}")

    async def start_components():
        tasks = []
        tasks.append(create_task(vcs.run()))
        for port in physical_ports:
            tasks.append(create_task(port.run()))
        for cxl_device in cxl_devices:
            tasks.append(create_task(cxl_device.run()))
        for ppb_bind_processor in ppb_bind_processors:
            tasks.append(create_task(ppb_bind_processor.run()))
        for ppb_device in ppb_devices:
            tasks.append(create_task(ppb_device.run()))
        await gather(*tasks)

    async def stop_components():
        await vcs.stop()
        for port in physical_ports:
            await port.stop()
        for cxl_device in cxl_devices:
            await cxl_device.stop()
        for ppb_bind_processor in ppb_bind_processors:
            await ppb_bind_processor.stop()
        for ppb_device in ppb_devices:
            await ppb_device.stop()

    async def wait_and_test_and_stop():
        wait_tasks = []
        wait_tasks.append(create_task(vcs.wait_for_ready()))
        for port in physical_ports:
            wait_tasks.append(create_task(port.wait_for_ready()))
        for cxl_device in cxl_devices:
            wait_tasks.append(create_task(cxl_device.wait_for_ready()))
        for ppb_bind_processor in ppb_bind_processors:
            wait_tasks.append(create_task(ppb_bind_processor.wait_for_ready()))
        for ppb_device in ppb_devices:
            wait_tasks.append(create_task(ppb_device.wait_for_ready()))
        await gather(*wait_tasks)

        exception = None
        try:
            await root_port_device.enumerate(base_address)
            await test_mmio_request(root_port_device, base_address)
        except Exception as e:
            exception = e
        await stop_components()
        if exception:
            raise exception

    tasks = [
        create_task(start_components()),
        create_task(wait_and_test_and_stop()),
    ]
    await gather(*tasks)


@pytest.mark.asyncio
async def test_virtual_switch_manager_test_mmio_routing_oob():
    UnalignedBitStructure.make_quiet()

    (
        vcs,
        physical_ports,
        root_port_device,
        cxl_devices,
        _dsp_devices,
        ppb_devices,
        ppb_bind_processors,
    ) = create_cxl_topology(bind=True)

    base_address = 0xFE000000

    async def test_mmio_oob(
        root_port_device: CxlRootPortDevice,
        mmio_enum_info: MmioEnumerationInfo,
    ):
        data = 0xDEADBEEF

        # NOTE: Write OOB (Lower Boundary)
        address = mmio_enum_info.memory_base - 4
        await root_port_device.write_mmio(address, data)

        # NOTE: Write OOB (Upper Boundary)
        address = mmio_enum_info.memory_limit + 4
        await root_port_device.write_mmio(address, data)

        # NOTE: Read OOB (Lower Boundary)
        address = mmio_enum_info.memory_base - 4
        data = await root_port_device.read_mmio(address)
        assert data == 0
        logger.info(f"[PyTest] Received expected OOB from {address}")

        # NOTE: Read OOB (Upper Boundary)
        address = mmio_enum_info.memory_limit + 4
        data = await root_port_device.read_mmio(address)
        assert data == 0
        logger.info(f"[PyTest] Received expected OOB from {address}")

        for bar_block in mmio_enum_info.bar_blocks:
            # NOTE: Write OOB (Lower Boundary)
            address = bar_block.memory_base - 4
            await root_port_device.write_mmio(address, data)

            # NOTE: Write OOB (Upper Boundary)
            address = bar_block.memory_limit + 4
            await root_port_device.write_mmio(address, data)

            # NOTE: Read OOB (Lower Boundary)
            address = bar_block.memory_base - 4
            data = await root_port_device.read_mmio(address)
            assert data == 0
            logger.info(f"[PyTest] Received expected OOB from 0x{address:08x}")

            # NOTE: Read OOB (Upper Boundary)
            address = bar_block.memory_limit + 4
            data = await root_port_device.read_mmio(address)
            assert data == 0
            logger.info(f"[PyTest] Received expected OOB from 0x{address:08x}")

    async def start_components():
        tasks = []
        tasks.append(create_task(vcs.run()))
        for port in physical_ports:
            tasks.append(create_task(port.run()))
        for cxl_device in cxl_devices:
            tasks.append(create_task(cxl_device.run()))
        for ppb_bind_processor in ppb_bind_processors:
            tasks.append(create_task(ppb_bind_processor.run()))
        for ppb_device in ppb_devices:
            tasks.append(create_task(ppb_device.run()))
        await gather(*tasks)

    async def stop_components():
        await vcs.stop()
        for port in physical_ports:
            await port.stop()
        for cxl_device in cxl_devices:
            await cxl_device.stop()
        for ppb_bind_processor in ppb_bind_processors:
            await ppb_bind_processor.stop()
        for ppb_device in ppb_devices:
            await ppb_device.stop()

    async def wait_and_test_and_stop():
        wait_tasks = []
        wait_tasks.append(create_task(vcs.wait_for_ready()))
        for port in physical_ports:
            wait_tasks.append(create_task(port.wait_for_ready()))
        for cxl_device in cxl_devices:
            wait_tasks.append(create_task(cxl_device.wait_for_ready()))
        for ppb_bind_processor in ppb_bind_processors:
            wait_tasks.append(create_task(ppb_bind_processor.wait_for_ready()))
        for ppb_device in ppb_devices:
            wait_tasks.append(create_task(ppb_device.wait_for_ready()))
        await gather(*wait_tasks)

        exception = None
        try:
            mmio_enum_info = await root_port_device.enumerate(base_address)
            await test_mmio_oob(root_port_device, mmio_enum_info)
        except Exception as e:
            exception = e
        await stop_components()
        if exception:
            raise exception

    tasks = [
        create_task(start_components()),
        create_task(wait_and_test_and_stop()),
    ]
    await gather(*tasks)


@pytest.mark.asyncio
async def test_virtual_switch_manager_test_bind_and_unbind():
    UnalignedBitStructure.make_quiet()
    memory_size = 0x100000

    (
        vcs,
        physical_ports,
        root_port_device,
        cxl_devices,
        _dsp_devices,
        ppb_devices,
        ppb_bind_processors,
    ) = create_cxl_topology(memory_size=memory_size)

    base_address = 0xFE000000

    async def start_components():
        tasks = []
        tasks.append(create_task(vcs.run()))
        for port in physical_ports:
            tasks.append(create_task(port.run()))
        for cxl_device in cxl_devices:
            tasks.append(create_task(cxl_device.run()))
        for ppb_bind_processor in ppb_bind_processors:
            tasks.append(create_task(ppb_bind_processor.run()))
        for ppb_device in ppb_devices:
            tasks.append(create_task(ppb_device.run()))
        await gather(*tasks)

    async def stop_components():
        await vcs.stop()
        for port in physical_ports:
            await port.stop()
        for cxl_device in cxl_devices:
            await cxl_device.stop()
        for ppb_bind_processor in ppb_bind_processors:
            await ppb_bind_processor.stop()
        for ppb_device in ppb_devices:
            await ppb_device.stop()

    async def bind_vppbs(vcs: CxlVirtualSwitch):
        await vcs.bind_vppb(1, 0, 0)
        await vcs.bind_vppb(2, 1, 0)
        await vcs.bind_vppb(3, 2, 0)

    async def unbind_vppbs(vcs: CxlVirtualSwitch):
        await vcs.unbind_vppb(0)
        await vcs.unbind_vppb(1)
        await vcs.unbind_vppb(2)

    async def wait_and_test_and_stop(vcs: CxlVirtualSwitch):
        wait_tasks = []
        wait_tasks.append(create_task(vcs.wait_for_ready()))
        for port in physical_ports:
            wait_tasks.append(create_task(port.wait_for_ready()))
        for cxl_device in cxl_devices:
            wait_tasks.append(create_task(cxl_device.wait_for_ready()))
        for ppb_bind_processor in ppb_bind_processors:
            wait_tasks.append(create_task(ppb_bind_processor.wait_for_ready()))
        for ppb_device in ppb_devices:
            wait_tasks.append(create_task(ppb_device.wait_for_ready()))
        await gather(*wait_tasks)

        exception = None
        try:
            await root_port_device.enumerate(base_address)
            enum_info_before_bind = await root_port_device.scan_devices()

            await bind_vppbs(vcs)
            enum_info_after_bind = await root_port_device.scan_devices()
            compare_enum_info(enum_info_before_bind, enum_info_after_bind, check_len=False)

            await unbind_vppbs(vcs)
            enum_info_after_unbind = await root_port_device.scan_devices()
            compare_enum_info(enum_info_after_bind, enum_info_after_unbind, check_len=False)
        except Exception as e:
            exception = e
        await stop_components()
        if exception:
            raise exception

    tasks = [
        create_task(start_components()),
        create_task(wait_and_test_and_stop(vcs)),
    ]
    await gather(*tasks)


@pytest.mark.asyncio
async def test_virtual_switch_manager_test_cxl_mem():
    UnalignedBitStructure.make_quiet()
    memory_size = 0x100000

    (
        vcs,
        physical_ports,
        root_port_device,
        cxl_devices,
        _dsp_devices,
        ppb_devices,
        ppb_bind_processors,
    ) = create_cxl_topology(memory_size=memory_size)

    base_address = 0xFE000000

    async def start_components():
        tasks = []
        tasks.append(create_task(vcs.run()))
        for port in physical_ports:
            tasks.append(create_task(port.run()))
        for cxl_device in cxl_devices:
            tasks.append(create_task(cxl_device.run()))
        for ppb_bind_processor in ppb_bind_processors:
            tasks.append(create_task(ppb_bind_processor.run()))
        for ppb_device in ppb_devices:
            tasks.append(create_task(ppb_device.run()))
        await gather(*tasks)

    async def stop_components():
        await vcs.stop()
        for port in physical_ports:
            await port.stop()
        for cxl_device in cxl_devices:
            await cxl_device.stop()
        for ppb_bind_processor in ppb_bind_processors:
            await ppb_bind_processor.stop()
        for ppb_device in ppb_devices:
            await ppb_device.stop()

    async def bind_vppbs(vcs: CxlVirtualSwitch):
        await vcs.bind_vppb(1, 0, 0)
        await vcs.bind_vppb(2, 1, 0)
        await vcs.bind_vppb(3, 2, 0)

    async def unbind_vppbs(vcs: CxlVirtualSwitch):
        await vcs.unbind_vppb(0)
        await vcs.unbind_vppb(1)
        await vcs.unbind_vppb(2)

    async def wait_and_test_and_stop(vcs: CxlVirtualSwitch):
        wait_tasks = []
        wait_tasks.append(create_task(vcs.wait_for_ready()))
        for port in physical_ports:
            wait_tasks.append(create_task(port.wait_for_ready()))
        for cxl_device in cxl_devices:
            wait_tasks.append(create_task(cxl_device.wait_for_ready()))
        for ppb_bind_processor in ppb_bind_processors:
            wait_tasks.append(create_task(ppb_bind_processor.wait_for_ready()))
        for ppb_device in ppb_devices:
            wait_tasks.append(create_task(ppb_device.wait_for_ready()))
        await gather(*wait_tasks)

        exception = None
        try:
            await bind_vppbs(vcs)
            await root_port_device.enumerate(base_address)
            enum_info_after_bind = await root_port_device.scan_devices()

            usp = enum_info_after_bind.devices[0]
            await root_port_device.enable_hdm_decoder(usp)

            cxl_hpa_base = 0x100000000
            await root_port_device.configure_hdm_decoder_single_device(usp, cxl_hpa_base)

            usp_cxl_devices = usp.get_all_cxl_devices()
            test_address = cxl_hpa_base
            for cxl_device in usp_cxl_devices:
                await root_port_device.cxl_mem_write(test_address, 0xDEADBEEF)
                data = await root_port_device.cxl_mem_read(test_address)
                assert data is not None, f"Failed to read from 0x{test_address:x}"
                logger.info(f"[PyTest] CXL.mem Read: 0x{data:x} from 0x{test_address:x}")
                test_address += cxl_device.cxl_device_size
            for cxl_device in usp_cxl_devices:
                await root_port_device.cxl_mem_birsp(CXL_MEM_M2SBIRSP_OPCODE.BIRSP_E, bi_id=3)
                await root_port_device.cxl_mem_birsp(CXL_MEM_M2SBIRSP_OPCODE.BIRSP_E, bi_id=4)
                await root_port_device.cxl_mem_birsp(CXL_MEM_M2SBIRSP_OPCODE.BIRSP_E, bi_id=5)

            await unbind_vppbs(vcs)
            enum_info_after_unbind = await root_port_device.scan_devices()
            compare_enum_info(enum_info_after_unbind, enum_info_after_bind, check_len=False)
        except Exception as e:
            exception = e
        await stop_components()
        if exception:
            raise exception

    tasks = [
        create_task(start_components()),
        create_task(wait_and_test_and_stop(vcs)),
    ]
    await gather(*tasks)
