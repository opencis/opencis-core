"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.

CXL Host CLI — opencis host <command>
======================================

Commands:
  host start          Start a single CXL Host on a given port
  host start-group    Start a group of CXL Hosts from a config file
  host mem-write      CXL.mem write to a device address
  host mem-read       CXL.mem read from a device address
  host get-port       Get physical port state from the switch (via FM SocketIO)
  host get-vcs        Get virtual CXL switch info (via FM SocketIO)
  host get-device     Get connected device info (via FM SocketIO)
"""

import asyncio
import click

from opencis.util.logger import logger
from opencis.cxl.environment import parse_cxl_environment
from opencis.cxl.component.cxl_component import PORT_TYPE
from opencis.cxl.component.host_manager import HostManager, UtilConnClient
from opencis.apps.memory_pooling import run_host
from opencis.bin import socketio_client
from opencis.bin.common import BASED_INT


# ─────────────────────────────────────────────────────────────────────────────
# Top-level group
# ─────────────────────────────────────────────────────────────────────────────

@click.group(name="host")
def host_group():
    """CXL Host management commands."""


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers (not CLI commands)
# ─────────────────────────────────────────────────────────────────────────────

async def _start_host_manager():
    logger.info("Starting CXL HostManager")
    host_manager = HostManager()
    await host_manager.run()


async def _run_host_group(ports, ig, iw):
    irq_port = 8500
    tasks = [asyncio.create_task(_start_host_manager())]
    for idx in ports:
        tasks.append(
            asyncio.create_task(
                run_host(port_index=idx, irq_port=irq_port, ig=ig, iw=iw)
            )
        )
        irq_port += 1
    try:
        await asyncio.gather(*tasks)
    except Exception as e:
        logger.error("Error while running CXL Host Group", exc_info=e)
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


def start_group(config_file: str, ig: int = 0, iw: int = 0):
    """Internal helper used by 'opencis start' all-in-one command."""
    logger.info(f"Starting CXL Host Group - Config: {config_file}")
    try:
        environment = parse_cxl_environment(config_file)
    except Exception as e:
        logger.error(f"Failed to parse environment configuration: {e}")
        return

    ports = [
        idx
        for idx, port_config in enumerate(environment.switch_config.port_configs)
        if port_config.type == PORT_TYPE.USP
    ]

    try:
        asyncio.run(_run_host_group(ports, ig, iw))
    except Exception as e:
        logger.error("Error while running CXL Host Group", exc_info=e)


# ─────────────────────────────────────────────────────────────────────────────
# host start — single host
# ─────────────────────────────────────────────────────────────────────────────

@host_group.command(name="start")
@click.option("--port",     type=BASED_INT, default=0, show_default=True,
              help="CXL port index to start the host on.")
@click.option("--irq-port", type=BASED_INT, default=8500, show_default=True,
              help="IRQ/interrupt port used by the host.")
@click.option("--ig",       type=BASED_INT, default=0, show_default=True,
              help="Interleave Granularity (IG) in bytes.")
@click.option("--iw",       type=BASED_INT, default=0, show_default=True,
              help="Interleave Ways (IW).")
def host_start(port: int, irq_port: int, ig: int, iw: int):
    """Start a single CXL Host on a given port index.

    \b
    Example:
        host start --port 0
        host start --port 1 --ig 256 --iw 2
    """
    logger.info(f"Starting CXL Host on port {port}")
    try:
        asyncio.run(run_host(port_index=port, irq_port=irq_port, ig=ig, iw=iw))
    except Exception as e:
        logger.error(f"Error running CXL Host: {e}", exc_info=e)


# ─────────────────────────────────────────────────────────────────────────────
# host start-group — multiple hosts from config
# ─────────────────────────────────────────────────────────────────────────────

@host_group.command(name="start-group")
@click.option("--config-file", required=True,
              help="Path to CXL environment config file (YAML).")
@click.option("--ig", type=BASED_INT, default=0, show_default=True,
              help="Interleave Granularity (IG) in bytes.")
@click.option("--iw", type=BASED_INT, default=0, show_default=True,
              help="Interleave Ways (IW).")
def host_start_group(config_file: str, ig: int, iw: int):
    """Start all CXL Hosts defined in a config file.

    Reads USP port configs from the environment file and starts
    one CXL Host per USP port, plus the HostManager.

    \b
    Example:
        host start-group --config-file tests/configs/pbr_2port.yaml
    """
    start_group(config_file, ig, iw)


# ─────────────────────────────────────────────────────────────────────────────
# host mem-write / host mem-read — CXL.mem data plane
# ─────────────────────────────────────────────────────────────────────────────

@host_group.command(name="mem-write")
@click.argument("port",  type=BASED_INT)
@click.argument("addr",  type=BASED_INT)
@click.argument("data",  type=BASED_INT)
@click.option("--util-host", type=str,       default="0.0.0.0", show_default=True,
              help="UtilConnServer host.")
@click.option("--util-port", type=BASED_INT, default=8400,     show_default=True,
              help="UtilConnServer port.")
def host_mem_write(port: int, addr: int, data: int, util_host: str, util_port: int):
    """CXL.mem write to a device via a host port.

    PORT: host port index
    ADDR: 64-bit physical address (hex or decimal)
    DATA: value to write (up to 64 bytes = 0x40 bytes)

    \b
    Example:
        host mem-write 0 0x1000 0xDEADBEEF
        host mem-write 1 0x2000 0xCAFEBABE --util-port 8401
    """
    if len(f"{data:x}") > 128:
        logger.info(f"CXL-Host[Port{port}]: Error — data length > 0x40 bytes")
        return
    client = UtilConnClient(host=util_host, port=util_port)
    try:
        asyncio.run(client.cxl_mem_write(port, addr, data))
        logger.info(f"CXL-Host[Port{port}]: CXL.mem write success  addr={addr:#x}")
    except Exception as e:
        logger.info(f"CXL-Host[Port{port}]: {e}")


@host_group.command(name="mem-read")
@click.argument("port", type=BASED_INT)
@click.argument("addr", type=BASED_INT)
@click.option("--util-host", type=str,       default="0.0.0.0", show_default=True,
              help="UtilConnServer host.")
@click.option("--util-port", type=BASED_INT, default=8400,     show_default=True,
              help="UtilConnServer port.")
def host_mem_read(port: int, addr: int, util_host: str, util_port: int):
    """CXL.mem read from a device via a host port.

    PORT: host port index
    ADDR: 64-bit physical address (hex or decimal)

    \b
    Example:
        host mem-read 0 0x1000
        host mem-read 1 0x2000 --util-port 8401
    """
    client = UtilConnClient(host=util_host, port=util_port)
    try:
        res = asyncio.run(client.cxl_mem_read(port, addr))
        logger.info(f"CXL-Host[Port{port}]: CXL.mem read success  addr={addr:#x}")
        logger.info("Data:")
        res_hex = f"{res:x}"
        data = [int(res_hex[i:i+2], 16) for i in range(0, len(res_hex), 2)]
        logger.hexdump("INFO", data)
    except Exception as e:
        logger.info(f"CXL-Host[Port{port}]: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# host get-port / get-vcs / get-device — query switch state via FM SocketIO
# ─────────────────────────────────────────────────────────────────────────────

@host_group.command(name="get-port")
def host_get_port():
    """Get physical port state from the switch (via FM SocketIO port 8200).

    Shows port type, connection state, and link speed for all switch ports.

    \b
    Example:
        host get-port
    """
    asyncio.run(socketio_client.get_port())


@host_group.command(name="get-vcs")
def host_get_vcs():
    """Get virtual CXL switch (VCS) info (via FM SocketIO port 8200).

    Shows VCS bindings and vPPB states.

    \b
    Example:
        host get-vcs
    """
    asyncio.run(socketio_client.get_vcs())


@host_group.command(name="get-device")
def host_get_device():
    """Get connected device info (via FM SocketIO port 8200).

    Shows device type, serial number, and port for all connected CXL devices.

    \b
    Example:
        host get-device
    """
    asyncio.run(socketio_client.get_device())
