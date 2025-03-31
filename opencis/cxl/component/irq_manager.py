"""
Copyright (c) 2024, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from opencis.cxl.component.short_msg_conn import ShortMsgBase, ShortMsgConn


class Irq(ShortMsgBase):
    NULL = 0x00

    # Host-side file ready to be read by device using CXL.cache
    HOST_READY = 0x01

    # Device-side results ready to be read by host using CXL.mem
    ACCEL_VALIDATION_FINISHED = 0x02

    # Host finished writing file to device via CXL.mem
    HOST_SENT = 0x03

    # Accelerator finished training, waiting for host to send validation pics
    ACCEL_TRAINING_FINISHED = 0x04

    # Interrupt for Removed Device
    DEV_REMOVED = 0x05

    # Interrupt for Plugged Device
    DEV_ADDED = 0x06


class IrqManager(ShortMsgConn):
    def __init__(
        self,
        device_name,
        addr: str = "0.0.0.0",
        port: int = 8500,
        server: bool = False,
        device_id: int = 0,
    ):
        super().__init__(
            f"{device_name}:IrqHandler",
            addr,
            port,
            server,
            device_id,
            msg_width=1,
            msg_type=Irq,
        )
