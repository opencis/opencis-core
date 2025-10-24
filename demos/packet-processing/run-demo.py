"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

import argparse
from signal import SIGCONT, SIGINT, SIGIO, SIG_BLOCK, SIG_UNBLOCK, pthread_sigmask, signal, pause

import os

from opencis.util.logger import logger

run_progress = 0
pids = {}
RUN_LIST = {}


def clean_shutdown(signum=None, frame=None):
    # pylint: disable=unused-argument, global-statement
    pthread_sigmask(SIG_BLOCK, [SIGINT])

    global pids
    pids = dict(reversed(pids.items()))
    for _, pid in pids.items():
        os.kill(pid, SIGINT)
        os.waitpid(pid, 0)
    os._exit(0)


def run_next_app(signum=None, frame=None):
    # pylint: disable=unused-argument, global-statement
    pthread_sigmask(SIG_BLOCK, [SIGCONT])

    global run_progress
    if run_progress >= len(RUN_LIST):
        # signal the host that IO is ready
        host_pid = pids["host"]
        os.kill(host_pid, SIGIO)
        return

    component_name, program, args = RUN_LIST[run_progress]

    if not (chld := os.fork()):
        # child process
        try:
            if os.execvp(program, (program, *args)) == -1:
                logger.info("EXECVE FAIL!!!")
        except PermissionError as exc:
            raise RuntimeError(f'Failed to invoke "{program}" with args {args}') from exc
        except FileNotFoundError as exc:
            raise RuntimeError(f'Couldn\'t find "{program}"') from exc
    else:
        run_progress += 1
        pids[component_name] = chld
        pthread_sigmask(SIG_UNBLOCK, [SIGCONT])


def main():
    # pylint: disable=global-statement
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-n",
        "--num-accels",
        dest="na",
        default="2",
        action="store",
        help="The number of accelerators.",
        metavar="NUM_ACCELS",
    )
    parser.add_argument(
        "-t",
        "--accel-type",
        dest="at",
        default="2",
        action="store",
        help="Accelerator CXL device type.",
        metavar="ACCEL_TYPE",
    )

    parser.add_argument(
        "-r",
        "--push-rate",
        dest="pr",
        default="1",
        action="store",
        help="Cache Friendliness Enabled.",
        metavar="CACHE_FRIENDLINESS",
    )

    parser.add_argument(
        "-p",
        "--max-packets",
        dest="mp",
        default="-1",
        action="store",
        help="Max number of packets to be processed. Default -1 (no limit).",
        metavar="CACHE_FRIENDLINESS",
    )

    args = vars(parser.parse_args())
    num_accels = args["na"]
    accel_type = args["at"]
    push_rate = args["pr"]
    max_packets = args["mp"]
    sw_port = "22500"

    host_file = f"./host-t{accel_type}.py"
    accel_file = f"./accel-t{accel_type}.py"

    global RUN_LIST
    RUN_LIST = [
        ("switch", "./switch.py", (sw_port, num_accels)),
        ("host", host_file, (sw_port, num_accels, push_rate, max_packets)),
    ]
    for i in range(int(num_accels)):
        RUN_LIST.append(
            (
                f"accel{i + 1}",
                accel_file,
                (sw_port, f"{i + 1}", num_accels),
            )
        )
    signal(SIGCONT, run_next_app)
    signal(SIGINT, clean_shutdown)

    run_next_app()

    while True:
        pause()


if __name__ == "__main__":
    main()
