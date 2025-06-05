"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from asyncio import gather, create_task
from typing import cast
import pytest


from opencis.util.logger import logger
from opencis.util.pci import create_bdf
from opencis.pci.device.pci_device import PciDevice, PciComponentIdentity
from opencis.pci.component.pci_connection import PciConnection
from opencis.pci.component.pci import (
    EEUM_VID,
    SW_EP_DID,
    PCI_CLASS,
    PCI_SYSTEM_PERIPHERAL_SUBCLASS,
)
from opencis.cxl.transport.transaction import (
    CxlIoCfgRdPacket,
    CxlIoCfgWrPacket,
    CxlIoMemRdPacket,
    CxlIoMemWrPacket,
    CxlIoCompletionWithDataPacket,
    is_cxl_io_completion_status_sc,
    is_cxl_io_completion_status_ur,
)


def test_pci_device():
    transport_connection = PciConnection()
    PciDevice(transport_connection=transport_connection)


@pytest.mark.asyncio
async def test_pci_device_run_stop():
    transport_connection = PciConnection()
    identity = PciComponentIdentity(
        vendor_id=EEUM_VID,
        device_id=SW_EP_DID,
        base_class_code=PCI_CLASS.SYSTEM_PERIPHERAL,
        sub_class_coce=PCI_SYSTEM_PERIPHERAL_SUBCLASS.OTHER,
    )
    device = PciDevice(
        transport_connection=transport_connection, identity=identity, label="TestDevice"
    )

    async def wait_and_stop():
        await device.wait_for_ready()
        await device.stop()

    tasks = [create_task(device.run()), create_task(wait_and_stop())]
    await gather(*tasks)


@pytest.mark.asyncio
async def test_pci_device_run_stop_without_label():
    transport_connection = PciConnection()
    identity = PciComponentIdentity(
        vendor_id=EEUM_VID,
        device_id=SW_EP_DID,
        base_class_code=PCI_CLASS.SYSTEM_PERIPHERAL,
        sub_class_coce=PCI_SYSTEM_PERIPHERAL_SUBCLASS.OTHER,
    )
    device = PciDevice(transport_connection=transport_connection, identity=identity)

    async def wait_and_stop():
        await device.wait_for_ready()
        await device.stop()

    tasks = [create_task(device.run()), create_task(wait_and_stop())]
    await gather(*tasks)


@pytest.mark.asyncio
async def test_pci_device_config_space():
    transport_connection = PciConnection()
    identity = PciComponentIdentity(
        vendor_id=EEUM_VID,
        device_id=SW_EP_DID,
        base_class_code=PCI_CLASS.SYSTEM_PERIPHERAL,
        sub_class_coce=PCI_SYSTEM_PERIPHERAL_SUBCLASS.OTHER,
    )
    bar_size = 4096
    device = PciDevice(
        transport_connection=transport_connection,
        identity=identity,
        label="TestDevice",
        bar_size=bar_size,
    )

    async def test_config_space(transport_connection: PciConnection):
        # NOTE: Test Config Space Type0 Read - VID/DID
        logger.info("[PyTest] Testing Config Space Type0 Read (VID/DID)")
        packet = CxlIoCfgRdPacket.create(create_bdf(0, 0, 0), 0, 4, is_type0=True)

        await transport_connection.cfg_fifo.host_to_target.put(packet)
        packet = await transport_connection.cfg_fifo.target_to_host.get()
        assert is_cxl_io_completion_status_sc(packet)
        cpld_packet = cast(CxlIoCompletionWithDataPacket, packet)
        assert cpld_packet.data == (EEUM_VID | (SW_EP_DID << 16))

        # NOTE: Test Config Space Type0 Write - BAR WRITE
        logger.info("[PyTest] Testing Config Space Type0 Write (BAR)")
        packet = CxlIoCfgWrPacket.create(create_bdf(0, 0, 0), 0x10, 4, 0xFFFFFFFF, is_type0=True)
        await transport_connection.cfg_fifo.host_to_target.put(packet)
        packet = await transport_connection.cfg_fifo.target_to_host.get()
        assert is_cxl_io_completion_status_sc(packet)

        # NOTE: Test Config Space Type0 Read - BAR READ
        logger.info("[PyTest] Testing Config Space Type0 Read (BAR)")
        packet = CxlIoCfgRdPacket.create(create_bdf(0, 0, 0), 0x10, 4, is_type0=True)
        await transport_connection.cfg_fifo.host_to_target.put(packet)
        packet = await transport_connection.cfg_fifo.target_to_host.get()
        assert is_cxl_io_completion_status_sc(packet)
        cpld_packet = cast(CxlIoCompletionWithDataPacket, packet)
        size = 0xFFFFFFFF - cpld_packet.data + 1
        assert size == bar_size

        # NOTE: Test Config Space Type1 Read - VID/DID: Expect UR
        logger.info("[PyTest] Testing Config Space Type1 Read - Expect UR")
        packet = CxlIoCfgRdPacket.create(create_bdf(0, 0, 0), 0, 4, is_type0=False)
        await transport_connection.cfg_fifo.host_to_target.put(packet)
        packet = await transport_connection.cfg_fifo.target_to_host.get()
        assert is_cxl_io_completion_status_ur(packet)

        # NOTE: Test Config Space Type1 Write - BAR WRITE: Expect UR
        logger.info("[PyTest] Testing Config Space Type1 Write - Expect UR")
        packet = CxlIoCfgWrPacket.create(create_bdf(0, 0, 0), 0x10, 4, 0xFFFFFFFF, is_type0=False)
        await transport_connection.cfg_fifo.host_to_target.put(packet)
        packet = await transport_connection.cfg_fifo.target_to_host.get()
        assert is_cxl_io_completion_status_ur(packet)

    async def wait_test_stop():
        await device.wait_for_ready()
        await test_config_space(transport_connection)
        await device.stop()

    tasks = [create_task(device.run()), create_task(wait_test_stop())]
    await gather(*tasks)


@pytest.mark.asyncio
async def test_pci_device_mmio():
    transport_connection = PciConnection()
    identity = PciComponentIdentity(
        vendor_id=EEUM_VID,
        device_id=SW_EP_DID,
        base_class_code=PCI_CLASS.SYSTEM_PERIPHERAL,
        sub_class_coce=PCI_SYSTEM_PERIPHERAL_SUBCLASS.OTHER,
    )
    bar_size = 4096
    device = PciDevice(
        transport_connection=transport_connection,
        identity=identity,
        label="TestDevice",
        bar_size=bar_size,
    )
    base_addresss = 0x1000000

    async def configure_bar(transport_connection: PciConnection):
        logger.info("[PyTest] Setting BAR Address")
        # NOTE: Test Config Space Type0 Write - BAR WRITE
        packet = CxlIoCfgWrPacket.create(
            create_bdf(0, 0, 0), 0x10, 4, value=base_addresss, is_type0=True
        )
        await transport_connection.cfg_fifo.host_to_target.put(packet)
        packet = await transport_connection.cfg_fifo.target_to_host.get()
        assert is_cxl_io_completion_status_sc(packet)

    async def test_mmio(transport_connection: PciConnection):
        logger.info("[PyTest] Accessing MMIO register")
        # NOTE: Write 0xDEADBEEF
        data = 0xDEADBEEF
        packet = CxlIoMemWrPacket.create(base_addresss, 4, data=data)
        await transport_connection.mmio_fifo.host_to_target.put(packet)

        # NOTE: Confirm 0xDEADBEEF is written
        packet = CxlIoMemRdPacket.create(base_addresss, 4)
        await transport_connection.mmio_fifo.host_to_target.put(packet)
        packet = await transport_connection.mmio_fifo.target_to_host.get()
        assert is_cxl_io_completion_status_sc(packet)
        cpld_packet = cast(CxlIoCompletionWithDataPacket, packet)
        assert cpld_packet.data == data

        # NOTE: Write OOB (Upper Boundary), Expect No Error
        packet = CxlIoMemWrPacket.create(base_addresss + bar_size, 4, data=data)
        await transport_connection.mmio_fifo.host_to_target.put(packet)

        # NOTE: Write OOB (Lower Boundary), Expect No Error
        packet = CxlIoMemWrPacket.create(base_addresss - 4, 4, data=data)
        await transport_connection.mmio_fifo.host_to_target.put(packet)

        # NOTE: Read OOB (Upper Boundary), Expect 0
        packet = CxlIoMemRdPacket.create(base_addresss + bar_size, 4)
        await transport_connection.mmio_fifo.host_to_target.put(packet)
        packet = await transport_connection.mmio_fifo.target_to_host.get()
        assert is_cxl_io_completion_status_sc(packet)
        cpld_packet = cast(CxlIoCompletionWithDataPacket, packet)
        assert cpld_packet.data == 0

        # NOTE: Read OOB (Lower Boundary), Expect 0
        packet = CxlIoMemRdPacket.create(base_addresss - 4, 4)
        await transport_connection.mmio_fifo.host_to_target.put(packet)
        packet = await transport_connection.mmio_fifo.target_to_host.get()
        assert is_cxl_io_completion_status_sc(packet)
        cpld_packet = cast(CxlIoCompletionWithDataPacket, packet)
        assert cpld_packet.data == 0

    async def wait_test_stop():
        await device.wait_for_ready()
        await configure_bar(transport_connection)
        await test_mmio(transport_connection)
        await device.stop()

    tasks = [create_task(device.run()), create_task(wait_test_stop())]
    await gather(*tasks)
