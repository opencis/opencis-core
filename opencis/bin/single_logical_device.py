"""
 Copyright (c) 2024, Eeum, Inc.

 This software is licensed under the terms of the Revised BSD License.
 See LICENSE for details.
"""

import asyncio
from typing import List
import humanfriendly
import click

from opencis.util.logger import logger
from opencis.cxl.environment import parse_cxl_environment
from opencis.apps.single_logical_device import SingleLogicalDevice


@click.group(name="sld")
def sld_group():
    """Command group for managing single logical devices."""


async def run_devices(slds: List[SingleLogicalDevice]):
    try:
        await asyncio.gather(*(sld.run() for sld in slds))
    except Exception as e:
        logger.error("Error while running Single Logical Device", exc_info=e)
    finally:
        await asyncio.gather(*(sld.stop() for sld in slds))


def start_group(config_file):
    logger.info(f"Starting CXL Single Logical Device Group - Config: {config_file}")
    cxl_env = parse_cxl_environment(config_file)
    slds = []
    for device_config in cxl_env.single_logical_device_configs:
        sld = SingleLogicalDevice(
            port_index=device_config.port_index,
            memory_size=device_config.memory_size,
            memory_file=device_config.memory_file,
            serial_number=device_config.serial_number,
            host=cxl_env.switch_config.host,
            port=cxl_env.switch_config.port,
        )
        slds.append(sld)
    asyncio.run(run_devices(slds))


@sld_group.command(name="start")
@click.option("--port", default=1, help="Port number for the service.", show_default=True)
@click.option("--memfile", type=str, default=None, help="Memory file name.")
@click.option("--memsize", type=str, default="256M", help="Memory file size.")
def start(port, memfile, memsize):
    logger.info(f"Starting CXL Single Logical Device at port {port}")
    if memfile is None:
        memfile = f"mem{port}.bin"
    memsize = humanfriendly.parse_size(memsize, binary=True)
    sld = SingleLogicalDevice(port, memsize, memfile)
    asyncio.run(sld.run())
