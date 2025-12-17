"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

import asyncio
import click

from opencis.util.logger import logger
from opencis.apps.fabric_manager import CxlFabricManager
from opencis.bin import socketio_client
from opencis.bin.common import BASED_INT


# Fabric Manager command group
@click.group(name="fm")
def fabric_manager_group():
    """Command group for Fabric Manager."""


@fabric_manager_group.command(name="start")
@click.option("--use-test-runner", is_flag=True, help="Run with the test runner.")
@click.option("--config-file", help="<Config File> input path.")
def start(use_test_runner, config_file):
    """Run the Fabric Manager."""
    logger.info("Starting CXL FabricManager")
    fabric_manager = CxlFabricManager(use_test_runner=use_test_runner, config_file=config_file)
    try:
        asyncio.run(fabric_manager.run())
    except SystemExit:
        # Signal handler called sys.exit() - process is terminating, don't try to stop
        # in a new event loop as it would fail with "bound to different event loop"
        pass
    except Exception as e:
        logger.error("Error while running CXL FabricManager", exc_info=e)
        try:
            asyncio.run(fabric_manager.stop())
        except Exception as stop_e:
            logger.error("Error while stopping CXL FabricManager", exc_info=stop_e)


@fabric_manager_group.command(name="bind")
@click.argument("vcs", nargs=1, type=BASED_INT)
@click.argument("vppb", nargs=1, type=BASED_INT)
@click.argument("physical", nargs=1, type=BASED_INT)
@click.argument(
    "ld_id",
    nargs=1,
    type=BASED_INT,
    default=0,
)
def fm_bind(vcs: int, vppb: int, physical: int, ld_id: int):
    asyncio.run(socketio_client.bind(vcs, vppb, physical, ld_id))


@fabric_manager_group.command(name="unbind")
@click.argument("vcs", nargs=1, type=BASED_INT)
@click.argument("vppb", nargs=1, type=BASED_INT)
def fm_unbind(vcs: int, vppb: int):
    asyncio.run(socketio_client.unbind(vcs, vppb))


@fabric_manager_group.command(name="get-ld-info")
@click.argument("port_index", nargs=1, type=BASED_INT)
def get_ld_info(port_index: int):
    asyncio.run(socketio_client.get_ld_info(port_index))


@fabric_manager_group.command(name="get-ld-allocations")
@click.argument("port_index", nargs=1, type=BASED_INT)
@click.argument("start_ld_id", nargs=1, type=BASED_INT)
@click.argument("ld_allocation_list_limit", nargs=1, type=BASED_INT)
def get_ld_allocation(port_index: int, start_ld_id: int, ld_allocation_list_limit: int):
    asyncio.run(
        socketio_client.get_ld_allocation(port_index, start_ld_id, ld_allocation_list_limit)
    )


@fabric_manager_group.command(name="freeze")
@click.argument("vcs", nargs=1, type=BASED_INT)
@click.argument("vppb", nargs=1, type=BASED_INT)
def fm_freeze(vcs: int, vppb: int):
    asyncio.run(socketio_client.freeze(vcs, vppb))


@fabric_manager_group.command(name="unfreeze")
@click.argument("vcs", nargs=1, type=BASED_INT)
@click.argument("vppb", nargs=1, type=BASED_INT)
def fm_unfreeze(vcs: int, vppb: int):
    asyncio.run(socketio_client.unfreeze(vcs, vppb))


# TODO: Implement set_ld_allocation
@fabric_manager_group.command(name="set-ld-allocation")
@click.argument("port_index", nargs=1, type=BASED_INT)
@click.argument("number_of_lds", nargs=1, type=BASED_INT)
@click.argument("start_ld_id", nargs=1, type=BASED_INT)
@click.argument("ld_allocation_list", nargs=1, type=BASED_INT)
def set_ld_allocation(
    port_index: int, number_of_lds: int, start_ld_id: int, ld_allocation_list: int
):
    asyncio.run(
        socketio_client.set_ld_allocation(
            port_index, number_of_lds, start_ld_id, ld_allocation_list
        )
    )


@fabric_manager_group.command(name="background-status")
def background_status():
    """Check the status of background commands."""
    asyncio.run(socketio_client.get_background_status())


@fabric_manager_group.command(name="test-dynamic-ld")
def test_dynamic_ld():
    """Test dynamic LD allocation with empty configuration."""
    print("Testing dynamic LD allocation...")
    print("This will create logical devices dynamically using the Set LD Allocation command.")

    async def test():
        # Create first LD
        await socketio_client.set_ld_allocation(
            port_index=1,
            number_of_lds=1,
            start_ld_id=0,
            ld_allocation_list=[{"range1": 16384, "range2": 0}],
        )
        print("✅ Created first LD (ID: 16384)")

        # Create multiple LDs
        await socketio_client.set_ld_allocation(
            port_index=1,
            number_of_lds=2,
            start_ld_id=1,
            ld_allocation_list=[{"range1": 16385, "range2": 0}, {"range1": 16386, "range2": 0}],
        )
        print("✅ Created additional LDs (IDs: 16385, 16386)")

        print("Dynamic LD allocation test completed successfully!")

    asyncio.run(test())
