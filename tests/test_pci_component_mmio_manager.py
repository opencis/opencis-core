"""
Copyright (c) 2024, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from unittest.mock import MagicMock
import pytest

from opencis.pci.component.mmio_manager import MmioManager, BarEntry
from opencis.pci.component.fifo_pair import FifoPair
from opencis.cxl.transport.transaction import CxlIoMemRdPacket, CxlIoMemWrPacket


def test_mmio_manager():
    upstream_fifo = FifoPair()
    bar_entry = BarEntry()
    mmio_manager = MmioManager(upstream_fifo)

    expected_size = 0
    bar_entry.register = None
    size = mmio_manager.get_bar_size(1)
    mmio_manager.set_bar_entries([bar_entry])
    assert expected_size == size

    expected_size = 0
    bar_entry.register = None
    mmio_manager.set_bar_entries([bar_entry])
    size = mmio_manager.get_bar_size(0)
    assert expected_size == size

    expected_size = 0x1000
    bar_entry.register = MagicMock()
    bar_entry.register.__len__.return_value = expected_size - 1
    mmio_manager.set_bar_entries([bar_entry])
    size = mmio_manager.get_bar_size(0)
    assert expected_size == size

    expected_size = 0x2000
    bar_entry.register = MagicMock()
    bar_entry.register.__len__.return_value = expected_size - 0x100
    mmio_manager.set_bar_entries([bar_entry])
    size = mmio_manager.get_bar_size(0)
    assert expected_size == size

    expected_value = None
    bar_entry.register = None
    mmio_manager.set_bar_entries([bar_entry])
    value = mmio_manager.get_bar_info(1)
    assert expected_value == value

    expected_value = bar_entry.info
    mmio_manager.set_bar_entries([bar_entry])
    value = mmio_manager.get_bar_info(0)
    assert expected_value == value

    expected_value = bar_entry.base_address
    mmio_manager.set_bar(1, 0x1000)
    assert bar_entry.base_address == expected_value

    expected_value = 0x1000
    mmio_manager.set_bar(0, expected_value)
    assert bar_entry.base_address == expected_value


@pytest.mark.asyncio
async def test_mmio_manager_write():
    # pylint: disable=protected-access
    upstream_fifo = FifoPair()
    bar_entry = BarEntry()
    mmio_manager = MmioManager(upstream_fifo)
    mmio_manager.set_bar_entries([bar_entry])

    bar_entry.base_address = 0
    bar_entry.register = MagicMock()
    packet = CxlIoMemWrPacket.create(addr=0, length=4, data=0xF)
    await upstream_fifo.host_to_target.put(packet)
    await mmio_manager._process_host_to_target(run_once=True)
    assert upstream_fifo.host_to_target.qsize() == 0
    bar_entry.register.write_bytes.assert_not_called()

    # bar_entry.base_address = 0x1000
    # bar_entry.register = None
    # address = 0x1000
    # size = 4
    # value = 0xF
    # mmio_manager.write_mmio(address, size, value)

    # bar_entry.base_address = 0x1000
    # bar_entry.register = MagicMock()
    # address = 0x1000 - 1
    # size = 4
    # value = 0xF
    # mmio_manager.write_mmio(address, size, value)
    # bar_entry.register.write_bytes.assert_not_called()

    # bar_entry.base_address = 0x1000
    # bar_entry.register = MagicMock()
    # address = 0x1000
    # size = 4
    # value = 0xF
    # mmio_manager.write_mmio(address, size, value)
    # bar_entry.register.write_bytes.assert_not_called()

    # bar_entry.base_address = 0x1000
    # bar_entry.register = MagicMock()
    # bar_entry.register.__len__.return_value = 0x10
    # address = 0x1000
    # size = 4
    # value = 0xF
    # mmio_manager.write_mmio(address, size, value)
    # bar_entry.register.write_bytes.assert_called_with(0, size - 1, value)


class BytesLikeMock(MagicMock):
    def to_bytes(self, *args, **kwargs):
        return int(self).to_bytes(*args, **kwargs)


@pytest.mark.asyncio
async def test_mmio_manager_read():
    # pylint: disable=protected-access
    upstream_fifo = FifoPair()
    bar_entry = BarEntry()
    mmio_manager = MmioManager(upstream_fifo)
    mmio_manager.set_bar_entries([bar_entry])

    # Test when base address is 0
    bar_entry.base_address = 0
    bar_entry.register = None
    packet = CxlIoMemRdPacket.create(addr=0, length=4)
    await upstream_fifo.host_to_target.put(packet)
    await mmio_manager._process_host_to_target(run_once=True)
    assert upstream_fifo.host_to_target.qsize() == 0
    assert upstream_fifo.target_to_host.qsize() == 1
    await upstream_fifo.target_to_host.get()

    # Test when register is empty
    bar_entry.base_address = 0x1000
    bar_entry.register = None
    packet = CxlIoMemRdPacket.create(addr=0x1000, length=4)
    await upstream_fifo.host_to_target.put(packet)
    await mmio_manager._process_host_to_target(run_once=True)
    assert upstream_fifo.host_to_target.qsize() == 0
    assert upstream_fifo.target_to_host.qsize() == 1
    await upstream_fifo.target_to_host.get()

    # Test when address is out of bound
    bar_entry.base_address = 0x1000
    bar_entry.register = BytesLikeMock()
    bar_entry.register.__len__.return_value = 0x10
    packet = CxlIoMemRdPacket.create(addr=0x1000 - 1, length=4)
    await upstream_fifo.host_to_target.put(packet)
    await mmio_manager._process_host_to_target(run_once=True)
    assert upstream_fifo.host_to_target.qsize() == 0
    bar_entry.register.read_bytes.assert_not_called()
    assert upstream_fifo.target_to_host.qsize() == 1
    await upstream_fifo.target_to_host.get()

    # Test when address is valid
    bar_entry.base_address = 0x1000
    bar_entry.register = BytesLikeMock()
    bar_entry.register.__len__.return_value = 0x10
    packet = CxlIoMemRdPacket.create(addr=0x1000, length=4)
    await upstream_fifo.host_to_target.put(packet)
    await mmio_manager._process_host_to_target(run_once=True)
    assert upstream_fifo.host_to_target.qsize() == 0
    bar_entry.register.read_bytes.assert_called_with(0, 3)
    assert upstream_fifo.target_to_host.qsize() == 1
    await upstream_fifo.target_to_host.get()
