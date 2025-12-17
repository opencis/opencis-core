"""
MLD Client for communicating with MLD process to create logical devices dynamically.
"""

import asyncio
from typing import List, Optional
import socketio
from opencis.util.logger import logger


class MLDClient:
    """Client for communicating with MLD process."""

    def __init__(self, host: str = "127.0.0.1", port: int = 8600):
        self._host = host
        self._port = port
        self._sio_client = socketio.AsyncClient()
        self._connected = False

    def is_connected(self) -> bool:
        """Check if the client is connected to the MLD socket server."""
        return self._connected

    async def connect(self):
        """Connect to the MLD socket server."""
        try:
            # Check if already connected
            if self._connected:
                logger.info(f"Already connected to MLD socket server at {self._host}:{self._port}")
                return

            await self._sio_client.connect(f"http://{self._host}:{self._port}")
            self._connected = True
            logger.info(f"Connected to MLD socket server at {self._host}:{self._port}")
        except Exception as e:
            logger.error(f"Failed to connect to MLD socket server: {e}")
            raise

    async def disconnect(self):
        """Disconnect from the MLD socket server."""
        if self._connected:
            await self._sio_client.disconnect()
            self._connected = False
            logger.info("Disconnected from MLD socket server")

    async def create_logical_devices(
        self,
        port_index: int,
        ld_ids: List[int],
        memory_sizes: List[int] = None,
        memory_files: List[str] = None,
        serial_numbers: List[str] = None,
    ) -> bool:
        """Send command to MLD process to create logical devices.

        Args:
            port_index: The port index to create LDs for
            ld_ids: List of LD IDs to create
            memory_sizes: Memory sizes for each LD
            memory_files: Memory files for each LD
            serial_numbers: Serial numbers for each LD

        Returns:
            True if successful, False otherwise
        """
        if not self._connected:
            logger.error("Not connected to MLD socket server")
            return False

        try:
            # Prepare the command data
            command_data = {
                "port_index": port_index,
                "ld_ids": ld_ids,
                "memory_sizes": memory_sizes,
                "memory_files": memory_files,
                "serial_numbers": serial_numbers,
            }

            logger.info(f"Sending create_logical_devices command to MLD process: {command_data}")

            # Create a future to wait for the response
            response_future = asyncio.Future()

            # Set up a one-time event handler for the response
            @self._sio_client.on("create_logical_devices_response")
            def handle_response(data):
                if not response_future.done():
                    response_future.set_result(data)

            # Send the command
            await self._sio_client.emit("create_logical_devices", command_data)

            # Wait for response with timeout
            try:
                response = await asyncio.wait_for(response_future, timeout=10.0)
                logger.info(f"Received response from MLD process: {response}")

                if response.get("success"):
                    logger.info(
                        f"Successfully created logical devices: {response.get('message', '')}"
                    )
                    return True
                logger.error(
                    f"Failed to create logical devices: {response.get('error', 'Unknown error')}"
                )
                return False

            except asyncio.TimeoutError:
                logger.error("Timeout waiting for response from MLD process")
                return False

        except Exception as e:
            logger.error(f"Error communicating with MLD process: {e}")
            return False

    async def deallocate_logical_devices(self, port_index: int, ld_ids: List[int]) -> bool:
        """Send command to MLD process to deallocate logical devices.

        Args:
            port_index: The port index to deallocate LDs from
            ld_ids: List of LD IDs to deallocate

        Returns:
            True if successful, False otherwise
        """
        if not self._connected:
            logger.error("Not connected to MLD socket server")
            return False

        try:
            # Prepare the command data
            command_data = {"port_index": port_index, "ld_ids": ld_ids}

            logger.info(
                f"Sending deallocate_logical_devices command to MLD process: {command_data}"
            )

            # Create a future to wait for the response
            response_future = asyncio.Future()

            # Set up a one-time event handler for the response
            @self._sio_client.on("deallocate_logical_devices_response")
            def handle_response(data):
                if not response_future.done():
                    response_future.set_result(data)

            # Send the command
            await self._sio_client.emit("deallocate_logical_devices", command_data)

            # Wait for response with timeout
            try:
                response = await asyncio.wait_for(response_future, timeout=10.0)
                logger.info(f"Received deallocation response from MLD process: {response}")

                if response.get("success"):
                    logger.info(
                        f"Successfully deallocated logical devices: {response.get('message', '')}"
                    )
                    return True
                logger.error(
                    "Failed to deallocate logical devices: "
                    f"{response.get('error', 'Unknown error')}"
                )
                return False

            except asyncio.TimeoutError:
                logger.error("Timeout waiting for deallocation response from MLD process")
                return False

        except Exception as e:
            logger.error(f"Error communicating with MLD process for deallocation: {e}")
            return False

    async def get_device_info(self, port_index: int) -> Optional[List[dict]]:
        """Get device information from the MLD process."""
        if not self._connected:
            logger.error("Not connected to MLD socket server")
            return None

        logger.info(f"MLD Client: Getting device info for port {port_index}")

        try:
            # Prepare the command data
            command_data = {"port_index": port_index}

            logger.info(f"Sending get_device_info command to MLD process: {command_data}")

            # Create a future to wait for the response
            response_future = asyncio.Future()

            # Set up a one-time event handler for the response
            @self._sio_client.on("get_device_info_response")
            def handle_response(data):
                if not response_future.done():
                    response_future.set_result(data)

            # Send the command
            await self._sio_client.emit("get_device_info", command_data)

            # Wait for response with timeout
            try:
                response = await asyncio.wait_for(response_future, timeout=10.0)
                logger.info(f"Received device info response from MLD process: {response}")

                if response.get("success"):
                    devices = response.get("devices", [])
                    logger.info(
                        f"MLD Client: Retrieved {len(devices)} devices for port {port_index}"
                    )
                    return devices
                logger.error(f"Failed to get device info: {response.get('error', 'Unknown error')}")
                return None

            except asyncio.TimeoutError:
                logger.error("Timeout waiting for device info response from MLD process")
                return None

        except Exception as e:
            logger.error(f"Error communicating with MLD process for device info: {e}")
            return None

    async def get_capacity_info(self, port_index: int) -> Optional[dict]:
        """Get capacity information for a specific port.

        Args:
            port_index: The port index to get capacity info for

        Returns:
            Dictionary with capacity information or None if failed
        """
        if not self._connected:
            logger.error("Not connected to MLD socket server")
            return None

        try:
            # Prepare the command data
            command_data = {"port_index": port_index}

            logger.info(f"Sending get_capacity_info command to MLD process: {command_data}")

            # Create a future to wait for the response
            response_future = asyncio.Future()

            # Set up a one-time event handler for the response
            @self._sio_client.on("get_capacity_info_response")
            def handle_response(data):
                if not response_future.done():
                    response_future.set_result(data)

            # Send the command
            await self._sio_client.emit("get_capacity_info", command_data)

            # Wait for response with timeout
            try:
                response = await asyncio.wait_for(response_future, timeout=10.0)
                logger.info(f"Received capacity info response from MLD process: {response}")

                if response.get("success"):
                    return response
                logger.error(
                    f"Failed to get capacity info: {response.get('error', 'Unknown error')}"
                )
                return None
            except asyncio.TimeoutError:
                logger.error("Timeout waiting for capacity info response")
                return None

        except Exception as e:
            logger.error(f"Error getting capacity info: {e}")
            return None

    async def sync_with_switch_state(
        self, port_index: int, switch_ld_ids: List[int], fmld_allocation_list: List[int] = None
    ) -> bool:
        """Synchronize MLD Manager state with switch allocation state.

        Args:
            port_index: The port index to sync
            switch_ld_ids: List of LD IDs that are actually allocated in the switch
            fmld_allocation_list: FMLD allocation list (e.g., [2, 0, 1, 0] for LD0=512MB, LD1=256MB)

        Returns:
            True if successful, False otherwise
        """
        if not self._connected:
            logger.error("Not connected to MLD socket server")
            return False

        try:
            # Prepare the command data
            command_data = {
                "port_index": port_index,
                "switch_ld_ids": switch_ld_ids,
                "fmld_allocation_list": fmld_allocation_list,
            }

            logger.info(f"Sending sync_with_switch_state command to MLD process: {command_data}")

            # Create a future to wait for the response
            response_future = asyncio.Future()

            # Set up a one-time event handler for the response
            @self._sio_client.on("sync_with_switch_state_response")
            def handle_response(data):
                if not response_future.done():
                    response_future.set_result(data)

            # Send the command
            await self._sio_client.emit("sync_with_switch_state", command_data)

            # Wait for response with timeout
            try:
                response = await asyncio.wait_for(response_future, timeout=10.0)
                logger.info(f"Received sync response from MLD process: {response}")

                if response.get("success"):
                    logger.info(
                        f"Successfully synced with switch state: {response.get('message', '')}"
                    )
                    return True
                logger.error(
                    "Failed to sync with switch state: " f"{response.get('error', 'Unknown error')}"
                )
                return False
            except asyncio.TimeoutError:
                logger.error("Timeout waiting for sync response")
                return False

        except Exception as e:
            logger.error(f"Error syncing with switch state: {e}")
            return False

    def get_used_capacity(self, port_index: int) -> int:
        """Get the used capacity for a specific port from the MLD Manager.

        This is a synchronous method that accesses the global MLD Manager instance.

        Args:
            port_index: The port index to get capacity for

        Returns:
            The used capacity in bytes
        """
        try:
            from opencis.cxl.component.mld_manager import mld_manager

            return mld_manager.get_used_capacity(port_index)
        except Exception as e:
            logger.error(f"Error getting used capacity for port {port_index}: {e}")
            return 0


# Global client instance
mld_client = MLDClient()
