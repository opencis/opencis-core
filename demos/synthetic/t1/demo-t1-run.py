#!/usr/bin/env python3

import asyncio
import logging
from signal import *
import os
import argparse
from opencis.util.logger import logger

logger.setLevel(logging.INFO)

sw_port = "22500"

RUN_LIST = []

jobs = {}  # list of pids

run_progress = 0

interrupted = False

stop_signal = asyncio.Event()


def clean_shutdown(signum=None, frame=None):
    global interrupted, stop_signal
    interrupted = True
    stop_signal.set()
    pthread_sigmask(SIG_BLOCK, [SIGINT])
    for prog, pid in reversed(jobs.items()):
        print(f"[RUNNER] Killing {prog} (PID {pid})")
        os.kill(pid, SIGINT)
        os.waitpid(pid, 0)
        print(f"[RUNNER] Killed {prog} (PID {pid})")

    logger.debug(f"[RUNNER] exiting...")
    quit()


async def main(signum=None, frame=None):
    run_next_app(signum, frame)
    await stop_signal.wait()


def run_next_app(signum=None, frame=None):
    if interrupted:
        return

    pthread_sigmask(SIG_BLOCK, [SIGCONT])

    logger.debug("[RUNNER] SIGCONT received")

    global run_progress, jobs, stop_signal

    if run_progress >= len(RUN_LIST):
        # signal the host that IO is ready
        host_pid = jobs["host"]
        os.kill(host_pid, SIGIO)
        return

    component_name, program, args = RUN_LIST[run_progress]

    if not (chld := os.fork()):
        # child process
        try:
            if os.execvp(program, (program, *args)) == -1:
                logger.debug("EXECVE FAIL!!!")
        except PermissionError as exc:
            raise RuntimeError(f'Failed to invoke "{program}" with args {args}') from exc
        except FileNotFoundError as exc:
            raise RuntimeError(f'Couldn\'t find "{program}"') from exc
    else:
        run_progress += 1
        jobs[component_name] = chld
        pthread_sigmask(SIG_UNBLOCK, [SIGCONT])
        logger.debug(f"[RUNNER] PID {chld}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-p",
        "--img-folder-path",
        dest="ifp",
        action="store",
        required=True,
        help="The folder path to the image training data.",
        metavar="IMG_FOLDER_PATH",
    )
    parser.add_argument(
        "-n",
        "--num-accels",
        dest="na",
        default=2,
        action="store",
        help="The number of accelerators.",
        metavar="NUM_ACCELS",
    )

    args = vars(parser.parse_args())
    train_data_path = args["ifp"]
    num_accels = int(args["na"])

    if not os.path.exists(train_data_path) or not os.path.isdir(train_data_path):
        logger.debug(f"Path {train_data_path} does not exist, or is not a folder.")
        quit(1)

    RUN_LIST = [
        ("switch", "./switch.py", (sw_port,)),
        ("host", "./chost.py", (sw_port, train_data_path)),
    ]
    for i in range(num_accels):
        RUN_LIST.append((f"accel{i + 1}", "./accel.py", (sw_port, f"{i + 1}", train_data_path)))
    signal(SIGCONT, run_next_app)
    signal(SIGINT, clean_shutdown)
    asyncio.run(main())
    while True:
        pause()
