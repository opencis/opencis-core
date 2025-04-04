"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from asyncio import gather, create_task
import pytest

from opencis.apps.multiheaded_single_logical_device import MultiHeadedSingleLogicalDevice
from opencis.cxl.device.root_port_device import CxlRootPortDevice
from opencis.cxl.component.cxl_connection import CxlConnection
from opencis.util.memory import get_memory_bin_name
from opencis.util.number_const import MB

# Test with 4 ports
num_ports = 4


def test_multiheaded_single_logical_device():
    memory_size = 256 * MB
    memory_file = get_memory_bin_name()
    transport_connection = CxlConnection()
    MultiHeadedSingleLogicalDevice(
        num_ports,
        memory_size=memory_size,
        memory_file=memory_file,
        serial_number="AAAAAAAAAAAAAAAA",
        test_mode=True,
        cxl_connection=transport_connection,
    )


@pytest.mark.asyncio
async def test_multiheaded_single_logical_device_run_stop(get_gold_std_reg_vals):
    memory_size = 256 * MB
    memory_file = get_memory_bin_name()
    transport_connection = CxlConnection()
    mhsld_device = MultiHeadedSingleLogicalDevice(
        num_ports,
        memory_size=memory_size,
        memory_file=memory_file,
        serial_number="AAAAAAAAAAAAAAAA",
        test_mode=True,
        cxl_connection=transport_connection,
    )

    # check register values after initialization
    for sld_device in mhsld_device.get_sld_devices():
        reg_vals = str(sld_device.get_reg_vals())
        reg_vals_expected = get_gold_std_reg_vals("SLD")
        assert reg_vals == reg_vals_expected

    async def wait_and_stop():
        await mhsld_device.wait_for_ready()
        await mhsld_device.stop()

    tasks = [create_task(mhsld_device.run()), create_task(wait_and_stop())]
    await gather(*tasks)


@pytest.mark.asyncio
async def test_multiheaded_single_logical_device_enumeration():
    memory_size = 256 * MB
    memory_file = get_memory_bin_name()
    transport_connection = CxlConnection()
    root_port_device = CxlRootPortDevice(downstream_connection=transport_connection, label="Port0")
    mhsld_device = MultiHeadedSingleLogicalDevice(
        num_ports,
        memory_size=memory_size,
        memory_file=memory_file,
        serial_number="AAAAAAAAAAAAAAAA",
        test_mode=True,
        cxl_connection=transport_connection,
    )
    memory_base_address = 0xFE000000

    async def wait_and_stop():
        await mhsld_device.wait_for_ready()
        await root_port_device.enumerate(memory_base_address)
        await mhsld_device.stop()

    tasks = [create_task(mhsld_device.run()), create_task(wait_and_stop())]
    await gather(*tasks)
