"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

import logging
import multiprocessing
import os
import time
import traceback

import click
import pyshark

from opencis.util.logger import logger
from opencis.bin import (
    cxl_host,
    cxl_switch,
    fabric_manager,
    get_info,
    mem,
    multi_logical_device as mld,
    packet_runner,
    single_logical_device as sld,
)


@click.group()
def cli():
    pass


def validate_component(ctx, param, components):
    # pylint: disable=unused-argument
    valid_components = [
        "fm",
        "switch",
        "host-group",
        "sld-group",
        "mld-group",
    ]
    if "all" in components:
        return ("fm", "switch", "host-group", "sld-group", "mld-group")
    for c in components:
        if not c in valid_components:
            raise click.BadParameter(f"Please select from {list(valid_components)}")
    return components


def validate_log_level(ctx, param, level):
    # pylint: disable=unused-argument
    valid_levels = list(logging.getLevelNamesMapping().keys())
    if level:
        level = level.upper()
        if not level in valid_levels:
            raise click.BadParameter(f"Please select from {", ".join(valid_levels)}")
    return level


@cli.command(name="start")
@click.pass_context
@click.option(
    "-c",
    "--comp",
    multiple=True,
    required=True,
    callback=validate_component,
    help='Components. e.g. "-c fm -c switch ..." ',
)
@click.option("--config-file", help="<Config File> input path.")
@click.option("--log-file", help="<Log File> output path.")
@click.option("--pcap-file", help="<Packet Capture File> output path.")
@click.option("--log-level", callback=validate_log_level, help="Specify log level.")
@click.option("--show-timestamp", is_flag=True, default=False, help="Show timestamp.")
@click.option("--show-loglevel", is_flag=True, default=False, help="Show log level.")
@click.option("--show-linenumber", is_flag=True, default=False, help="Show line number.")
@click.option("--ig", help="Interleave granularity")
@click.option("--iw", help="Interleave ways")
def start(
    ctx,
    comp,
    config_file,
    log_level,
    log_file,
    pcap_file,
    show_timestamp,
    show_loglevel,
    show_linenumber,
    ig,
    iw,
):
    """Start components"""

    log_level = log_level if not None else "INFO"
    config_components = ["switch", "sld-group", "mld-group", "host-group"]
    comp = list(comp)

    # Validate config
    missing_cfg = [c for c in comp if c in config_components and not config_file]
    if missing_cfg:
        raise click.BadParameter(f"Must specify <config file> for: {', '.join(missing_cfg)}")

    # Logger setup
    if log_level or show_timestamp or show_loglevel or show_linenumber:
        logger.set_stdout_levels(
            loglevel=log_level,
            show_timestamp=show_timestamp,
            show_loglevel=show_loglevel,
            show_linenumber=show_linenumber,
        )

    if log_file:
        logger.create_log_file(
            f"logs/{log_file}",
            loglevel=log_level,
            show_timestamp=show_timestamp,
            show_loglevel=show_loglevel,
            show_linenumber=show_linenumber,
        )

    component_map = {
        "fm": lambda: ctx.invoke(fabric_manager.start),
        "switch": lambda: ctx.invoke(cxl_switch.start, config_file=config_file),
        "sld-group": lambda: ctx.invoke(sld.start_group, config_file=config_file),
        "mld-group": lambda: ctx.invoke(mld.start_group, config_file=config_file),
        "host-group": lambda: ctx.invoke(
            cxl_host.start_group, config_file=config_file, ig=ig, iw=iw
        ),
    }

    # Start pcap capture first
    if pcap_file:
        spawn_process(lambda: ctx.invoke(start_capture, pcap_file=pcap_file))
        time.sleep(2)

    # Launch processes
    for name in comp:
        launcher = component_map.get(name)
        if launcher:
            spawn_process(launcher)


# helper functions
def spawn_process(target):
    proc = multiprocessing.Process(target=target)
    proc.start()


def start_capture(pcap_file):
    try:
        logger.info(f"Capturing in pid: {os.getpid()}")
        if os.path.exists(pcap_file):
            os.remove(pcap_file)

        capture = pyshark.LiveCapture(interface="lo", bpf_filter="tcp", output_file=pcap_file)
        capture.sniff(packet_count=0)
    except Exception as e:
        logger.error(f"Failed to start capture: {e}")
        traceback.print_exc()


cli.add_command(cxl_host.host_group)
cli.add_command(fabric_manager.fabric_manager_group)
cli.add_command(get_info.get_info_group)
cli.add_command(mem.mem_group)
cli.add_command(packet_runner.ptr_group)

if __name__ == "__main__":
    cli()
