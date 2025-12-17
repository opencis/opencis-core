"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

import asyncio
import click
from opencis.util.logger import logger
from opencis.apps.cxl_switch import CxlSwitch
from opencis.cxl.environment import parse_cxl_environment, CxlEnvironment


# Switch command group
@click.group(name="switch")
def switch_group():
    """Command group for CXL Switch."""


@switch_group.command(name="start")
@click.argument("config_file", type=click.Path(exists=True))
def start(config_file):
    """Run the CXL Switch with the given configuration file."""
    logger.info(f"Starting CXL Switch - Config: {config_file}")
    try:
        environment: CxlEnvironment = parse_cxl_environment(config_file)
    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        return

    switch = CxlSwitch(environment.switch_config, environment.logical_device_configs)
    try:
        asyncio.run(switch.run())
    except SystemExit:
        # Signal handler called sys.exit() - process is terminating, don't try to stop
        # in a new event loop as it would fail with "bound to different event loop"
        pass
    except Exception as e:
        logger.error("Error while running CXL Switch", exc_info=e)
        try:
            asyncio.run(switch.stop())
        except Exception as stop_e:
            logger.error("Error while stopping CXL Switch", exc_info=stop_e)
