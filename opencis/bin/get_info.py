"""
 Copyright (c) 2024, Eeum, Inc.

 This software is licensed under the terms of the Revised BSD License.
 See LICENSE for details.
"""

import asyncio
import click

from opencis.bin import socketio_client


@click.group(name="get-info")
def get_info_group():
    """Command group for component info"""


@get_info_group.command(name="port")
def get_port():
    asyncio.run(socketio_client.get_port())


@get_info_group.command(name="vcs")
def get_vcs():
    asyncio.run(socketio_client.get_vcs())


@get_info_group.command(name="device")
def get_device():
    asyncio.run(socketio_client.get_device())
