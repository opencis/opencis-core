"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

import logging
import multiprocessing
import os
import signal
import sys
import time
import traceback
from typing import List

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

# Global list to track spawned processes
_spawned_processes: List[multiprocessing.Process] = []
_shutdown_initiated = False


def signal_handler(signum: int, _) -> None:
    # pylint: disable=global-statement
    global _shutdown_initiated
    if _shutdown_initiated:
        return
    _shutdown_initiated = True

    signal_name = signal.Signals(signum).name
    logger.info(f"Received {signal_name}, initiating shutdown...")

    # Only the main process should manage child processes
    if not _spawned_processes:
        logger.info("Child process exiting...")
        sys.exit(0)

    # Send SIGTERM to all child processes and their process groups
    for proc in _spawned_processes[:]:
        try:
            if proc.is_alive():
                logger.info(f"Terminating process {proc.pid} and its group...")
                try:
                    # Send SIGTERM to the entire process group
                    os.killpg(proc.pid, signal.SIGTERM)
                except (ProcessLookupError, PermissionError) as e:
                    logger.warning(f"Could not send signal to process group {proc.pid}: {e}")
                    try:
                        # Fallback to individual process
                        proc.terminate()
                    except Exception as e2:
                        logger.error(f"Error terminating process {proc.pid}: {e2}")
        except AssertionError as e:
            if "can only test a child process" in str(e):
                logger.debug(f"Cannot check status of process {proc.pid} - not our child")
                # Remove from our list since we can't manage it
                try:
                    _spawned_processes.remove(proc)
                except ValueError:
                    pass
            else:
                logger.error(f"Error checking process {proc.pid}: {e}")
        except Exception as e:
            logger.error(f"Error handling process {proc.pid}: {e}")

    logger.info("Waiting for processes to terminate...")
    timeout = 10
    start_time = time.time()

    while _spawned_processes and (time.time() - start_time) < timeout:
        for proc in _spawned_processes[:]:
            try:
                proc.join(timeout=0.1)
                if not proc.is_alive():
                    _spawned_processes.remove(proc)
                    logger.info(f"Process {proc.pid} terminated")
            except AssertionError as e:
                if "can only test a child process" in str(e):
                    logger.debug(f"Cannot join process {proc.pid} - not our child")
                    _spawned_processes.remove(proc)
                else:
                    logger.error(f"Error joining process {proc.pid}: {e}")
            except Exception as e:
                logger.error(f"Error waiting for process {proc.pid}: {e}")

        if _spawned_processes:
            time.sleep(0.1)

    # Force kill any remaining processes
    if _spawned_processes:
        logger.warning("Force killing remaining processes...")
        for proc in _spawned_processes[:]:
            try:
                if proc.is_alive():
                    try:
                        # Try to kill the entire process group first
                        os.killpg(proc.pid, signal.SIGKILL)
                        proc.join(timeout=1)
                        logger.info(f"Force killed process group {proc.pid}")
                    except (ProcessLookupError, PermissionError):
                        try:
                            # Fallback to individual process
                            proc.kill()
                            proc.join(timeout=1)
                            logger.info(f"Force killed process {proc.pid}")
                        except Exception as e:
                            logger.error(f"Error force killing process {proc.pid}: {e}")
            except AssertionError as e:
                if "can only test a child process" in str(e):
                    logger.debug(f"Cannot force kill process {proc.pid} - not our child")
                    _spawned_processes.remove(proc)
                else:
                    logger.error(f"Error force killing process {proc.pid}: {e}")
            except Exception as e:
                logger.error(f"Error in force kill for process {proc.pid}: {e}")

    logger.info("Shutdown complete")
    sys.exit(0)


def setup_signal_handlers() -> None:
    """Set up signal handlers for shutdown."""
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    logger.info("Signal handlers set up for shutdown")


def setup_child_signal_handlers() -> None:
    """Set up signal handlers for child processes."""

    def child_signal_handler(signum: int, _) -> None:
        signal_name = signal.Signals(signum).name
        logger.info(f"Child process {os.getpid()} received {signal_name}, exiting...")
        sys.exit(0)

    signal.signal(signal.SIGTERM, child_signal_handler)
    signal.signal(signal.SIGINT, child_signal_handler)


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

    # Set up signal handlers for shutdown
    setup_signal_handlers()

    # Launch processes
    for name in comp:
        launcher = component_map.get(name)
        if launcher:
            spawn_process(launcher)

    # Keep main process alive and wait for all child processes
    try:
        logger.info(f"Started {len(_spawned_processes)} processes. Press Ctrl+C for shutdown.")
        wait_for_processes()
    except KeyboardInterrupt:
        logger.info("Received KeyboardInterrupt, initiating shutdown...")
        signal_handler(signal.SIGINT, None)


# helper functions
def child_process_wrapper(target):
    """Wrapper function that sets up child process signal handling and process group."""
    # Create a new process group for this child process
    os.setpgrp()
    setup_child_signal_handlers()

    target()


def spawn_process(target):
    """Spawn a new process and track it for proper shutdown."""
    proc = multiprocessing.Process(target=lambda: child_process_wrapper(target))
    proc.start()
    _spawned_processes.append(proc)
    logger.debug(f"Spawned process {proc.pid}")


def wait_for_processes():
    """Wait for all spawned processes to complete."""
    while _spawned_processes:
        for proc in _spawned_processes[:]:
            try:
                proc.join(timeout=0.5)
                if not proc.is_alive():
                    _spawned_processes.remove(proc)
                    logger.info(f"Process {proc.pid} completed")
            except Exception as e:
                logger.error(f"Error monitoring process {proc.pid}: {e}")

        if _spawned_processes:
            time.sleep(0.1)


def start_capture(pcap_file):
    try:
        logger.info(f"Capturing in pid: {os.getpid()}")
        if os.path.exists(pcap_file):
            os.remove(pcap_file)

        capture = pyshark.LiveCapture(interface="lo", bpf_filter="tcp", output_file=pcap_file)
        capture.sniff(packet_count=0)
    except KeyboardInterrupt:
        logger.info("Packet capture interrupted, shutting down")
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
