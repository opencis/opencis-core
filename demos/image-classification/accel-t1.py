#!/usr/bin/env python
"""
 Copyright (c) 2024, Eeum, Inc.

 This software is licensed under the terms of the Revised BSD License.
 See LICENSE for details.
"""

import logging
from signal import SIGCONT, SIGINT
import asyncio
import os
import sys

from opencis.apps.accelerator import MyType1Accelerator
from opencis.util.logger import logger

logger.setLevel(logging.INFO)
device: MyType1Accelerator = None
start_tasks = []
stop_signal = asyncio.Event()


async def shutdown(signame=None):
    # pylint: disable=unused-argument
    try:
        device.set_stop_flag()
        stop_tasks = [
            asyncio.create_task(device.stop()),
        ]
        await asyncio.gather(*stop_tasks)
        stop_signal.set()
    except Exception as exc:
        logger.debug(f"[ACCEL] {exc.__traceback__}")
    finally:
        os._exit(0)


async def main():
    # pylint: disable=global-statement, duplicate-code
    lp = asyncio.get_event_loop()
    lp.add_signal_handler(SIGINT, lambda signame="SIGINT": asyncio.create_task(shutdown(signame)))

    sw_portno = int(sys.argv[1])
    portidx = int(sys.argv[2])
    train_data_path = sys.argv[3]

    logger.debug(f"[ACCEL] listening on port {sw_portno} and physical port {portidx}")

    global device
    device = MyType1Accelerator(
        port_index=portidx,
        port=sw_portno,
        irq_port=8500,
        device_id=portidx - 1,
        train_data_path=train_data_path,
    )

    global start_tasks
    start_tasks = [
        asyncio.create_task(device.run()),
    ]
    ready_tasks = [
        asyncio.create_task(device.wait_for_ready()),
    ]

    os.kill(os.getppid(), SIGCONT)

    await asyncio.gather(*ready_tasks)
    logger.debug("[ACCEL] ready!")

    await stop_signal.wait()
    await asyncio.gather(*start_tasks)


if __name__ == "__main__":
    asyncio.run(main())
