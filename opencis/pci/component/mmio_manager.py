"""
 Copyright (c) 2024, Eeum, Inc.

 This software is licensed under the terms of the Revised BSD License.
 See LICENSE for details.
"""

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Optional, List, Tuple, cast

from opencis.util.logger import logger
from opencis.util.unaligned_bit_structure import BitMaskedBitStructure
from opencis.util.number import round_up_to_power_of_2, tlptoh16
from opencis.pci.component.fifo_pair import FifoPair
from opencis.pci.component.packet_processor import PacketProcessor

from opencis.cxl.transport.transaction import (
    BasePacket,
    CxlIoBasePacket,
    CxlIoMemWrPacket,
    CxlIoMemReqPacket,
    CxlIoCompletionPacket,
    CxlIoCompletionWithDataPacket,
)


class MEMORY_TYPE(IntEnum):
    ADDRESS_32BIT = 0b00
    ADDRESS_64BIT = 0b10


@dataclass
class BarInfo:
    prefetchable: bool = 0
    memory_type: MEMORY_TYPE = MEMORY_TYPE.ADDRESS_32BIT


@dataclass
class BarEntry:
    register: Optional[BitMaskedBitStructure] = None
    base_address: int = 0
    size_override: int = 0
    info: BarInfo = field(default_factory=BarInfo)


class MmioManager(PacketProcessor):
    def __init__(
        self,
        upstream_fifo: FifoPair,
        downstream_fifo: Optional[FifoPair] = None,
        label: Optional[str] = None,
    ):
        self._downstream_fifo: Optional[FifoPair]
        self._upstream_fifo: FifoPair

        super().__init__(upstream_fifo, downstream_fifo, label)
        self._memory_base = 0
        self._memory_limit = 0
        self._prefetchable_memory_base = 0
        self._prefetchable_memory_limit = 0
        self._bar_entries: List[BarEntry] = []
        self._req_id = 0

    # NOTE: Setting memory ranges is only used for bridge devices

    def set_memory_base(self, memory_base: int):
        if self._downstream_fifo is None:
            raise Exception("Setting memory base is prohibited for an endpoint device")
        logger.debug(self._create_message(f"Setting memory base to 0x{memory_base:08x}"))
        self._memory_base = memory_base

    def set_memory_limit(self, memory_limit: int):
        if self._downstream_fifo is None:
            raise Exception("Setting memory base is prohibited for an endpoint device")
        logger.debug(self._create_message(f"Setting memory limit to 0x{memory_limit:08x}"))
        self._memory_limit = memory_limit

    def set_prefetchable_memory_base(self, memory_base: int):
        if self._downstream_fifo is None:
            raise Exception("Setting memory base is prohibited for an endpoint device")
        self._prefetchable_memory_base = memory_base

    def set_prefetchable_memory_limit(self, memory_limit: int):
        if self._downstream_fifo is None:
            raise Exception("Setting memory base is prohibited for an endpoint device")
        self._prefetchable_memory_limit = memory_limit

    def set_bar_entries(self, bar_entries: List[BarEntry]):
        self._bar_entries = bar_entries

    def get_bar_size(self, index: int) -> int:
        # TODO: Handle Bar with 64bit address
        if index >= len(self._bar_entries):
            return 0
        entry = self._bar_entries[index]
        if entry.register and entry.size_override == 0:
            size = len(entry.register)
        elif entry.size_override > 0:
            size = entry.size_override
        else:
            return 0

        # size must be minimum of 0x1000
        return round_up_to_power_of_2(max(size, 0x1000))

    def get_bar_info(self, index: int) -> Optional[BarInfo]:
        if index >= len(self._bar_entries):
            return None
        return self._bar_entries[index].info

    def set_bar(self, index: int, base_address: int):
        if index >= len(self._bar_entries):
            return
        logger.debug(self._create_message(f"[BAR] setting BAR{index} = 0x{base_address:08x}"))
        self._bar_entries[index].base_address = base_address

    def _get_register_and_offset(
        self, address: int, size: int
    ) -> Optional[Tuple[BitMaskedBitStructure, int]]:
        for entry in self._bar_entries:
            if entry.base_address == 0:
                continue
            if not entry.register:
                continue
            if address < entry.base_address:
                continue
            end_address = address + size - 1
            end_register = entry.base_address + len(entry.register) - 1
            if end_address > end_register:
                continue
            offset = address - entry.base_address
            return entry.register, offset
        return None, None

    async def _send_completion(
        self, req_id: int, tag: int, data: int = None, data_len: int = 0, ld_id: int = 0
    ):
        if data is not None:
            if isinstance(data, int) and data >= (1 << (data_len * 8)):
                # if isinstance(data, MagicMock), then just assume it'll fit in the given size
                raise Exception(f"'Data: {data} could not possibly fit within length: {data_len}")
            packet = CxlIoCompletionWithDataPacket.create(
                req_id, tag, data, pload_len=data_len, ld_id=ld_id
            )
        else:
            packet = CxlIoCompletionPacket.create(req_id=req_id, tag=tag, ld_id=ld_id)

        packet.cpl_header.req_id = self._req_id
        await self._upstream_fifo.target_to_host.put(packet)

    async def _forward_request(self, packet: CxlIoBasePacket):
        logger.debug(self._create_message("Forwarding request to the next child device"))
        await self._downstream_fifo.host_to_target.put(packet)

    async def read_mmio(self, addr: int, size: int, bar_id: int = 0):
        addr = self._bar_entries[bar_id].base_address + addr
        register, offset = self._get_register_and_offset(addr, size)
        return register.read_bytes(offset, offset + size - 1)

    async def write_mmio(self, addr: int, size: int, data: int, bar_id: int = 0):
        addr = self._bar_entries[bar_id].base_address + addr
        register, offset = self._get_register_and_offset(addr, size)
        register.write_bytes(offset, offset + size - 1, data)

    async def _process_mmio_packet(self, mem_req_packet: CxlIoMemReqPacket):
        address = mem_req_packet.get_address()
        size = mem_req_packet.get_data_size()
        req_id = tlptoh16(mem_req_packet.mreq_header.req_id)
        tag = mem_req_packet.mreq_header.tag
        ld_id = mem_req_packet.tlp_prefix.ld_id

        register, offset = self._get_register_and_offset(address, size)
        if register is None and offset is None:
            if self._should_forward_packet(address, size):
                await self._forward_request(mem_req_packet)
            else:
                if mem_req_packet.is_mem_read():
                    logger.debug(self._create_message(f"RD: 0x{address:x}[{size}] OOB"))
                    await self._send_completion(req_id, tag, data=0, data_len=size, ld_id=ld_id)
                elif mem_req_packet.is_mem_write():
                    logger.debug(self._create_message(f"WR: 0x{address:x}[{size}] OOB"))
                else:
                    raise Exception("Unknown Mem request packet.")
            return

        start_offset = offset
        end_offset = offset + size - 1
        if mem_req_packet.is_mem_write():
            data = cast(CxlIoMemWrPacket, mem_req_packet).data
            logger.debug(self._create_message(f"WR: 0x{address:x}[{size}]=0x{data:08x}"))
            register.write_bytes(start_offset, end_offset, data)
        elif mem_req_packet.is_mem_read():
            logger.debug(self._create_message(f"RD: 0x{address:x}[{size}]"))
            data = register.read_bytes(start_offset, end_offset)
            await self._send_completion(req_id, tag, data, size, ld_id=ld_id)
        else:
            raise Exception("Unsupported MMIO packet")

    def _should_forward_packet(self, address: int, size: int) -> bool:
        if self._downstream_fifo is None:
            logger.debug(self._create_message("Downstream FIFO is not configured"))
            return False

        logger.debug(self._create_message("Checking if the request can be forwarded"))
        logger.debug(
            self._create_message(
                f"Memory Range: [{self._memory_base:08x}-{self._memory_limit:08x}]"
            )
        )

        # TODO: Support prefetchable address
        address_start = address
        address_end = address + size - 1
        if address_start >= self._memory_base and address_end <= self._memory_limit:
            logger.debug(self._create_message("Requested address is within the memory range"))
            return True

        logger.debug(self._create_message("Requested address is out of the memory range"))
        return False

    async def _process_host_to_target(self, run_once: bool = False):
        logger.debug(self._create_message("Started processing host to target fifo"))
        while True:
            packet = await self._upstream_fifo.host_to_target.get()
            if packet is None:
                logger.debug(self._create_message("Stopped processing host to target fifo"))
                break

            base_packet = cast(BasePacket, packet)
            cxl_io_packet = cast(CxlIoBasePacket, packet)
            if not base_packet.is_cxl_io() or not (
                cxl_io_packet.is_mem_read() or cxl_io_packet.is_mem_write()
            ):
                raise Exception(f"Received unexpected packet: {base_packet.get_type()}")
            self._req_id = packet.mreq_header.req_id
            logger.debug(self._create_message("Received host to target packet"))
            await self._process_mmio_packet(cast(CxlIoMemReqPacket, packet))

            if run_once:
                break
