"""
Copyright (c) 2024, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from asyncio import gather, create_task
import pytest

from opencis.cxl.device.downstream_port_device import (
    DownstreamPortDevice,
    CXL_COMPONENT_TYPE,
)
from opencis.cxl.component.cxl_connection import CxlConnection


def test_downstream_port_device():
    transport_connection = CxlConnection()
    device = DownstreamPortDevice(transport_connection=transport_connection, port_index=0)
    assert device.get_device_type() == CXL_COMPONENT_TYPE.DSP


@pytest.mark.asyncio
async def test_downstream_port_device_run_stop():
    transport_connection = CxlConnection()
    device = DownstreamPortDevice(transport_connection=transport_connection, port_index=0)

    async def wait_and_stop():
        await device.wait_for_ready()
        await device.stop()

    tasks = [create_task(device.run()), create_task(wait_and_stop())]
    await gather(*tasks)
