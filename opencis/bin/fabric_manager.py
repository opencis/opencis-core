"""
 Copyright (c) 2024, Eeum, Inc.

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
def start(use_test_runner):
    """Run the Fabric Manager."""
    logger.info("Starting CXL FabricManager")
    fabric_manager = CxlFabricManager(use_test_runner=use_test_runner)
    asyncio.run(fabric_manager.run())


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


@fabric_manager_group.command(name="get-ld-allocation")
@click.argument("port_index", nargs=1, type=BASED_INT)
@click.argument("start_ld_id", nargs=1, type=BASED_INT)
@click.argument("ld_allocation_list_limit", nargs=1, type=BASED_INT)
def get_ld_allocation(port_index: int, start_ld_id: int, ld_allocation_list_limit: int):
    asyncio.run(
        socketio_client.get_ld_allocation(port_index, start_ld_id, ld_allocation_list_limit)
    )


# TODO: Implement set_ld_allocation
# @fabric_manager_group.command(name="set-ld-allocation")
# @click.argument("port_index", nargs=1, type=BASED_INT)
# @click.argument("number_of_lds", nargs=1, type=BASED_INT)
# @click.argument("start_ld_id", nargs=1, type=BASED_INT)
# @click.argument("ld_allocation_list", nargs=1, type=BASED_INT)
# def set_ld_allocation(
#     port_index: int, number_of_lds: int, start_ld_id: int, ld_allocation_list: int
# ):
#     asyncio.run(
#         socketio_client.set_ld_allocation(
#             port_index, number_of_lds, start_ld_id, ld_allocation_list
#         )
#     )
