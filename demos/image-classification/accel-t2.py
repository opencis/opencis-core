#!/usr/bin/env python
"""
 Copyright (c) 2024, Eeum, Inc.

 This software is licensed under the terms of the Revised BSD License.
 See LICENSE for details.
"""

import asyncio
from signal import SIGCONT, SIGINT
import os
import sys

from opencis.util.logger import logger
from opencis.apps.accelerator import MyType2Accelerator
from opencis.util.number_const import MB

device: MyType2Accelerator = None
start_tasks = []


async def shutdown(signame=None):
    # pylint: disable=unused-argument
    try:
        stop_tasks = [
            asyncio.create_task(device.stop()),
        ]
        await asyncio.gather(*stop_tasks, return_exceptions=True)
        await asyncio.gather(*start_tasks)
    except Exception as exc:
        logger.info(f"[ACCEL] {exc.__traceback__}")
    finally:
        os._exit(0)


async def main():
    # pylint: disable=global-statement, duplicate-code
    lp = asyncio.get_event_loop()
    lp.add_signal_handler(SIGINT, lambda signame="SIGINT": asyncio.create_task(shutdown(signame)))

    sw_portno = int(sys.argv[1])
    portidx = int(sys.argv[2])
    train_data_path = sys.argv[3]

    global device
    global start_tasks

    start_tasks = []
    ready_tasks = []
    mempath = f"mem{portidx}.bin"
    with open(mempath, "a") as _:
        pass
    device = MyType2Accelerator(
        port_index=portidx,
        memory_size=256 * MB,  # min 256MB, or will cause error for DVSEC
        memory_file=f"mem{portidx}.bin",
        host="localhost",
        port=sw_portno,
        train_data_path=train_data_path,
        device_id=portidx - 1,
    )
    start_tasks.append(asyncio.create_task(device.run()))
    ready_tasks.append(asyncio.create_task(device.wait_for_ready()))
    await asyncio.gather(*ready_tasks)

    os.kill(os.getppid(), SIGCONT)

    await asyncio.Event().wait()  # blocks


if __name__ == "__main__":
    asyncio.run(main())
