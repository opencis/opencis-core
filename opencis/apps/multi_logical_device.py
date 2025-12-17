"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from asyncio import gather, create_task
from typing import List
from opencis.cxl.component.cxl_connection import CxlConnection
from opencis.util.component import RunnableComponent
from opencis.cxl.device.cxl_type3_device import CxlType3Device, CXL_T3_DEV_TYPE
from opencis.cxl.component.switch_connection_client import SwitchConnectionClient
from opencis.cxl.component.cxl_component import CXL_COMPONENT_TYPE
from opencis.cxl.component.cxl_packet_processor import FifoGroup
from opencis.util.logger import logger
from opencis.cxl.device.config.logical_device import MultiLogicalDeviceConfig


class MultiLogicalDevice(RunnableComponent):
    def __init__(
        self,
        config: MultiLogicalDeviceConfig,
        cxl_connections: List[CxlConnection] = None,
    ):
        label = f"Port{config.port_index}"
        super().__init__(label)

        self._cxl_type3_devices: List[CxlType3Device] = []
        self._test_mode = getattr(config, "test_mode", False)
        self._total_capacity = config.total_capacity
        self._used_capacity = 0  # Track used capacity for dynamic LD creation
        self._config = config

        assert len(config.memory_sizes) == len(
            config.memory_files
        ), "memory_sizes, and memory_files must have the same length"
        ld_count = len(config.memory_sizes)

        # Calculate initial used capacity from static configuration
        # For dynamic configurations (ld_count = 0), start with 0 used capacity
        if ld_count == 0:
            self._used_capacity = 0
            logger.info(
                f"MLD Port{config.port_index}: Dynamic config - starting with 0 used capacity"
            )
        else:
            self._used_capacity = sum(config.memory_sizes) if config.memory_sizes else 0

        logger.info(
            f"MLD Port{config.port_index}: Total capacity = {self._total_capacity} bytes, "
            f"Initial used capacity = {self._used_capacity} bytes"
        )

        assert (
            not getattr(config, "test_mode", False) or cxl_connections is not None
        ), "cxl_connections must be passed in test mode"
        assert (
            getattr(config, "test_mode", False) or cxl_connections is None
        ), "cxl_connections must not be passed in non-test mode"

        if cxl_connections is not None:
            self._cxl_connections = cxl_connections
        else:
            self._sw_conn_client = SwitchConnectionClient(
                config.port_index,
                CXL_COMPONENT_TYPE.LD,
                ld_count=ld_count,
                mld_config=config,
                host=getattr(config, "host", "0.0.0.0"),
                port=getattr(config, "port", 8000),
            )
            self._cxl_connections = self._sw_conn_client.get_cxl_connection()

        # Handle the case where there are no logical devices (empty configuration)
        if ld_count == 0:
            # No logical devices to create, just initialize empty lists
            self._cxl_type3_devices = []
            return

        # Ensure _cxl_connections is a list for indexing
        if not isinstance(self._cxl_connections, list):
            self._cxl_connections = [self._cxl_connections]

        base_outgoing = FifoGroup(
            self._cxl_connections[0].cfg_fifo.target_to_host,
            self._cxl_connections[0].mmio_fifo.target_to_host,
            self._cxl_connections[0].cxl_mem_fifo.target_to_host,
            self._cxl_connections[0].cxl_cache_fifo.target_to_host,
            self._cxl_connections[0].cci_fifo.target_to_host,
        )

        # Share the outgoing queue across multiple LDs
        # TODO: avoid creation at all
        if ld_count > 1:
            for i in range(1, ld_count):
                connection = self._cxl_connections[i]
                connection.cfg_fifo.target_to_host = base_outgoing.cfg_space
                connection.mmio_fifo.target_to_host = base_outgoing.mmio
                connection.cxl_mem_fifo.target_to_host = base_outgoing.cxl_mem
                connection.cxl_cache_fifo.target_to_host = base_outgoing.cxl_cache
                connection.cci_fifo.target_to_host = base_outgoing.cci_fifo

        for ld in range(ld_count):
            cxl_type3_device = CxlType3Device(
                transport_connection=self._cxl_connections[ld],
                memory_size=config.memory_sizes[ld],
                memory_file=config.memory_files[ld],
                serial_number=config.serial_numbers[ld],
                dev_type=CXL_T3_DEV_TYPE.MLD,
                label=label,
            )
            self._cxl_type3_devices.append(cxl_type3_device)

    def get_total_capacity(self) -> int:
        """Get the total capacity of the MLD device in bytes."""
        return self._total_capacity

    def get_used_capacity(self) -> int:
        """Get the currently used capacity in bytes."""
        return self._used_capacity

    def get_remaining_capacity(self) -> int:
        """Get the remaining available capacity in bytes."""
        return self._total_capacity - self._used_capacity

    def get_devices(self) -> List[CxlType3Device]:
        """Get the list of CXL Type 3 devices."""
        return self._cxl_type3_devices

    def reset_capacity(self):
        """Reset used capacity to match current devices."""
        # Calculate actual used capacity based on current devices
        actual_used_capacity = sum(device.get_memory_size() for device in self._cxl_type3_devices)
        old_used_capacity = self._used_capacity
        self._used_capacity = actual_used_capacity
        logger.info(
            f"Reset capacity: old_used={old_used_capacity}, actual_used={actual_used_capacity}, "
            f"total={self._total_capacity}, remaining={self.get_remaining_capacity()}"
        )

        # Log individual device memory sizes for debugging
        for i, device in enumerate(self._cxl_type3_devices):
            mem_size = device.get_memory_size()
            mb_size = mem_size / (1024 * 1024)
            dev_label = device.get_label() or "unknown"
            logger.info(
                f"Device {i}: memory_size={mem_size} bytes ({mb_size:.1f} MB), "
                f"label={dev_label}"
            )

    def _validate_capacity_for_dynamic_lds(self, memory_sizes: List[int]) -> bool:
        """Validate that the requested memory sizes don't exceed total capacity."""
        requested_capacity = sum(memory_sizes)
        remaining_capacity = self._total_capacity - self._used_capacity

        logger.info(
            f"Capacity validation: requested={requested_capacity} bytes, "
            f"total={self._total_capacity} bytes, used={self._used_capacity} bytes, "
            f"remaining={remaining_capacity} bytes"
        )

        if requested_capacity > remaining_capacity:
            return False
        return True

    async def create_logical_devices_dynamically(
        self,
        ld_ids: List[int],
        memory_sizes: List[int] = None,
        memory_files: List[str] = None,
        serial_numbers: List[str] = None,
    ):
        """Dynamically create logical devices at runtime.

        Args:
            ld_ids: List of LD IDs to create
            memory_sizes: Memory sizes for each LD (default: 256M each)
            memory_files: Memory files for each LD (default: auto-generated)
            serial_numbers: Serial numbers for each LD (default: auto-generated)
        """

        if not ld_ids:
            logger.warning("No LD IDs provided for dynamic creation")
            return False

        # Set defaults if not provided
        if memory_sizes is None:
            memory_sizes = [256 * 1024 * 1024] * len(ld_ids)  # 256M each
        if memory_files is None:
            memory_files = [f"/tmp/ld_{ld_id}.mem" for ld_id in ld_ids]
        if serial_numbers is None:
            # Generate valid hex serial numbers that can be converted to integers
            # Create 16-character hex strings like the original format
            serial_numbers = [f"{ld_id:016X}" for ld_id in ld_ids]

        logger.info(f"Creating {len(ld_ids)} logical devices dynamically: {ld_ids}")

        # Validate capacity before creating logical devices
        if not self._validate_capacity_for_dynamic_lds(memory_sizes):
            requested_capacity = sum(memory_sizes)
            remaining_capacity = self._total_capacity - self._used_capacity
            # Convert bytes to MB/GB for better readability
            requested_mb = requested_capacity / (1024 * 1024)
            remaining_mb = remaining_capacity / (1024 * 1024)
            total_mb = self._total_capacity / (1024 * 1024)
            used_mb = self._used_capacity / (1024 * 1024)

            error_msg = (
                "Backend capacity exceeded. The backend has insufficient memory capacity "
                'to allocate the requested LDs. Try using "Force Clear All LDs" to free up '
                "memory, or reduce the number/size of LDs you are trying to allocate.\n\n"
                f"Details:\n- Requested: {requested_mb:.1f} MB ({requested_capacity:,} bytes)\n"
                f"- Available: {remaining_mb:.1f} MB ({remaining_capacity:,} bytes)\n"
                f"- Total capacity: {total_mb:.1f} MB ({self._total_capacity:,} bytes)\n"
                f"- Currently used: {used_mb:.1f} MB ({self._used_capacity:,} bytes)"
            )
            logger.error(error_msg)
            return False

        # Ensure we have a switch connection client with enough connections
        if not hasattr(self, "_sw_conn_client"):
            self._sw_conn_client = SwitchConnectionClient(
                self._config.port_index,
                CXL_COMPONENT_TYPE.LD,
                ld_count=len(ld_ids),
                host=getattr(self._config, "host", "0.0.0.0"),
                port=getattr(self._config, "port", 8000),
            )
            self._cxl_connections = self._sw_conn_client.get_cxl_connection()
        else:
            # Update existing connection client to support more LDs if needed
            current_connection_count = (
                len(self._cxl_connections) if isinstance(self._cxl_connections, list) else 1
            )
            if len(ld_ids) > current_connection_count:
                logger.info(
                    f"Updating connection client to support {len(ld_ids)} LDs "
                    f"(currently {current_connection_count})"
                )
                # Create a new connection client with the required number of connections
                self._sw_conn_client = SwitchConnectionClient(
                    self._config.port_index,
                    CXL_COMPONENT_TYPE.LD,
                    ld_count=len(ld_ids),
                    host=getattr(self._config, "host", "0.0.0.0"),
                    port=getattr(self._config, "port", 8000),
                )
                self._cxl_connections = self._sw_conn_client.get_cxl_connection()

        # Ensure _cxl_connections is a list
        if not isinstance(self._cxl_connections, list):
            self._cxl_connections = [self._cxl_connections]

        # Create logical devices
        for i, ld_id in enumerate(ld_ids):
            if i < len(self._cxl_connections):
                connection = self._cxl_connections[i]
            else:
                # This should not happen now since we ensure enough connections above
                logger.error(
                    f"Not enough connections for LD {ld_id} (index {i}), "
                    f"but we should have {len(self._cxl_connections)} connections"
                )
                continue

            cxl_type3_device = CxlType3Device(
                transport_connection=connection,
                memory_size=memory_sizes[i],
                memory_file=memory_files[i],
                serial_number=serial_numbers[i],
                dev_type=CXL_T3_DEV_TYPE.MLD,
                label=f"{self._label}_LD{ld_id}",
            )
            self._cxl_type3_devices.append(cxl_type3_device)

        # Update used capacity after successful creation
        self._used_capacity += sum(memory_sizes)
        logger.info(f"Successfully created {len(self._cxl_type3_devices)} logical devices")
        logger.info(
            f"Updated used capacity: {self._used_capacity} bytes, "
            f"remaining: {self.get_remaining_capacity()} bytes"
        )
        return True

    async def deallocate_logical_devices_dynamically(self, ld_ids: List[int]):
        """Dynamically deallocate logical devices at runtime.

        Args:
            ld_ids: List of LD IDs to deallocate
        """
        if not ld_ids:
            logger.warning("No LD IDs provided for dynamic deallocation")
            return False

        logger.info(f"Deallocating {len(ld_ids)} logical devices dynamically: {ld_ids}")
        current_devices = [
            f"{i}:{self.extract_ld_id_from_device(device)}"
            for i, device in enumerate(self._cxl_type3_devices)
        ]
        logger.info(f"Current devices: {current_devices}")

        # Find and remove the logical devices
        devices_to_remove = []
        total_deallocated_capacity = 0

        for ld_id in ld_ids:
            # Find the device with matching LD ID
            found_device = False
            for i, device in enumerate(self._cxl_type3_devices):
                # Extract LD ID from device label or other identifier
                device_ld_id = self.extract_ld_id_from_device(device)
                logger.info(
                    f"Checking device {i}: device_ld_id={device_ld_id}, requested_ld_id={ld_id}"
                )
                if device_ld_id == ld_id:
                    devices_to_remove.append((i, device))
                    total_deallocated_capacity += device.get_memory_size()
                    found_device = True
                    logger.info(f"Found device {i} with LD ID {device_ld_id} for deallocation")
                    break

            if not found_device:
                logger.warning(f"No device found with LD ID {ld_id} for deallocation")
                # Try to find by position instead of LD ID
                if ld_id < len(self._cxl_type3_devices):
                    device = self._cxl_type3_devices[ld_id]
                    device_ld_id = self.extract_ld_id_from_device(device)
                    devices_to_remove.append((ld_id, device))
                    total_deallocated_capacity += device.get_memory_size()
                    logger.info(
                        f"Found device at position {ld_id}, LD ID {device_ld_id}, for dealloc"
                    )
                else:
                    logger.error(
                        f"LD ID {ld_id} is out of range (max: {len(self._cxl_type3_devices) - 1})"
                    )

        # Stop all devices first
        for original_i, device in devices_to_remove:
            try:
                device_ld_id = self.extract_ld_id_from_device(device)
                await device.stop()
                logger.info(f"Stopped logical device {device_ld_id}")
            except Exception as e:
                logger.error(f"Error stopping logical device {device_ld_id}: {e}")

        # Remove devices from the list (in reverse order to maintain indices)
        for original_i, device in sorted(devices_to_remove, reverse=True):
            try:
                device_ld_id = self.extract_ld_id_from_device(device)
                if original_i < len(self._cxl_type3_devices):
                    del self._cxl_type3_devices[original_i]
                    logger.info(f"Successfully deallocated logical device {device_ld_id}")
                else:
                    logger.error(f"Invalid index {original_i} for device {device_ld_id}")
            except Exception as e:
                logger.error(f"Error removing logical device {device_ld_id}: {e}")

        # Update used capacity
        self._used_capacity -= total_deallocated_capacity
        logger.info(f"Successfully deallocated {len(devices_to_remove)} logical devices")
        logger.info(
            f"Updated used capacity: {self._used_capacity} bytes, "
            f"remaining: {self.get_remaining_capacity()} bytes"
        )
        # Reset capacity to ensure it matches actual devices
        self.reset_capacity()
        return True

    def extract_ld_id_from_device(self, device):
        """Extract LD ID from device label or other identifier."""
        import re

        # Try to extract LD ID from device label
        label = device.get_label() if hasattr(device, "get_label") else None
        if label:
            # Look for LD ID in the label (e.g., "Port1_LD16384" -> 16384)
            match = re.search(r"LD(\d+)", label)
            if match:
                return int(match.group(1))

        # Fallback: try to get LD ID from device index
        # This assumes the device index corresponds to the LD ID
        try:
            return self._cxl_type3_devices.index(device)
        except ValueError:
            return None

    async def _run(self):
        # pylint: disable=duplicate-code

        # Handle the case where there are no logical devices
        if not self._cxl_type3_devices:
            if not self._test_mode:
                await self._sw_conn_client.run()
            await self._change_status_to_running()
            if not self._test_mode:
                await self._sw_conn_client.wait_for_ready()
            return

        run_tasks = [create_task(device.run()) for device in self._cxl_type3_devices]
        wait_tasks = [create_task(device.wait_for_ready()) for device in self._cxl_type3_devices]
        if not self._test_mode:
            run_tasks += [create_task(self._sw_conn_client.run())]
            wait_tasks += [create_task(self._sw_conn_client.wait_for_ready())]

        await gather(*wait_tasks)
        await self._change_status_to_running()
        await gather(*run_tasks)

    async def _stop(self):
        # Handle the case where there are no logical devices
        if not self._cxl_type3_devices:
            if not self._test_mode:
                await self._sw_conn_client.stop()
            return

        stop_tasks = [create_task(device.stop()) for device in self._cxl_type3_devices]
        if not self._test_mode:
            stop_tasks += [create_task(self._sw_conn_client.stop())]

        await gather(*stop_tasks)
