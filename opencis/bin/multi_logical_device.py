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
from opencis.apps.multi_logical_device import MultiLogicalDevice


@click.group(name="mld")
def mld_group():
    """Command group for managing single logical devices."""


async def run_devices(mlds: List[MultiLogicalDevice]):
    try:
        await asyncio.gather(*(mld.run() for mld in mlds))
    except Exception as e:
        logger.error(
            "An error occurred while running the Single Logical Device clients.",
            exc_info=e,
        )
    finally:
        await asyncio.gather(*(mld.stop() for mld in mlds))


def start_group(config_file):
    logger.info(f"Starting CXL Multi Logical Device Group - Config: {config_file}")
    cxl_env = parse_cxl_environment(config_file)
    mlds = []
    for device_config in cxl_env.multi_logical_device_configs:
        mld = MultiLogicalDevice(
            port_index=device_config.port_index,
            memory_sizes=device_config.memory_sizes,
            memory_files=device_config.memory_files,
            serial_numbers=device_config.serial_numbers,
            host=cxl_env.switch_config.host,
            port=cxl_env.switch_config.port,
        )
        mlds.append(mld)
    asyncio.run(run_devices(mlds))


@mld_group.command(name="start")
@click.option("--port", default=1, help="Port number for the service.", show_default=True)
@click.option("--memfile", type=str, default=None, help="Memory file name.")
@click.option("--memsize", type=str, default="256M", help="Memory file size.")
def start(port, memfile, memsize):
    logger.info(f"Starting CXL Single Logical Device at port {port}")
    if memfile is None:
        memfile = f"mld-mem{port}.bin"
    memsize = humanfriendly.parse_size(memsize, binary=True)
    mld = MultiLogicalDevice(port, memsize, memfile, serial_numbers=[])
    asyncio.run(mld.run())
