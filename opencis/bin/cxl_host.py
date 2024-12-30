"""
 Copyright (c) 2024, Eeum, Inc.

 This software is licensed under the terms of the Revised BSD License.
 See LICENSE for details.
"""

import asyncio
import click

from opencis.util.logger import logger
from opencis.cxl.environment import parse_cxl_environment
from opencis.cxl.component.cxl_component import PORT_TYPE
from opencis.apps.memory_pooling import run_host


@click.group(name="host")
def host_group():
    """Command group for managing CXL Host"""


def start(port: int = 0):
    logger.info(f"Starting CXL Host on Port{port}")
    asyncio.run(run_host(port_index=port, irq_port=8500))


async def run_host_group(ports):
    irq_port = 8500
    tasks = []
    for idx in ports:
        tasks.append(
            asyncio.create_task(
                run_host(
                    port_index=idx,
                    irq_port=irq_port,
                )
            )
        )
        irq_port += 1
    await asyncio.gather(*tasks)


def start_group(config_file: str):
    logger.info(f"Starting CXL Host Group - Config: {config_file}")
    try:
        environment = parse_cxl_environment(config_file)
    except Exception as e:
        logger.error(f"Failed to parse environment configuration: {e}")
        return

    ports = []
    for idx, port_config in enumerate(environment.switch_config.port_configs):
        if port_config.type == PORT_TYPE.USP:
            ports.append(idx)
    asyncio.run(run_host_group(ports))
