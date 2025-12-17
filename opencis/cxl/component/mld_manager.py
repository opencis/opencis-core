"""
MLD Manager for dynamic logical device creation and management.
"""

from typing import Dict, List, Optional

import socketio
from aiohttp import web

from opencis.util.logger import logger
from opencis.apps.multi_logical_device import MultiLogicalDevice


class MLDManager:
    """Global manager for Multi-Logical Device instances."""

    _instance = None
    _mld_instances: Dict[int, MultiLogicalDevice] = {}
    _sio_server = None
    _web_app = None
    _socket_server = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(MLDManager, cls).__new__(cls)
        return cls._instance

    @classmethod
    def get_instance(cls):
        """Get the singleton instance of MLDManager."""
        return cls()

    def register_mld(self, port_index: int, mld: MultiLogicalDevice):
        """Register an MLD instance for a specific port."""
        self._mld_instances[port_index] = mld
        logger.info(f"Registered MLD instance for port {port_index}")
        logger.info(
            f"MLD Manager now has {len(self._mld_instances)} registered instances: "
            f"{list(self._mld_instances.keys())}"
        )

    def get_mld(self, port_index: int) -> Optional[MultiLogicalDevice]:
        """Get the MLD instance for a specific port."""
        mld = self._mld_instances.get(port_index)
        logger.info(f"MLD Manager: get_mld({port_index}) returned: {mld is not None}")
        if mld is not None:
            logger.info(f"MLD Manager: Port {port_index} has {len(mld.get_devices())} devices")
        return mld

    def get_all_mlds(self) -> Dict[int, MultiLogicalDevice]:
        """Get all registered MLD instances."""
        return self._mld_instances.copy()

    async def create_logical_devices(
        self,
        port_index: int,
        ld_ids: List[int],
        memory_sizes: List[int] = None,
        memory_files: List[str] = None,
        serial_numbers: List[str] = None,
    ) -> bool:
        """Create logical devices dynamically for a specific port.

        Args:
            port_index: The port index to create LDs for
            ld_ids: List of LD IDs to create
            memory_sizes: Memory sizes for each LD
            memory_files: Memory files for each LD
            serial_numbers: Serial numbers for each LD

        Returns:
            True if successful, False otherwise
        """
        # Create logical devices
        if ld_ids:
            logger.info(f"Creating {len(ld_ids)} LD(s) for port {port_index}")

        mld = self.get_mld(port_index)
        if mld is None:
            # Create a new MLD instance dynamically for this port
            logger.info(f"No MLD instance found for port {port_index}, creating one dynamically")

            # Set defaults if not provided
            if memory_sizes is None:
                # Calculate actual memory sizes from LD IDs
                # LD IDs represent the memory size in KB (e.g., 204800 KB = 200MB)
                memory_sizes = []
                for ld_id in ld_ids:
                    # Convert LD ID (KB) to bytes
                    memory_size_bytes = ld_id * 1024
                    # Use a minimum of 1MB and maximum of 1GB
                    memory_size_bytes = max(1024 * 1024, min(memory_size_bytes, 1024 * 1024 * 1024))
                    memory_sizes.append(memory_size_bytes)
                    mb_size = memory_size_bytes / (1024 * 1024)
                    logger.info(
                        f"Calculated memory size for LD {ld_id}: "
                        f"{memory_size_bytes} bytes ({mb_size:.1f} MB)"
                    )
            if memory_files is None:
                memory_files = [f"/tmp/ld_{ld_id}.mem" for ld_id in ld_ids]
            if serial_numbers is None:
                serial_numbers = [f"{ld_id:016X}" for ld_id in ld_ids]

            # Set a reasonable total capacity for dynamic configuration
            # Use a default of 4GB or sum of memory_sizes, whichever is larger
            requested_capacity = sum(memory_sizes)
            default_capacity = 4 * 1024 * 1024 * 1024  # 4GB
            total_capacity = max(requested_capacity, default_capacity)

            # Create MLD configuration
            from opencis.cxl.device.config.logical_device import MultiLogicalDeviceConfig

            mld_config = MultiLogicalDeviceConfig(
                port_index=port_index,
                device_id=61445,  # Add required fields
                vendor_id=7621,
                subsystem_vendor_id=0,
                subsystem_id=0,
                memory_sizes=[],
                ld_list=[],
                memory_files=[],
                serial_numbers=[],
                total_capacity=total_capacity,
                ld_count=0,  # Start with no LDs
                num_lds_supported=16,  # Add this field
            )

            # Create and register the MLD instance
            mld = MultiLogicalDevice(mld_config)
            self.register_mld(port_index, mld)

            logger.info(
                f"Created dynamic MLD instance for port {port_index} "
                f"with capacity {total_capacity} bytes"
            )
        else:
            # Reset capacity of existing MLD instance to match current devices
            logger.info(f"Using existing MLD instance for port {port_index}, resetting capacity")
            mld.reset_capacity()

        try:
            success = await mld.create_logical_devices_dynamically(
                ld_ids, memory_sizes, memory_files, serial_numbers
            )
            if success:
                logger.info(
                    f"Successfully created {len(ld_ids)} logical devices for port {port_index}"
                )
                # Log capacity information after creation
                used_capacity = mld.get_used_capacity()
                remaining_capacity = mld.get_remaining_capacity()
                logger.info(
                    f"Port {port_index} capacity after creation: "
                    f"used={used_capacity} bytes, remaining={remaining_capacity} bytes"
                )
            return success
        except Exception as e:
            logger.error(f"Failed to create logical devices for port {port_index}: {e}")
            return False

    async def deallocate_logical_devices(self, port_index: int, ld_ids: List[int]) -> bool:
        """Deallocate logical devices for a specific port.

        Args:
            port_index: The port index to deallocate LDs from
            ld_ids: List of LD IDs to deallocate

        Returns:
            True if successful, False otherwise
        """
        # Deallocate logical devices
        if ld_ids:
            logger.info(f"Deallocating {len(ld_ids)} LD(s) for port {port_index}")

        mld = self.get_mld(port_index)
        if mld is None:
            logger.warning(
                f"No MLD instance found for port {port_index} - "
                f"this may be normal for dynamic configurations"
            )
            # For dynamic configurations, it's normal to not have an MLD instance
            # if no LDs are allocated
            # Return True to indicate successful deallocation (nothing to deallocate)
            return True

        try:
            success = await mld.deallocate_logical_devices_dynamically(ld_ids)
            if success:
                logger.info(
                    f"Successfully deallocated {len(ld_ids)} logical devices for port {port_index}"
                )

                # Log capacity information after deallocation
                used_capacity = mld.get_used_capacity()
                remaining_capacity = mld.get_remaining_capacity()
                logger.info(
                    f"Port {port_index} capacity after deallocation: "
                    f"used={used_capacity} bytes, remaining={remaining_capacity} bytes"
                )

                # Check if all LDs have been deallocated
                if len(mld.get_devices()) == 0:
                    logger.info(f"All LDs deallocated for port {port_index}, clearing MLD instance")
                    # Remove the MLD instance from the manager
                    if port_index in self._mld_instances:
                        del self._mld_instances[port_index]
                        logger.info(f"Cleared MLD instance for port {port_index}")

            return success
        except Exception as e:
            logger.error(f"Failed to deallocate logical devices for port {port_index}: {e}")
            return False

    def get_ld_count(self, port_index: int) -> int:
        """Get the number of logical devices for a specific port."""
        mld = self.get_mld(port_index)
        if mld is None:
            return 0
        return len(mld.get_devices())

    def get_ld_ids(self, port_index: int) -> List[int]:
        """Get the list of LD IDs for a specific port."""
        mld = self.get_mld(port_index)
        if mld is None:
            logger.warning(f"No MLD instance found for port {port_index}")
            return []

        device_count = len(mld.get_devices())
        ld_ids = list(range(device_count))
        logger.info(
            f"MLD Manager: Port {port_index} has {device_count} devices, returning LD IDs: {ld_ids}"
        )
        return ld_ids

    async def get_fmld_allocation_state(self, port_index: int) -> dict:
        """Get the FMLD allocation state for a port.

        Args:
            port_index: The port index to get allocation state for

        Returns:
            Dictionary containing allocation state information
        """
        try:
            # This would ideally query the FMLD component directly
            # For now, we'll return a placeholder that indicates we need to implement this
            logger.info(f"MLD Manager: Getting FMLD allocation state for port {port_index}")
            # TODO: Implement actual FMLD allocation state query
            return {"success": False, "message": "FMLD allocation state query not yet implemented"}
        except Exception as e:
            logger.error(f"Error getting FMLD allocation state for port {port_index}: {e}")
            return {"success": False, "error": str(e)}

    async def sync_with_switch_state(
        self, port_index: int, switch_ld_ids: List[int], fmld_allocation_list: List[int] = None
    ) -> bool:
        """Synchronize MLD Manager state with switch allocation state.

        Args:
            port_index: The port index to sync
            switch_ld_ids: List of LD IDs that are actually allocated in the switch
            fmld_allocation_list: FMLD allocation list (e.g., [2, 0, 1, 0] for LD0=512MB, LD1=256MB)

        Returns:
            True if synchronization was successful, False otherwise
        """
        logger.info(f"MLD Manager: Syncing port {port_index} with switch state: {switch_ld_ids}")
        if fmld_allocation_list:
            logger.info(f"FMLD allocation list: {fmld_allocation_list}")

        mld = self.get_mld(port_index)
        if mld is None:
            logger.info(f"No MLD instance found for port {port_index}, creating new one")
            # Create a new MLD instance if none exists
            mld = self.ensure_mld_instance(port_index)
            if mld is None:
                logger.error(f"Failed to create MLD instance for port {port_index}")
                return False

        # Get current MLD device count
        current_device_count = len(mld.get_devices())
        logger.info(f"MLD Manager: Port {port_index} currently has {current_device_count} devices")

        # If switch has no LDs allocated, clear all MLD devices
        if not switch_ld_ids:
            if current_device_count > 0:
                logger.info(
                    f"Switch has no LDs allocated, clearing all {current_device_count} MLD devices"
                )
                mld.get_devices().clear()
                mld.reset_capacity()
                logger.info(f"Cleared all devices for port {port_index}")
            return True

        # The switch reports LD IDs that are actually allocated
        # We need to update the MLD Manager's device list to match this state
        logger.info(f"Switch reports {len(switch_ld_ids)} allocated LDs: {switch_ld_ids}")

        # If MLD has more devices than switch, remove excess devices
        if current_device_count > len(switch_ld_ids):
            excess_count = current_device_count - len(switch_ld_ids)
            logger.info(f"MLD has {excess_count} excess devices, removing them")

            # Remove devices that are not in the switch allocation
            devices_to_remove = []
            devices_to_update = []  # Track devices that need memory size updates
            logger.info("Current MLD devices:")
            for i, device in enumerate(mld.get_devices()):
                dev_label = device.get_label()
                dev_serial = device.get_serial_number()
                logger.info(f"  Device {i}: {dev_label}, serial={dev_serial}")

                # Extract LD ID from device label or serial number
                device_ld_id = None
                if dev_label:
                    # Use regex to extract LD ID from label like "Port1_LD0"
                    import re

                    match = re.search(r"LD(\d+)", dev_label)
                    if match:
                        device_ld_id = int(match.group(1))
                        logger.info(f"    Extracted LD ID from label: {device_ld_id}")
                    else:
                        logger.warning(f"    Could not extract LD ID from label: {dev_label}")
                elif dev_serial:
                    # Extract LD ID from serial number like "0000000000000000"
                    try:
                        device_ld_id = int(dev_serial[-1], 16)
                        logger.info(f"    Extracted LD ID from serial: {device_ld_id}")
                    except (ValueError, IndexError):
                        logger.warning(f"    Could not extract LD ID from serial: {dev_serial}")

                if device_ld_id is not None and device_ld_id not in switch_ld_ids:
                    devices_to_remove.append(device)
                    logger.info(
                        f"    Marking device {dev_label} (LD {device_ld_id}) "
                        "for removal - not in switch allocation"
                    )
                elif device_ld_id is not None and device_ld_id in switch_ld_ids:
                    # Device is kept, but we need to update its memory size to match FMLD allocation
                    devices_to_update.append((device, device_ld_id))
                    logger.info(
                        f"    Keeping device {dev_label} (LD {device_ld_id}) - in switch allocation"
                    )
                elif device_ld_id is None:
                    logger.warning(f"    Could not determine LD ID for device {dev_label}")

            logger.info(f"Devices to remove: {[d.get_label() for d in devices_to_remove]}")
            logger.info(
                f"Devices to update: "
                f"{[(d.get_label(), ld_id) for d, ld_id in devices_to_update]}"
            )

            # Remove excess devices
            for device in devices_to_remove:
                mld.get_devices().remove(device)
                logger.info(f"Removed excess device: {device.get_label()}")

            # Update memory sizes for kept devices to match FMLD allocation
            # Use the actual FMLD allocation list if provided, otherwise fall back to calculation
            for i, (device, ld_id) in enumerate(devices_to_update):
                if fmld_allocation_list and len(fmld_allocation_list) > ld_id * 2:
                    # Get the allocation multiplier from the FMLD allocation list
                    # The allocation list format is [range1_ld0, range2_ld0,
                    # range1_ld1, range2_ld1, ...]
                    range1_index = ld_id * 2
                    range1_multiplier = fmld_allocation_list[range1_index]
                    allocation_multiplier = range1_multiplier
                    logger.info(
                        f"Using FMLD allocation list: LD {ld_id} "
                        f"has allocation multiplier {allocation_multiplier}"
                    )
                else:
                    # Fallback calculation
                    if len(switch_ld_ids) > 0:
                        min_ld_id = min(switch_ld_ids)
                        allocation_multiplier = ld_id - min_ld_id + 1
                    else:
                        allocation_multiplier = i + 1
                    logger.info(
                        f"Using fallback calculation: LD {ld_id} "
                        f"has allocation multiplier {allocation_multiplier}"
                    )

                expected_memory_size = allocation_multiplier * 256 * 1024 * 1024  # 256MB base unit
                dev_label = device.get_label()

                if hasattr(device, "get_memory_size"):
                    old_memory_size = device.get_memory_size()
                    device.set_memory_size(expected_memory_size)
                    logger.info(
                        f"Updated device {dev_label} (LD {ld_id}) memory size: "
                        f"{old_memory_size} -> {expected_memory_size} bytes "
                        f"({allocation_multiplier * 256} MB)"
                    )
                else:
                    logger.warning(f"Device {dev_label} has no get_memory_size method")

            # Reset capacity to reflect the change
            mld.reset_capacity()
            logger.info(
                f"Removed {len(devices_to_remove)} excess devices, "
                f"now have {len(mld.get_devices())} devices"
            )

        # If MLD has fewer devices than switch, we need to create missing devices
        elif current_device_count < len(switch_ld_ids):
            missing_count = len(switch_ld_ids) - current_device_count
            logger.info(
                f"MLD has {missing_count} missing devices, but cannot create them during sync"
            )

            # Find which LD IDs are missing
            current_ld_ids = []
            for device in mld.get_devices():
                device_ld_id = None
                dev_label = device.get_label()
                dev_serial = device.get_serial_number()
                if dev_label:
                    import re

                    match = re.search(r"LD(\d+)", dev_label)
                    if match:
                        device_ld_id = int(match.group(1))
                elif dev_serial:
                    try:
                        device_ld_id = int(dev_serial[-1], 16)
                    except (ValueError, IndexError):
                        pass

                if device_ld_id is not None:
                    current_ld_ids.append(device_ld_id)

            missing_ld_ids = [ld_id for ld_id in switch_ld_ids if ld_id not in current_ld_ids]
            logger.info(f"Sequential LD IDs: {current_ld_ids}")
            logger.info(f"Missing LD IDs: {missing_ld_ids}")
            logger.info(
                f"Cannot create {len(missing_ld_ids)} missing devices during sync: {missing_ld_ids}"
            )
            logger.info(
                "These devices will need to be created through the normal allocation process"
            )

        # If MLD has the same number of devices as switch, verify they match
        else:
            logger.info(
                f"MLD has same number of devices as switch ({current_device_count}), "
                "verifying they match"
            )
            current_ld_ids = []
            for device in mld.get_devices():
                device_ld_id = None
                dev_label = device.get_label()
                dev_serial = device.get_serial_number()
                if dev_label:
                    import re

                    match = re.search(r"LD(\d+)", dev_label)
                    if match:
                        device_ld_id = int(match.group(1))
                elif dev_serial:
                    try:
                        device_ld_id = int(dev_serial[-1], 16)
                    except (ValueError, IndexError):
                        pass

                if device_ld_id is not None:
                    current_ld_ids.append(device_ld_id)

            if set(current_ld_ids) != set(switch_ld_ids):
                logger.warning(
                    f"LD ID mismatch: MLD has {current_ld_ids}, switch has {switch_ld_ids}"
                )
                # This indicates a more serious synchronization issue
                # For now, we'll just log the warning and continue

        # Reset capacity to ensure it matches current devices
        mld.reset_capacity()
        logger.info(
            f"MLD Manager: Port {port_index} synchronization complete - "
            f"{len(mld.get_devices())} devices"
        )
        logger.info(
            f"Port {port_index} capacity after sync: "
            f"used={mld.get_used_capacity()} bytes, "
            f"remaining={mld.get_remaining_capacity()} bytes"
        )
        return True

    def get_total_capacity(self, port_index: int) -> int:
        """Get the total capacity of the MLD device for a specific port."""
        mld = self.get_mld(port_index)
        if mld is None:
            # Return default capacity for dynamic configuration
            logger.info(f"No MLD instance found for port {port_index}, returning default capacity")
            return 4 * 1024 * 1024 * 1024  # 4GB default
        return mld.get_total_capacity()

    def get_used_capacity(self, port_index: int) -> int:
        """Get the currently used capacity for a specific port."""
        mld = self.ensure_mld_instance(port_index)
        if mld is None:
            logger.info(
                f"Could not ensure MLD instance for port {port_index}, returning 0 used capacity"
            )
            return 0
        return mld.get_used_capacity()

    def get_remaining_capacity(self, port_index: int) -> int:
        """Get the remaining available capacity for a specific port."""
        mld = self.ensure_mld_instance(port_index)
        if mld is None:
            logger.info(
                f"Could not ensure MLD instance for port {port_index}, "
                f"returning default remaining capacity"
            )
            return 4 * 1024 * 1024 * 1024  # 4GB default
        return mld.get_remaining_capacity()

    def reset_capacity(self, port_index: int):
        """Reset used capacity to match current devices for a specific port."""
        mld = self.ensure_mld_instance(port_index)
        if mld is None:
            logger.warning(
                f"Could not ensure MLD instance for port {port_index}, cannot reset capacity"
            )
            return
        mld.reset_capacity()

    async def start_socket_server(self, host: str = "0.0.0.0", port: int = 8600):
        """Start the socket server to receive commands from other processes."""
        self._sio_server = socketio.AsyncServer(cors_allowed_origins="*")
        self._web_app = web.Application()
        self._sio_server.attach(self._web_app)

        # Register event handlers
        self._sio_server.on("connect", self._on_connect)
        self._sio_server.on("disconnect", self._on_disconnect)
        self._sio_server.on("create_logical_devices", self._on_create_logical_devices)
        self._sio_server.on("deallocate_logical_devices", self._on_deallocate_logical_devices)
        self._sio_server.on("get_device_info", self._on_get_device_info)
        self._sio_server.on("get_capacity_info", self._on_get_capacity_info)
        self._sio_server.on("sync_with_switch_state", self._on_sync_with_switch_state)

        # Start the server
        runner = web.AppRunner(self._web_app)
        await runner.setup()
        self._socket_server = web.TCPSite(runner, host, port)
        await self._socket_server.start()

        logger.info(f"MLD Manager socket server started on {host}:{port}")

    async def stop_socket_server(self):
        """Stop the socket server."""
        if self._socket_server:
            await self._socket_server.stop()
            logger.info("MLD Manager socket server stopped")

    async def _on_connect(self, sid, _environ):
        """Handle client connection."""
        logger.info(f"MLD Manager: Client connected: {sid}")

    async def _on_disconnect(self, sid):
        """Handle client disconnection."""
        logger.info(f"MLD Manager: Client disconnected: {sid}")

    async def _on_create_logical_devices(self, sid, data):
        """Handle create logical devices command from other processes."""
        try:
            logger.info(f"MLD Manager: Received create_logical_devices command: {data}")

            port_index = data.get("port_index")
            ld_ids = data.get("ld_ids", [])
            memory_sizes = data.get("memory_sizes")
            memory_files = data.get("memory_files")
            serial_numbers = data.get("serial_numbers")

            if port_index is None:
                await self._sio_server.emit(
                    "create_logical_devices_response",
                    {"success": False, "error": "Missing port_index"},
                    room=sid,
                )
                return

            success = await self.create_logical_devices(
                port_index=port_index,
                ld_ids=ld_ids,
                memory_sizes=memory_sizes,
                memory_files=memory_files,
                serial_numbers=serial_numbers,
            )

            await self._sio_server.emit(
                "create_logical_devices_response",
                {
                    "success": success,
                    "port_index": port_index,
                    "ld_ids": ld_ids,
                    "message": f"Logical devices creation {'succeeded' if success else 'failed'}",
                },
                room=sid,
            )

        except Exception as e:
            logger.error(f"MLD Manager: Error handling create_logical_devices: {e}")
            await self._sio_server.emit(
                "create_logical_devices_response", {"success": False, "error": str(e)}, room=sid
            )

    async def _on_deallocate_logical_devices(self, sid, data):
        """Handle deallocate logical devices command from other processes."""
        try:
            logger.info(f"MLD Manager: Received deallocate_logical_devices command: {data}")

            port_index = data.get("port_index")
            ld_ids = data.get("ld_ids", [])

            if port_index is None:
                await self._sio_server.emit(
                    "deallocate_logical_devices_response",
                    {"success": False, "error": "Missing port_index"},
                    room=sid,
                )
                return

            success = await self.deallocate_logical_devices(port_index=port_index, ld_ids=ld_ids)

            await self._sio_server.emit(
                "deallocate_logical_devices_response",
                {
                    "success": success,
                    "port_index": port_index,
                    "ld_ids": ld_ids,
                    "message": f"Logical devices deallocation "
                    f"{'succeeded' if success else 'failed'}",
                },
                room=sid,
            )

        except Exception as e:
            logger.error(f"MLD Manager: Error handling deallocate_logical_devices: {e}")
            await self._sio_server.emit(
                "deallocate_logical_devices_response", {"success": False, "error": str(e)}, room=sid
            )

    async def _on_get_device_info(self, sid, data):
        """Handle get device info command from other processes."""
        try:
            logger.info(f"MLD Manager: Received get_device_info command: {data}")

            port_index = data.get("port_index")
            if port_index is None:
                await self._sio_server.emit(
                    "get_device_info_response",
                    {"success": False, "error": "Missing port_index"},
                    room=sid,
                )
                return

            mld = self.get_mld(port_index)
            if mld is None:
                await self._sio_server.emit(
                    "get_device_info_response",
                    {"success": True, "port_index": port_index, "devices": []},
                    room=sid,
                )
                return

            # Get device information
            devices = []
            for i, device in enumerate(mld.get_devices()):
                # Extract LD ID from device using the same method as deallocation
                ld_id = mld.extract_ld_id_from_device(device)
                if ld_id is None:
                    # Fallback to device index if extraction fails
                    ld_id = i

                devices.append(
                    {
                        "serial_number": device.get_serial_number(),
                        "memory_size": device.get_memory_size(),
                        "ld_id": ld_id,  # Add the actual LD ID
                    }
                )

            await self._sio_server.emit(
                "get_device_info_response",
                {"success": True, "port_index": port_index, "devices": devices},
                room=sid,
            )

        except Exception as e:
            logger.error(f"MLD Manager: Error handling get_device_info: {e}")
            await self._sio_server.emit(
                "get_device_info_response", {"success": False, "error": str(e)}, room=sid
            )

    async def _on_get_capacity_info(self, sid, data):
        """Handle get capacity info command from other processes."""
        try:
            logger.info(f"MLD Manager: Received get_capacity_info command: {data}")

            port_index = data.get("port_index")
            if port_index is None:
                await self._sio_server.emit(
                    "get_capacity_info_response",
                    {"success": False, "error": "Missing port_index"},
                    room=sid,
                )
                return

            total_capacity = self.get_total_capacity(port_index)
            used_capacity = self.get_used_capacity(port_index)
            remaining_capacity = self.get_remaining_capacity(port_index)

            await self._sio_server.emit(
                "get_capacity_info_response",
                {
                    "success": True,
                    "port_index": port_index,
                    "total_capacity": total_capacity,
                    "used_capacity": used_capacity,
                    "remaining_capacity": remaining_capacity,
                },
                room=sid,
            )

        except Exception as e:
            logger.error(f"MLD Manager: Error handling get_capacity_info: {e}")
            await self._sio_server.emit(
                "get_capacity_info_response", {"success": False, "error": str(e)}, room=sid
            )

    async def _on_sync_with_switch_state(self, sid, data):
        """Handle sync_with_switch_state command from other processes."""
        try:
            logger.info(f"MLD Manager: Received sync_with_switch_state command: {data}")

            port_index = data.get("port_index")
            switch_ld_ids = data.get("switch_ld_ids", [])
            fmld_allocation_list = data.get("fmld_allocation_list")  # New parameter

            if port_index is None:
                await self._sio_server.emit(
                    "sync_with_switch_state_response",
                    {"success": False, "error": "Missing port_index"},
                    room=sid,
                )
                return

            success = await self.sync_with_switch_state(
                port_index=port_index,
                switch_ld_ids=switch_ld_ids,
                fmld_allocation_list=fmld_allocation_list,  # Pass the new parameter
            )

            await self._sio_server.emit(
                "sync_with_switch_state_response",
                {
                    "success": success,
                    "port_index": port_index,
                    "switch_ld_ids": switch_ld_ids,
                    "message": f"Switch state synchronization "
                    f"{'succeeded' if success else 'failed'}",
                },
                room=sid,
            )

        except Exception as e:
            logger.error(f"MLD Manager: Error handling sync_with_switch_state: {e}")
            await self._sio_server.emit(
                "sync_with_switch_state_response", {"success": False, "error": str(e)}, room=sid
            )

    def ensure_mld_instance(self, port_index: int) -> MultiLogicalDevice:
        """Ensure an MLD instance exists for a specific port, create one if it doesn't exist."""
        mld = self.get_mld(port_index)
        if mld is None:
            logger.info(f"No MLD instance found for port {port_index}, creating one dynamically")

            # Create a default MLD configuration
            from opencis.cxl.device.config.logical_device import MultiLogicalDeviceConfig

            mld_config = MultiLogicalDeviceConfig(
                port_index=port_index,
                device_id=61445,  # Add required fields
                vendor_id=7621,
                subsystem_vendor_id=0,
                subsystem_id=0,
                memory_sizes=[],
                ld_list=[],
                memory_files=[],
                serial_numbers=[],
                total_capacity=4 * 1024 * 1024 * 1024,  # 4GB default
                ld_count=0,  # Start with no LDs
                num_lds_supported=16,  # Add this field
            )

            # Create and register the MLD instance
            mld = MultiLogicalDevice(mld_config)
            self.register_mld(port_index, mld)

            logger.info(f"Created and registered dynamic MLD instance for port {port_index}")

            # Try to sync with existing devices
            self.sync_mld_with_existing_devices(port_index, mld)

        return mld

    def sync_mld_with_existing_devices(self, port_index: int, mld: MultiLogicalDevice):
        """Sync MLD instance with existing devices by querying the device info."""
        try:
            # This is a placeholder for syncing with existing devices
            # In a real implementation, you would query the actual device state
            # and update the MLD instance accordingly
            logger.info(
                f"Attempting to sync MLD instance for port {port_index} with existing devices"
            )

            # For now, we'll just reset the capacity to ensure it's accurate
            mld.reset_capacity()

            logger.info(f"Synced MLD instance for port {port_index}")
        except Exception as e:
            logger.warning(f"Could not sync MLD instance for port {port_index}: {e}")


# Global instance
mld_manager = MLDManager.get_instance()
