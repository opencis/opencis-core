"""
 Copyright (c) 2024, Eeum, Inc.

 This software is licensed under the terms of the Revised BSD License.
 See LICENSE for details.
"""

import asyncio
from enum import Enum
from typing import List
import click

from opencis.util.logger import logger
from opencis.cxl.environment import parse_cxl_environment
from opencis.apps.accelerator import MyType1Accelerator, MyType2Accelerator


class ACCEL_TYPE(Enum):
    T1 = 1
    T2 = 2


@click.group(name="accel")
def accel_group():
    """Command group for managing logical devices."""


async def run_devices(accels: List[MyType1Accelerator | MyType2Accelerator]):
    try:
        await asyncio.gather(*(accel.run() for accel in accels))
    except Exception as e:
        logger.error("Error while running Accelerator Device", exc_info=e)
    finally:
        await asyncio.gather(*(accel.stop() for accel in accels))


def start_group(config_file, dev_type):
    logger.info(f"Starting CXL Accelerator Group - Config: {config_file}")
    cxl_env = parse_cxl_environment(config_file)
    accels = []
    for device_config in cxl_env.logical_device_configs:
        if dev_type == ACCEL_TYPE.T1:
            accel = MyType1Accelerator(
                port_index=device_config.port_index,
                host=cxl_env.switch_config.host,
                port=cxl_env.switch_config.port,
            )
        elif dev_type == ACCEL_TYPE.T2:
            accel = MyType2Accelerator(
                port_index=device_config.port_index,
                memory_size=device_config.memory_size,
                memory_file=device_config.memory_file,
                host=cxl_env.switch_config.host,
                port=cxl_env.switch_config.port,
            )
        else:
            raise Exception("Invalid Aceelerator Type")
        accels.append(accel)
    asyncio.run(run_devices(accels))
