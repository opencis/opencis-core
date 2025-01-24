"""
 Copyright (c) 2024, Eeum, Inc.

 This software is licensed under the terms of the Revised BSD License.
 See LICENSE for details.
"""

from typing import Optional, cast
from enum import Enum, auto
from asyncio import create_task, gather
from opencis.pci.component.fifo_pair import FifoPair
from opencis.pci.config_space.pci import REG_ADDR
from opencis.util.unaligned_bit_structure import BitMaskedBitStructure
from opencis.util.number import tlptoh16
from opencis.cxl.transport.transaction import (
    CxlIoBasePacket,
    CxlIoCfgRdPacket,
    CxlIoCfgWrPacket,
    CxlIoCfgReqPacket,
    CxlIoCompletionPacket,
    CxlIoCompletionWithDataPacket,
    CXL_IO_FMT_TYPE,
    CXL_IO_CPL_STATUS,
)
from opencis.util.component import RunnableComponent
from opencis.util.pci import bdf_to_string
from opencis.util.logger import logger


class PCI_DEVICE_TYPE(Enum):
    UPSTREAM_BRIDGE = auto()
    DOWNSTREAM_BRIDGE = auto()
    ENDPOINT = auto()


class ConfigSpaceManager(RunnableComponent):
    def __init__(
        self,
        upstream_fifo: FifoPair,
        downstream_fifo: Optional[FifoPair] = None,
        label: Optional[str] = None,
        device_type=PCI_DEVICE_TYPE.ENDPOINT,
    ):
        super().__init__()
        if device_type != PCI_DEVICE_TYPE.ENDPOINT and downstream_fifo is None:
            raise Exception("PCI Bridge Device must have a downstream FIFO")
        self._label = label
        self._upstream_fifo = upstream_fifo
        self._downstream_fifo = downstream_fifo
        self._device_type = device_type
        self._register = None
        self._req_id = 0

    def set_register(self, register: BitMaskedBitStructure):
        self._register = register

    def get_register(self):
        return self._register

    async def _forward_request(self, packet: CxlIoBasePacket):
        logger.debug(self._create_message("Forwarding request to the next child device"))
        await self._downstream_fifo.host_to_target.put(packet)

    async def _send_unsupported_request(self, req_id, tag, ld_id):
        packet = CxlIoCompletionPacket.create(
            req_id=req_id, tag=tag, status=CXL_IO_CPL_STATUS.UR, ld_id=ld_id
        )
        await self._upstream_fifo.target_to_host.put(packet)

    def _is_bridge(self) -> bool:
        return self._device_type in (
            PCI_DEVICE_TYPE.DOWNSTREAM_BRIDGE,
            PCI_DEVICE_TYPE.UPSTREAM_BRIDGE,
        )

    async def _process_cxl_io_cfg_rd(self, cfg_rd_packet: CxlIoCfgRdPacket):
        dest_id = tlptoh16(cfg_rd_packet.cfg_req_header.dest_id)
        bdf_str = bdf_to_string(dest_id)
        req_id = tlptoh16(cfg_rd_packet.cfg_req_header.req_id)
        tag = cfg_rd_packet.cfg_req_header.tag
        ld_id = cfg_rd_packet.tlp_prefix.ld_id

        # NOTE: Only downstream port supports non-zero device number.
        if cfg_rd_packet.get_function() != 0:
            logger.debug(
                self._create_message(
                    f"Received request for {bdf_str}, however, this device supports function 0 only"
                )
            )
            await self._send_unsupported_request(req_id, tag, ld_id)
            return

        if (
            self._device_type != PCI_DEVICE_TYPE.DOWNSTREAM_BRIDGE
            and cfg_rd_packet.get_device() != 0
        ):
            logger.debug(
                self._create_message(
                    f"Received request for {bdf_str}, however, this device supports device 0 only"
                )
            )
            await self._send_unsupported_request(req_id, tag, ld_id)
            return

        cfg_addr, size = cfg_rd_packet.get_cfg_addr_read_info()

        # TODO: Fix OOB

        logger.debug(
            self._create_message(
                f"[RD] Config Space - ADDR: 0x{cfg_addr:04x}, SIZE: {size}, LD_ID: {ld_id}"
            )
        )
        value = self._register.read_bytes(cfg_addr, cfg_addr + size - 1)

        cpl_packet = CxlIoCompletionWithDataPacket.create(
            req_id, tag, value, cpl_id=dest_id, ld_id=ld_id
        )
        cpl_packet.cpl_header.req_id = self._req_id
        await self._upstream_fifo.target_to_host.put(cpl_packet)

    async def _process_cxl_io_cfg_wr(self, cfg_wr_packet: CxlIoCfgWrPacket):
        # NOTE: All PCIe devices are single function devices.
        dest_id = tlptoh16(cfg_wr_packet.cfg_req_header.dest_id)
        req_id = tlptoh16(cfg_wr_packet.cfg_req_header.req_id)
        tag = cfg_wr_packet.cfg_req_header.tag
        ld_id = cfg_wr_packet.tlp_prefix.ld_id

        if cfg_wr_packet.get_function() != 0:
            dest_id = tlptoh16(cfg_wr_packet.cfg_req_header.dest_id)
            bdf_str = bdf_to_string(dest_id)
            logger.debug(
                self._create_message(
                    f"Received request for {bdf_str}, however, this device supports function 0 only"
                )
            )
            await self._send_unsupported_request(req_id, tag, ld_id)
            return

        cfg_addr, size = cfg_wr_packet.get_cfg_addr_write_info()
        value = cfg_wr_packet.get_value()

        # TODO: Fix OOB

        logger.debug(
            self._create_message(
                f"[WR] Config Space - ADDR: 0x{cfg_addr:04x}, "
                + "SIZE: {size}, "
                + "VALUE: 0x{value:08x}, "
                + "LD_ID: {ld_id}"
            )
        )
        self._register.write_bytes(cfg_addr, cfg_addr + size - 1, value)

        cpl_packet = CxlIoCompletionPacket.create(
            req_id=req_id, tag=tag, cpl_id=dest_id, ld_id=ld_id
        )
        await self._upstream_fifo.target_to_host.put(cpl_packet)

    async def _process_host_to_target(self):
        # pylint: disable=duplicate-code
        logger.debug(self._create_message("Started processing host to target fifo"))
        while True:
            packet = await self._upstream_fifo.host_to_target.get()
            if packet is None:
                logger.debug(self._create_message("Stop processing host to target fifo"))
                break
            base_packet = cast(CxlIoBasePacket, packet)
            # self._req_id = base_packet.cfg_req_header.req_id
            logger.debug(self._create_message("Received host to target packet"))
            if base_packet.is_cfg_type0():
                if base_packet.is_cfg_read():
                    await self._process_cxl_io_cfg_rd(base_packet)
                elif base_packet.is_cfg_write():
                    await self._process_cxl_io_cfg_wr(base_packet)
            elif base_packet.is_cfg_type1():
                if self._downstream_fifo:
                    self._convert_request_type_when_needed(base_packet)
                    await self._forward_request(base_packet)
                else:
                    logger.warning(
                        self._create_message("Endpoint device should not receive a type1 request")
                    )
                    cfg_req_packet = cast(CxlIoCfgReqPacket, base_packet)
                    req_id = tlptoh16(cfg_req_packet.cfg_req_header.req_id)
                    tag = cfg_req_packet.cfg_req_header.tag
                    ld_id = cfg_req_packet.tlp_prefix.ld_id
                    await self._send_unsupported_request(req_id, tag, ld_id=ld_id)
            else:
                raise Exception("Unexpected packet received from ConfigSpaceManager")

    def _convert_request_type_when_needed(self, packet: CxlIoBasePacket):
        offset = REG_ADDR.SECONDARY_BUS_NUMBER.START
        bus = self._register.read_bytes(offset, offset)
        if packet.is_cfg_type1():
            if packet.is_cfg_read():
                read_packet = cast(CxlIoCfgRdPacket, packet)
                if read_packet.get_bus() == bus:
                    logger.debug(self._create_message("Changing request type1 to type0"))
                    packet.cxl_io_header.fmt_type = CXL_IO_FMT_TYPE.CFG_RD0
            elif packet.is_cfg_write():
                write_packet = cast(CxlIoCfgWrPacket, packet)
                if write_packet.get_bus() == bus:
                    logger.debug(self._create_message("Changing request type1 to type0"))
                    packet.cxl_io_header.fmt_type = CXL_IO_FMT_TYPE.CFG_WR0
        return packet

    async def _process_target_to_host(self):
        if not self._is_bridge():
            logger.debug(self._create_message("Skipped processing downstream target to host fifo"))
            return
        logger.debug(self._create_message("Started processing downstream target to host fifo"))
        while True:
            packet = await self._downstream_fifo.target_to_host.get()
            if packet is None:
                logger.debug(self._create_message("Stop processing downstream target to host fifo"))
                break
            logger.debug(self._create_message("Received target to host packet"))
            await self._upstream_fifo.target_to_host.put(packet)

    async def _run(self):
        # pylint: disable=duplicate-code
        # CE-94
        tasks = [
            create_task(self._process_host_to_target()),
            create_task(self._process_target_to_host()),
        ]
        await self._change_status_to_running()
        await gather(*tasks)

    async def _stop(self):
        logger.info(self._create_message("Stopping ConfigSpaceManager"))
        if self._is_bridge():
            await self._downstream_fifo.target_to_host.put(None)
            self._downstream_fifo = None
        await self._upstream_fifo.host_to_target.put(None)
        self._upstream_fifo = None
