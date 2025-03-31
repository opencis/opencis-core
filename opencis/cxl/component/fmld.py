"""
 Copyright (c) 2024, Eeum, Inc.

 This software is licensed under the terms of the Revised BSD License.
 See LICENSE for details.
"""

from asyncio import create_task, gather
from typing import Optional, cast, List
from opencis.cxl.cci.common import CCI_FM_API_COMMAND_OPCODE
from opencis.util.component import RunnableComponent
from opencis.util.logger import logger
from opencis.pci.component.fifo_pair import FifoPair
from opencis.cxl.device.cxl_type3_device import CXL_T3_DEV_TYPE
from opencis.cxl.transport.transaction import (
    CciRequestPacket,
    GetLdInfoRequestPacket,
    GetLdInfoResponsePacket,
    GetLdAllocationsRequestPacket,
    GetLdAllocationsResponsePacket,
    SetLdAllocationsRequestPacket,
    SetLdAllocationsResponsePacket,
)


class FMLD(RunnableComponent):
    def __init__(
        self,
        upstream_fifo: FifoPair,
        ld_count: int,
        dev_type: CXL_T3_DEV_TYPE,
        # TODO: to-LD fifo should be implemented during FM-API implementation
        downstream_fifo: Optional[FifoPair] = None,
        label: Optional[str] = None,
    ):
        super().__init__(label)
        self.downstream_fifo = downstream_fifo
        self.upstream_fifo = upstream_fifo
        self._ld_count = ld_count
        self._dev_type = dev_type
        self._memory_granularity = 256

        # Key: LD ID, value: remaining number of memory block(s)
        # e.g., {0:1, 1:3, 2:2}
        # ld_id of 0 has 256M of memory
        # ld_id of 1 has 768M of memory
        # ld_id of 2 has 512M of memory
        self._ld_dict = {i: 1 for i in range(ld_count)}

    async def _process_get_ld_info_packet(self, get_ld_info_request_packet: CciRequestPacket):
        if get_ld_info_request_packet.get_command_opcode() != CCI_FM_API_COMMAND_OPCODE.GET_LD_INFO:
            raise Exception("Invalid command opcode")
        logger.info(f"Get LD Info Request: {get_ld_info_request_packet}")
        memory_size = self._ld_count * 1024 * 1024 * 256
        logger.info(f"Memory Size: {memory_size:x}")
        logger.info(f"LD Count: {self._ld_count}")
        get_ld_info_response_packet = GetLdInfoResponsePacket.create(
            memory_size=memory_size,
            ld_count=self._ld_count,
            message_tag=get_ld_info_request_packet.header_data.message_tag,
        )
        logger.info(f"Get LD Info Response: {get_ld_info_response_packet}")
        await self.upstream_fifo.target_to_host.put(get_ld_info_response_packet)
        logger.info("Get LD Info Response sent done")

    async def _process_get_ld_allocations_packet(
        self, get_ld_allocations_packet: GetLdAllocationsRequestPacket
    ):
        if (
            get_ld_allocations_packet.get_command_opcode()
            != CCI_FM_API_COMMAND_OPCODE.GET_LD_ALLOCATIONS
        ):
            raise Exception("Invalid command opcode")
        logger.info(f"Get LD Allocations: {get_ld_allocations_packet}")

        start_ld_id = get_ld_allocations_packet.get_start_ld_id()
        ld_alloc_list_limit = get_ld_allocations_packet.get_ld_allocation_list_limit()

        if start_ld_id < 0 or start_ld_id >= len(self._ld_dict):
            raise Exception("Invalid start_ld_id")

        # Number of keys for self._allocated_ld_dict
        max_len_ld_list = len(self._ld_dict) - start_ld_id
        if ld_alloc_list_limit < max_len_ld_list:
            ld_length = ld_alloc_list_limit
        else:
            ld_length = max_len_ld_list

        # Calculate number of lds
        number_of_lds = 0
        for i in range(max_len_ld_list):
            if self._ld_dict.get(start_ld_id + i) == 1:
                number_of_lds += 1

        # Create allocated_ld list
        allocated_ld: List[int] = []
        allocated_ld_length = 0
        for i in range(ld_length):
            if self._ld_dict.get(start_ld_id + i) == 1:
                # Range 1 Allocation Multiplier: Hardcoded right now to always return 256M
                allocated_ld.append(1)
                # Range 2 Allocation Multiplier: Fixed to 0
                allocated_ld.append(0)
                allocated_ld_length += 1
            elif self._ld_dict.get(start_ld_id + i) == 0:
                break

        allocated_ld_bytes = b"".join(num.to_bytes(8, "little") for num in allocated_ld)

        get_ld_allocations_response_packet = GetLdAllocationsResponsePacket.create(
            number_of_lds=number_of_lds,
            memory_granularity=0,
            start_ld_id=start_ld_id,
            ld_allocation_list_length=allocated_ld_length,
            ld_allocation_list=int.from_bytes(allocated_ld_bytes, "little"),
            message_tag=get_ld_allocations_packet.header_data.message_tag,
        )

        await self.upstream_fifo.target_to_host.put(get_ld_allocations_response_packet)
        logger.info("Get LD Allocations Response sent done")

    async def _process_set_ld_allocations_packet(
        self, set_ld_allocations_packet: SetLdAllocationsRequestPacket
    ):
        if (
            set_ld_allocations_packet.get_command_opcode()
            != CCI_FM_API_COMMAND_OPCODE.SET_LD_ALLOCATIONS
        ):
            raise Exception("Invalid command opcode")
        logger.info(f"Set LD Allocations: {set_ld_allocations_packet}")

        number_of_lds = set_ld_allocations_packet.get_number_of_lds()
        start_ld_id = set_ld_allocations_packet.get_start_ld_id()

        ld_allocation_list = set_ld_allocations_packet.get_ld_allocation_list()

        ld_allocation_list = [
            int.from_bytes(ld_allocation_list[i : i + 8], "little")
            for i in range(0, len(ld_allocation_list), 8)
        ]

        # Boundary check
        number_of_lds = min(number_of_lds, len(self._ld_dict) - start_ld_id)

        response_number_of_lds = 0
        response_ld_allocated_list = []

        ld_allocation_list = ld_allocation_list[::2]

        # Create ld_allocation_list
        for i in range(number_of_lds):
            if self._ld_dict.get(start_ld_id + i) >= ld_allocation_list[i]:
                response_ld_allocated_list.append(ld_allocation_list[i])
                self._ld_dict[start_ld_id + i] = (
                    self._ld_dict[start_ld_id + i] - ld_allocation_list[i]
                )
                response_number_of_lds += 1
            elif self._ld_dict.get(start_ld_id + i) == 0:
                response_ld_allocated_list.append(0)
            elif self._ld_dict.get(start_ld_id + i) < ld_allocation_list[i]:
                response_ld_allocated_list.append(self._ld_dict.get(start_ld_id + i))
                self._ld_dict[start_ld_id + i] = 0
                response_number_of_lds += 1

        response_ld_allocated_list = [1, 0] * len(response_ld_allocated_list)

        response_ld_allocated_bytes = b"".join(
            num.to_bytes(8, "little") for num in response_ld_allocated_list
        )
        ld_allocation_list = int.from_bytes(response_ld_allocated_bytes, "little")

        set_ld_allocations_response_packet = SetLdAllocationsResponsePacket.create(
            number_of_lds=response_number_of_lds,
            start_ld_id=start_ld_id,
            ld_allocation_list=ld_allocation_list,
            message_tag=set_ld_allocations_packet.header_data.message_tag,
        )
        await self.upstream_fifo.target_to_host.put(set_ld_allocations_response_packet)
        logger.info("Set LD Allocations Response sent done")

    async def _process_fm_to_target(self):
        logger.info(self._create_message("Started processing FM-to-LD packets"))
        while True:
            packet = await self.upstream_fifo.host_to_target.get()
            logger.info(self._create_message(f"FMLD received FM-to-LD packet: {packet}"))
            if packet is None:
                logger.info(self._create_message("None packet received, stopping FM-to-LD packets"))
                break

            if packet.get_command_opcode() == CCI_FM_API_COMMAND_OPCODE.GET_LD_INFO:
                packet = cast(GetLdInfoRequestPacket, packet)
                await self._process_get_ld_info_packet(packet)
            elif packet.get_command_opcode() == CCI_FM_API_COMMAND_OPCODE.GET_LD_ALLOCATIONS:
                packet = cast(GetLdAllocationsRequestPacket, packet)
                await self._process_get_ld_allocations_packet(packet)
            elif packet.get_command_opcode() == CCI_FM_API_COMMAND_OPCODE.SET_LD_ALLOCATIONS:
                packet = cast(SetLdAllocationsRequestPacket, packet)
                await self._process_set_ld_allocations_packet(packet)
        logger.info(self._create_message("Stopped processing FM-to-LD packets"))

    # TODO: This function should be implemented for LD-to-FM API
    async def _process_target_to_fm(self):
        if self.downstream_fifo is None:
            logger.info(self._create_message("Skipped processing LD-to-FM packets"))
            return
        logger.info(self._create_message("Started processing LD-to-FM packets"))
        while True:
            packet = await self.downstream_fifo.target_to_host.get()
            if packet is None:
                logger.info(self._create_message("Stopped LD-to-FM packets"))
                break
            logger.info(self._create_message("Received LD-to-FM Packet"))
            await self.upstream_fifo.target_to_host.put(packet)

    async def _run(self):
        tasks = [
            create_task(self._process_fm_to_target()),
            create_task(self._process_target_to_fm()),
        ]
        await self._change_status_to_running()
        await gather(*tasks)

    async def _stop(self):
        logger.info(self._create_message("Stopping FMLD"))
        if self.downstream_fifo is not None:
            await self.downstream_fifo.target_to_host.put(None)
        await self.upstream_fifo.host_to_target.put(None)
