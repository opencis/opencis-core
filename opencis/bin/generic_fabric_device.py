"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

import asyncio
from typing import List
import click

from opencis.util.logger import logger
from opencis.cxl.environment import parse_cxl_environment
from opencis.apps.generic_fabric_device import GenericFabricDevice


@click.group(name="gfd")
def gfd_group():
    """Command group for managing generic fabric devices."""


async def run_devices(gfds: List[GenericFabricDevice]):
    try:
        await asyncio.gather(*(gfd.run() for gfd in gfds))
    except Exception as e:
        logger.error("Error while running Generic Fabric Device", exc_info=e)
    finally:
        try:
            await asyncio.gather(*(gfd.stop() for gfd in gfds))
        except Exception as e:
            logger.error("Error while stopping Generic Fabric Device", exc_info=e)


def start_group(config_file):
    logger.info(f"Starting CXL Generic Fabric Device Group - Config: {config_file}")
    cxl_env = parse_cxl_environment(config_file)
    gfds = []
    for device_config in cxl_env.generic_fabric_device_configs:
        gfd = GenericFabricDevice(
            port_index=device_config.port_index,
            serial_number=device_config.serial_number,
            host=cxl_env.switch_config.host,
            port=cxl_env.switch_config.port,
        )
        gfds.append(gfd)
    asyncio.run(run_devices(gfds))


@gfd_group.command(name="start")
@click.option("--port", default=1, help="Port number for the service.", show_default=True)
def start(port):
    logger.info(f"Starting CXL Generic Fabric Device at port {port}")
    gfd = GenericFabricDevice(port_index=port, serial_number="0000000000000001")
    asyncio.run(gfd.run())
