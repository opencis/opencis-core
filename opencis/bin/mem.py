"""
 Copyright (c) 2024, Eeum, Inc.

 This software is licensed under the terms of the Revised BSD License.
 See LICENSE for details.
"""

import asyncio
import click

from opencis.util.logger import logger
from opencis.cxl.component.host_manager import UtilConnClient
from opencis.bin.common import BASED_INT


@click.group(name="mem")
def mem_group():
    """Command group for CXL.mem Commands"""


@mem_group.command(name="write")
@click.argument("port", nargs=1, type=BASED_INT)
@click.argument("addr", nargs=1, type=BASED_INT)
@click.argument("data", nargs=1, type=BASED_INT)
@click.option("--util-host", type=str, default="0.0.0.0", help="Host for util server")
@click.option("--util-port", type=BASED_INT, default=8400, help="Port for util server")
def cxl_mem_write(port: int, addr: int, data: int, util_host: str, util_port: int):
    """CXL.mem Write Command"""
    client = UtilConnClient(host=util_host, port=util_port)
    if len(f"{data:x}") > 128:
        logger.info(f"CXL-Host[Port{port}]: Error - Data length greater than 0x40 bytes")
        return
    try:
        asyncio.run(client.cxl_mem_write(port, addr, data))
    except Exception as e:
        logger.info(f"CXL-Host[Port{port}]: {e}")
        return
    logger.info(f"CXL-Host[Port{port}]: CXL.mem Write success")


@mem_group.command(name="read")
@click.argument("port", nargs=1, type=BASED_INT)
@click.argument("addr", nargs=1, type=BASED_INT)
@click.option("--util-host", type=str, default="0.0.0.0", help="Host for util server")
@click.option("--util-port", type=BASED_INT, default=8400, help="Port for util server")
def cxl_mem_read(port: int, addr: int, util_host: str, util_port: int):
    """CXL.mem Read Command"""
    client = UtilConnClient(host=util_host, port=util_port)
    try:
        res = asyncio.run(client.cxl_mem_read(port, addr))
    except Exception as e:
        logger.info(f"CXL-Host[Port{port}]: {e}")
        return
    logger.info(f"CXL-Host[Port{port}]: CXL.mem Read success")
    logger.info("Data:")
    res = f"{res:x}"
    data = list(map(lambda x: int(x, 16), [res[i : i + 2] for i in range(0, len(res), 2)]))
    logger.hexdump("INFO", data)
