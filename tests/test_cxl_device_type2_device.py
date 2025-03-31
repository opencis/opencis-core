"""
 Copyright (c) 2024, Eeum, Inc.

 This software is licensed under the terms of the Revised BSD License.
 See LICENSE for details.
"""

# pylint: disable=duplicate-code
from asyncio import gather, create_task
import pytest

from opencis.cxl.device.cxl_type2_device import (
    CxlType2Device,
    CxlType2DeviceConfig,
)
from opencis.cxl.device.root_port_device import CxlRootPortDevice
from opencis.cxl.component.cxl_connection import CxlConnection
from opencis.util.memory import get_memory_bin_name
from opencis.util.number_const import MB


def test_type2_device():
    device_config = CxlType2DeviceConfig(
        device_name="CXLType2Device",
        transport_connection=CxlConnection(),
        memory_size=256 * MB,
        memory_file=get_memory_bin_name(),
    )
    CxlType2Device(device_config)


@pytest.mark.asyncio
async def test_type2_device_run_stop(get_gold_std_reg_vals):
    device_config = CxlType2DeviceConfig(
        device_name="CXLType2Device",
        transport_connection=CxlConnection(),
        memory_size=256 * MB,
        memory_file=get_memory_bin_name(),
    )
    device = CxlType2Device(device_config)

    # check register values after initialization
    reg_vals = str(device.get_reg_vals())
    reg_vals_expected = get_gold_std_reg_vals("ACCEL_TYPE_2")
    assert reg_vals == reg_vals_expected

    async def wait_and_stop():
        await device.wait_for_ready()
        await device.stop()

    tasks = [create_task(device.run()), create_task(wait_and_stop())]
    await gather(*tasks)


@pytest.mark.asyncio
async def test_type2_device_enumeration():
    transport_connection = CxlConnection()
    device_config = CxlType2DeviceConfig(
        device_name="CXLType2Device",
        transport_connection=transport_connection,
        memory_size=256 * MB,
        memory_file=get_memory_bin_name(),
    )
    root_port_device = CxlRootPortDevice(downstream_connection=transport_connection, label="Port0")
    device = CxlType2Device(device_config)
    memory_base_address = 0xFE000000

    async def wait_and_stop():
        await device.wait_for_ready()
        await root_port_device.enumerate(memory_base_address)
        await device.stop()

    tasks = [create_task(device.run()), create_task(wait_and_stop())]
    await gather(*tasks)
