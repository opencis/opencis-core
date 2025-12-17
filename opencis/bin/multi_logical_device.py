"""
Copyright (c) 2024-2025, Eeum, Inc.

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
        # Start the MLD manager socket server
        from opencis.cxl.component.mld_manager import mld_manager

        await mld_manager.start_socket_server()

        await asyncio.gather(*(mld.run() for mld in mlds))
    except Exception as e:
        logger.error(
            "An error occurred while running the Single Logical Device clients.",
            exc_info=e,
        )
    finally:
        try:
            # Stop the socket server
            from opencis.cxl.component.mld_manager import mld_manager

            await mld_manager.stop_socket_server()

            await asyncio.gather(*(mld.stop() for mld in mlds))
        except Exception as e:
            logger.error("Error while stopping Multi Logical Device", exc_info=e)


def start_group(config_file):
    logger.info(f"Starting CXL Multi Logical Device Group - Config: {config_file}")
    cxl_env = parse_cxl_environment(config_file)
    mlds = []

    # Import the MLD manager
    from opencis.cxl.component.mld_manager import mld_manager

    for device_config in cxl_env.multi_logical_device_configs:
        # Always create MLD instances, even with empty logical devices
        # This allows for dynamic LD creation at runtime
        if not device_config.ld_list:
            logger.info(
                f"Creating MLD instance for port {device_config.port_index} "
                "with empty logical devices (ready for dynamic allocation)"
            )

        # Use device_config directly - it's already a MultiLogicalDeviceConfig
        mld = MultiLogicalDevice(device_config)

        # Register the MLD instance with the global manager
        mld_manager.register_mld(device_config.port_index, mld)

        mlds.append(mld)

    # Always start the MLD manager socket server, even if there are no MLD instances
    # This is needed for dynamic LD creation
    if mlds:
        asyncio.run(run_devices(mlds))
    else:
        # Start just the socket server without any MLD instances
        logger.info(
            "No MLD instances to start, but starting MLD manager socket server "
            "for dynamic LD creation"
        )

        async def run_socket_server_only():
            try:
                # Start the MLD manager socket server
                from opencis.cxl.component.mld_manager import mld_manager

                await mld_manager.start_socket_server()

                # Keep the server running
                while True:
                    await asyncio.sleep(1)
            except Exception as e:
                logger.error("Error running MLD manager socket server", exc_info=e)
            finally:
                try:
                    # Stop the socket server
                    from opencis.cxl.component.mld_manager import mld_manager

                    await mld_manager.stop_socket_server()
                except Exception as e:
                    logger.error("Error stopping MLD manager socket server", exc_info=e)

        asyncio.run(run_socket_server_only())

    return mlds


@mld_group.command(name="start")
@click.option("--port", default=1, help="Port number for the service.", show_default=True)
@click.option("--memfile", type=str, default=None, help="Memory file name.")
@click.option("--memsize", type=str, default="256M", help="Memory file size.")
def start(port, memfile, memsize):
    logger.info(f"Starting CXL Single Logical Device at port {port}")
    if memfile is None:
        memfile = f"mld-mem{port}.bin"
    memsize = humanfriendly.parse_size(memsize, binary=True)

    from opencis.apps.multi_logical_device import MultiLogicalDeviceConfig

    mld_config = MultiLogicalDeviceConfig(
        port_index=port,
        memory_sizes=[memsize],
        memory_files=[memfile],
        serial_numbers=[],
        total_capacity=memsize,
        ld_count=1,
        ld_list=[],
    )

    mld = MultiLogicalDevice(mld_config)
    asyncio.run(mld.run())
