#!/usr/bin/env python3

import logging
from signal import *
import asyncio
import sys, os
from opencis.apps.synth_accelerator import MyType1Accelerator
from opencis.util.logger import logger

logger.setLevel(logging.INFO)
device: MyType1Accelerator = None
start_tasks = []
stop_signal = asyncio.Event()


async def shutdown(signame=None):
    global device
    global start_tasks
    global stop_signal
    try:
        device.set_stop_flag()
        stop_signal.set()
        stop_tasks = [
            asyncio.create_task(device.stop()),
        ]
        await asyncio.gather(*stop_tasks)
        await asyncio.gather(*start_tasks)
    except Exception as exc:
        logger.debug("[ACCEL]", exc.__traceback__)
    finally:
        os._exit(0)


async def main():
    # install signal handlers
    lp = asyncio.get_event_loop()
    lp.add_signal_handler(SIGINT, lambda signame="SIGINT": asyncio.create_task(shutdown(signame)))

    sw_portno = int(sys.argv[1])
    portidx = int(sys.argv[2])
    train_data_path = sys.argv[3]

    logger.debug(f"[ACCEL] listening on port {sw_portno} and physical port {portidx}")

    global device
    global start_tasks
    global stop_signal

    device = MyType1Accelerator(
        port_index=portidx,
        port=sw_portno,
        server_port=9050,
        device_id=portidx - 1,
        host="localhost",
        train_data_path=train_data_path,
    )

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


if __name__ == "__main__":
    asyncio.run(main())
