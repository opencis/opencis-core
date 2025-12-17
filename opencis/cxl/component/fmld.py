"""
Copyright (c) 2024-2025, Eeum, Inc.

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
from opencis.cxl.transport.cci_packets import (
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
        total_capacity: int,
        dev_type: CXL_T3_DEV_TYPE,
        ld_count: int = 0,
        memory_sizes: List[int] = None,
        num_lds_supported: int = 16,  # Maximum number of LDs supported
        # TODO: to-LD fifo should be implemented during FM-API implementation
        downstream_fifo: Optional[FifoPair] = None,
        label: Optional[str] = None,
    ):
        super().__init__(label)
        self.downstream_fifo = downstream_fifo
        self.upstream_fifo = upstream_fifo
        self._total_capacity = total_capacity
        self._ld_count = ld_count
        self._dev_type = dev_type
        # Memory Granularity encoding per CXL spec:
        # 0h = 256 MB, 1h = 512 MB, 2h = 1 GB
        self._memory_granularity = 0  # Default: 256MB
        self._num_lds_supported = num_lds_supported

        # DEBUG: Log initialization parameters
        logger.info("FMLD DEBUG: Initialization parameters:")
        logger.info(f"  ld_count: {ld_count}")
        logger.info(f"  memory_sizes: {memory_sizes}")
        logger.info(
            f"  total_capacity: {total_capacity} bytes ({total_capacity / (1024*1024*1024):.2f} GB)"
        )

        # Key: LD ID, value: allocation multiplier
        # e.g., {0:2, 1:2, 2:1, 3:1}
        # ld_id of 0 has 512M of memory (multiplier 2)
        # ld_id of 1 has 512M of memory (multiplier 2)
        # ld_id of 2 has 256M of memory (multiplier 1)
        # ld_id of 3 has 256M of memory (multiplier 1)
        self._ld_allocations = {}
        self._ld_memory_sizes = {}  # Track actual memory sizes for each LD

        if ld_count > 0:
            # Pre-configured LDs - calculate allocation multipliers from memory sizes
            # Granularity based on memory_granularity: 0h=256MB, 1h=512MB, 2h=1GB
            granularity_bytes = (256 * 1024 * 1024) * (2**self._memory_granularity)
            if memory_sizes and len(memory_sizes) == ld_count:
                logger.info("FMLD DEBUG: Using memory_sizes for initialization")
                for i in range(ld_count):
                    memory_size_bytes = memory_sizes[i]
                    allocation_multiplier = memory_size_bytes // granularity_bytes
                    if allocation_multiplier == 0:
                        allocation_multiplier = 1  # Minimum 1 unit
                    self._ld_allocations[i] = allocation_multiplier
                    self._ld_memory_sizes[i] = memory_size_bytes
                    logger.info(
                        f"FMLD initialized LD {i} with {memory_size_bytes} bytes "
                        f"(allocation multiplier {allocation_multiplier})"
                    )
            else:
                logger.info("FMLD DEBUG: Falling back to default initialization")
                logger.info(f"  memory_sizes is None: {memory_sizes is None}")
                logger.info(f"  len(memory_sizes): {len(memory_sizes) if memory_sizes else 'N/A'}")
                logger.info(f"  ld_count: {ld_count}")
                # Fallback: set all to allocation multiplier 1
                for i in range(ld_count):
                    self._ld_allocations[i] = 1
                    self._ld_memory_sizes[i] = granularity_bytes  # Default based on granularity
                logger.info(
                    f"FMLD initialized with {ld_count} pre-configured LDs "
                    f"(default {granularity_bytes // (1024*1024)}MB each): {self._ld_allocations}"
                )
        else:
            # For dynamic configurations, start with empty allocations
            logger.info("FMLD initialized for dynamic configuration with no pre-configured LDs")

        # DEBUG: Log final state
        logger.info("FMLD DEBUG: Final initialization state:")
        logger.info(f"  _ld_allocations: {self._ld_allocations}")
        mem_sizes_mb = [size / (1024 * 1024) for size in self._ld_memory_sizes.values()]
        logger.info(f"  _ld_memory_sizes: {mem_sizes_mb} MB")

    async def _process_get_ld_info_packet(self, get_ld_info_request_packet: CciRequestPacket):
        if get_ld_info_request_packet.get_command_opcode() != CCI_FM_API_COMMAND_OPCODE.GET_LD_INFO:
            raise Exception("Invalid command opcode")
        logger.info(f"Get LD Info Request: {get_ld_info_request_packet}")

        # DEBUG: Log current state
        logger.info(f"FMLD DEBUG: _ld_allocations = {self._ld_allocations}")
        logger.info(f"FMLD DEBUG: _ld_memory_sizes = {self._ld_memory_sizes}")

        # Calculate the sum of currently allocated LD memory sizes
        # This is what the UI expects to see
        allocated_memory_size = 0
        for ld_id, multiplier in self._ld_allocations.items():
            if multiplier > 0:
                # Get the actual memory size for this LD
                if ld_id in self._ld_memory_sizes:
                    # Use actual memory size from _ld_memory_sizes (stored in bytes)
                    memory_size_bytes = self._ld_memory_sizes[ld_id]
                    allocated_memory_size += memory_size_bytes
                    mb_size = memory_size_bytes / (1024 * 1024)
                    logger.info(
                        f"FMLD: Using actual memory size for LD {ld_id}: "
                        f"{memory_size_bytes} bytes ({mb_size:.1f} MB)"
                    )
                else:
                    # Fallback to default size based on allocation multiplier and granularity
                    granularity_bytes = (256 * 1024 * 1024) * (2**self._memory_granularity)
                    fallback_size = multiplier * granularity_bytes
                    allocated_memory_size += fallback_size
                    mb_size = fallback_size / (1024 * 1024)
                    logger.info(
                        f"FMLD: Using default memory size for LD {ld_id}: "
                        f"{fallback_size} bytes ({mb_size:.0f} MB)"
                    )

        memory_size = allocated_memory_size

        # Get the number of LDs supported from config
        num_lds_supported = getattr(self, "_num_lds_supported", 16)  # Default to 16 if not set

        # Calculate the actual number of allocated LDs
        ld_count = sum(1 for multiplier in self._ld_allocations.values() if multiplier > 0)

        attr_val = getattr(self, "_num_lds_supported", "NOT_SET")
        logger.info(f"FMLD: num_lds_supported = {num_lds_supported} (attr = {attr_val})")
        logger.info(f"FMLD: ld_count (allocated) = {ld_count}")

        logger.info(f"LD Count (allocated): {ld_count}")
        logger.info(f"Total Capacity: {self._total_capacity}")
        mem_size_mb = memory_size / (1024 * 1024)
        logger.info(f"Memory Size (Total Capacity): {memory_size} bytes ({mem_size_mb:.2f} MB)")

        # DEBUG: Check for problematic values
        if memory_size == 1024:
            logger.error("FMLD DEBUG: Memory size is 1024 bytes (1 KB) - this is the bug!")
        elif memory_size == 0:
            logger.error("FMLD DEBUG: Memory size is 0 bytes - no allocations found!")
        elif memory_size < 1024 * 1024:
            logger.warning(f"FMLD DEBUG: Memory size is very small: {memory_size} bytes")

        # Create response payload with capacity information
        # pylint: disable=unused-variable
        from opencis.cxl.cci.fabric_manager.mld_components.get_ld_info import (
            GetLdInfoResponsePayload,
        )

        response_payload = GetLdInfoResponsePayload(  # noqa: F841
            memory_size=memory_size,
            ld_count=ld_count,  # Use actual number of allocated LDs
            qos_telemetry_capability=0,
            total_capacity=self._total_capacity,  # Total capacity from FMLD
            max_capacity=self._total_capacity,  # Max capacity is same as total for now
            device_capacity=memory_size,  # Device capacity is current allocated memory
        )

        get_ld_info_response_packet = GetLdInfoResponsePacket.create(
            memory_size=memory_size,
            ld_count=ld_count,  # Return actual number of allocated LDs
            message_tag=get_ld_info_request_packet.cci_msg_header.message_tag,
        )
        await self.upstream_fifo.target_to_host.put(get_ld_info_response_packet)
        logger.info("Get LD Info Response sent done")

    async def _process_get_ld_allocations_packet(
        self, request_packet: GetLdAllocationsRequestPacket
    ):
        if request_packet.get_command_opcode() != CCI_FM_API_COMMAND_OPCODE.GET_LD_ALLOCATIONS:
            raise Exception("Invalid command opcode")

        # Clean up any LD IDs beyond the supported range
        num_lds_supported = getattr(self, "_num_lds_supported", 16)
        logger.info(f"FMLD: Before cleanup - _ld_allocations keys: {sorted(self._ld_allocations)}")
        lds_to_remove = [ld_id for ld_id in self._ld_allocations if ld_id >= num_lds_supported]
        for ld_id in lds_to_remove:
            del self._ld_allocations[ld_id]
            if ld_id in self._ld_memory_sizes:
                del self._ld_memory_sizes[ld_id]
        if lds_to_remove:
            logger.info(
                f"FMLD: Cleaned up LD IDs beyond range ({num_lds_supported}): {lds_to_remove}"
            )
        logger.info(f"FMLD: After cleanup - _ld_allocations keys: {sorted(self._ld_allocations)}")

        start_ld_id = request_packet.payload.start_ld_id
        ld_allocation_list_limit = request_packet.payload.ld_allocation_list_limit

        # Get the number of LDs supported from config
        num_lds_supported = getattr(self, "_num_lds_supported", 16)  # Default to 16 if not set

        if start_ld_id < 0:
            raise Exception("Invalid start_ld_id")

        # Calculate the end LD ID based on the limit
        # If limit is 0, return all LDs from start_ld_id to num_lds_supported
        if ld_allocation_list_limit == 0:
            end_ld_id = num_lds_supported
        else:
            end_ld_id = min(start_ld_id + ld_allocation_list_limit, num_lds_supported)

        # Calculate number of allocated lds and create allocation multipliers
        # Only include LDs in the requested range [start_ld_id, end_ld_id)
        number_of_lds = 0
        ld_allocation_multipliers = {}

        # Populate the allocation multipliers for the requested range
        for ld_id in range(start_ld_id, end_ld_id):
            if ld_id in self._ld_allocations and self._ld_allocations[ld_id] > 0:
                # LD is allocated
                ld_allocation_multipliers[ld_id] = self._ld_allocations[ld_id]
                number_of_lds += 1
            else:
                # LD is not allocated or deallocated
                ld_allocation_multipliers[ld_id] = 0

        # Check if all LDs in the range are deallocated
        all_deallocated = number_of_lds == 0

        # If all LDs are deallocated, log it
        if all_deallocated:
            logger.info("FMLD: All LDs are deallocated, returning 0 for number_of_lds")
            logger.info(
                f"FMLD: Returning {number_of_lds} allocated LDs "
                f"(0 allocated, {num_lds_supported} slots available)"
            )
        else:
            logger.info(f"FMLD: {number_of_lds} LDs are currently allocated")

        get_ld_allocations_response_packet = GetLdAllocationsResponsePacket.create(
            number_of_lds=number_of_lds,  # Number of currently allocated LDs
            memory_granularity=self._memory_granularity,
            start_ld_id=start_ld_id,
            ld_length=len(
                ld_allocation_multipliers
            ),  # Total LD allocation list length (including deallocated)
            ld_allocations=ld_allocation_multipliers,  # Allocation multipliers (0 if dealloc)
            message_tag=request_packet.cci_msg_header.message_tag,
        )

        await self.upstream_fifo.target_to_host.put(get_ld_allocations_response_packet)
        logger.info("Get LD Allocations Response sent done")

    async def _process_set_ld_allocations_packet(
        self, request_packet: SetLdAllocationsRequestPacket
    ):
        if request_packet.get_command_opcode() != CCI_FM_API_COMMAND_OPCODE.SET_LD_ALLOCATIONS:
            raise Exception("Invalid command opcode")

        number_of_lds = request_packet.payload.number_of_lds
        start_ld_id = request_packet.payload.start_ld_id
        ld_allocation_list_bytes = request_packet.payload.ld_allocation_list

        # Validate number_of_lds according to CXL specification
        if number_of_lds < 1:
            logger.error(
                f"FMLD: Invalid number_of_lds={number_of_lds}. "
                "CXL specification requires minimum value of 1."
            )
            # Return error response
            response_packet = SetLdAllocationsResponsePacket.create(
                number_of_lds=0,
                start_ld_id=start_ld_id,
                ld_allocations={},
                message_tag=request_packet.cci_msg_header.message_tag,
            )
            await self.upstream_fifo.target_to_host.put(response_packet)
            logger.info("Set LD Allocations Response sent (error)")
            return

        # Dynamically expand _ld_allocations if needed, but respect num_lds_supported limit
        max_ld_id = start_ld_id + number_of_lds - 1
        current_max_ld_id = max(self._ld_allocations.keys()) if self._ld_allocations else -1

        # Validate that requested LD IDs don't exceed num_lds_supported
        if max_ld_id >= self._num_lds_supported:
            logger.error(
                f"FMLD: Requested LD ID {max_ld_id} "
                f"exceeds num_lds_supported ({self._num_lds_supported})"
            )
            # Return error response
            response_packet = SetLdAllocationsResponsePacket.create(
                number_of_lds=0,
                start_ld_id=start_ld_id,
                ld_allocations={},
                message_tag=request_packet.cci_msg_header.message_tag,
            )
            await self.upstream_fifo.target_to_host.put(response_packet)
            logger.info("Set LD Allocations Response sent (error - LD ID exceeds supported range)")
            return

        if max_ld_id > current_max_ld_id:
            # Expand the dictionary to accommodate new LDs, but only up to num_lds_supported
            for i in range(current_max_ld_id + 1, max_ld_id + 1):
                self._ld_allocations[i] = 0  # Initialize new LDs as unallocated
            logger.info(f"Expanded LD allocations to support LD IDs up to {max_ld_id}")

        # Parse the allocation list to determine allocation/deallocation
        # Each LD allocation entry is 16 bytes (8 bytes for range1 + 8 bytes for range2)

        # Check if this is a "deallocate all" request (all range1 values are 0)
        all_range1_zero = True
        for i in range(number_of_lds):
            offset = i * 16
            if offset + 8 <= len(ld_allocation_list_bytes):
                range1 = int.from_bytes(ld_allocation_list_bytes[offset : offset + 8], "little")
                if range1 > 0:
                    all_range1_zero = False
                    break

        if all_range1_zero and number_of_lds >= 0:
            # This is a "deallocate all" request - set all supported LDs to 0 instead of clearing
            # This maintains position structure so the UI can show gaps
            logger.info(
                "FMLD: Detected deallocate all request, setting all supported LDs "
                f"(0-{self._num_lds_supported-1}) to 0"
            )

            # Only deallocate LDs within the supported range
            for ld_id in range(self._num_lds_supported):
                self._ld_allocations[ld_id] = 0
                if ld_id in self._ld_memory_sizes:
                    del self._ld_memory_sizes[ld_id]

            # Remove any LD IDs that are beyond the supported range
            lds_to_remove = [
                ld_id for ld_id in self._ld_allocations if ld_id >= self._num_lds_supported
            ]
            for ld_id in lds_to_remove:
                del self._ld_allocations[ld_id]
                if ld_id in self._ld_memory_sizes:
                    del self._ld_memory_sizes[ld_id]

            logger.info(
                f"FMLD: Set all supported LDs (0-{self._num_lds_supported-1}) to 0 "
                f"and removed LDs beyond supported range: {lds_to_remove}"
            )
        else:
            # Process individual LD allocations/deallocations
            # First, clear any LDs that are not in the request range (partial deallocation behavior)
            request_ld_ids = set(range(start_ld_id, start_ld_id + number_of_lds))
            lds_to_remove = []
            for existing_ld_id in self._ld_allocations:
                if existing_ld_id not in request_ld_ids:
                    lds_to_remove.append(existing_ld_id)

            if lds_to_remove:
                logger.info(
                    f"FMLD: Partial deallocation - clearing LDs not in request: {lds_to_remove}"
                )
                for ld_id in lds_to_remove:
                    # Set to 0 instead of removing to maintain position structure
                    self._ld_allocations[ld_id] = 0
                    if ld_id in self._ld_memory_sizes:
                        del self._ld_memory_sizes[ld_id]
                    logger.info(f"Cleared LD {ld_id} (set to 0 to maintain position)")

            # Now process the LDs specified in the request
            for i in range(number_of_lds):
                ld_id = start_ld_id + i
                offset = i * 16

                if offset + 8 <= len(ld_allocation_list_bytes):
                    # Extract range1 value (first 8 bytes of the entry)
                    range1 = int.from_bytes(ld_allocation_list_bytes[offset : offset + 8], "little")

                    if range1 > 0:
                        # Allocate the LD
                        # range1 is the memory size in KB, convert to allocation multiplier
                        memory_size_kb = range1
                        memory_size_bytes = memory_size_kb * 1024
                        # Calculate granularity based on memory_granularity encoding:
                        # 0h = 256MB, 1h = 512MB, 2h = 1GB
                        granularity_bytes = (256 * 1024 * 1024) * (2**self._memory_granularity)
                        allocation_multiplier = memory_size_bytes // granularity_bytes
                        if allocation_multiplier == 0:
                            allocation_multiplier = 1  # Minimum 1 unit

                        # Store the allocation multiplier
                        self._ld_allocations[ld_id] = allocation_multiplier
                        # Store the memory size in bytes
                        self._ld_memory_sizes[ld_id] = memory_size_bytes
                        mb_size = memory_size_bytes / (1024 * 1024)
                        logger.info(
                            f"Allocated LD {ld_id} with allocation multiplier "
                            f"{allocation_multiplier} "
                            f"(memory size {memory_size_bytes} bytes = {mb_size:.0f} MB)"
                        )
                    elif range1 == 0:
                        # Deallocate the LD - set to 0 to maintain position structure
                        # All other LDs keep their positions when one is deallocated
                        self._ld_allocations[ld_id] = 0
                        # Remove memory size tracking for this LD
                        if ld_id in self._ld_memory_sizes:
                            del self._ld_memory_sizes[ld_id]
                        logger.info(f"Deallocated LD {ld_id} (set to 0 to maintain position)")
                    else:
                        # Invalid range1 value
                        logger.warning(f"Invalid range1 value {range1} for LD {ld_id}")
                else:
                    logger.warning(f"Not enough data for LD {ld_id} allocation entry")

        logger.info(f"Updated LD allocations: {self._ld_allocations}")
        allocated_count = sum(1 for v in self._ld_allocations.values() if v > 0)
        logger.info(f"FMLD: Number of allocated LDs: {allocated_count}")
        logger.info(f"FMLD: Total LDs in structure: {len(self._ld_allocations)}")
        deallocated_count = sum(1 for v in self._ld_allocations.values() if v == 0)
        logger.info(f"FMLD: Deallocated LDs (value 0): {deallocated_count}")

        response_packet = SetLdAllocationsResponsePacket.create(
            number_of_lds=number_of_lds,
            start_ld_id=start_ld_id,
            ld_allocations=self._ld_allocations,
            message_tag=request_packet.cci_msg_header.message_tag,
        )
        await self.upstream_fifo.target_to_host.put(response_packet)
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
