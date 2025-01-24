"""
 Copyright (c) 2024, Eeum, Inc.

 This software is licensed under the terms of the Revised BSD License.
 See LICENSE for details.
"""

import asyncio
import click

from opencis.bin.common import BASED_INT
from opencis.apps.packet_trace_runner import PacketTraceRunner


@click.group(name="packet-runner")
def ptr_group():
    """Command group for packet-runner"""


@ptr_group.command(name="start")
@click.argument("pcap-file", nargs=1, type=str)
@click.option("--switch-host", type=str, default="0.0.0.0", help="Host for switch")
@click.option("--switch-port", type=BASED_INT, default=8000, help="TCP port for switch")
@click.option("--device-port", type=BASED_INT, default=3000, help="TCP port for device")
@click.option("--label", type=str, default=None, help="Label to attach to the log lines")
def start(pcap_file, switch_host, switch_port, device_port, label):
    trace_runner = PacketTraceRunner(pcap_file, device_port, switch_port, switch_host, label)
    asyncio.run(trace_runner.run())
