"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

import asyncio
from functools import partial
from pprint import pformat
from typing import TypedDict, Any
import socketio
from aiohttp import web

from opencis.util.logger import logger
from opencis.cxl.component.short_msg_conn import ShortMsgBase, ShortMsgConn
from opencis.util.component import RunnableComponent
from opencis.cxl.component.mctp.mctp_cci_api_client import (
    MctpCciApiClient,
    GetPhysicalPortStateRequestPayload,
    GetVirtualCxlSwitchInfoRequestPayload,
    IdentifySwitchDeviceResponsePayload,
    BindVppbRequestPayload,
    UnbindVppbRequestPayload,
    GetLdAllocationsRequestPayload,
    SetLdAllocationsRequestPayload,
    FreezeVppbRequestPayload,
    UnfreezeVppbRequestPayload,
)
from opencis.cxl.cci.common import (
    CCI_VENDOR_SPECIFIC_OPCODE,
    get_opcode_string,
)
from opencis.cxl.transport.cci_packets import CciMessagePacket


class CommandResponse(TypedDict):
    error: str
    result: Any


class HostFMMsg(ShortMsgBase):
    UNBIND = 0x00
    BIND = 0x01
    CONFIRM = 0x02
    EXTRA = 0x03

    def __init__(self, arg):
        super().__init__(self, arg)
        self.data = 0x00

    @property
    def real_val(self):
        return self.data

    @classmethod
    def _missing_(cls, value):
        inst = cls.parse(value)
        inst.data = value
        return inst

    @classmethod
    def create(cls, vppb: int, root_port: int, confirmation: bool, bind: bool):
        data = (root_port << 8) | (vppb << 4) | (int(confirmation) << 1) | int(bind)
        inst = cls(data)
        inst.data = data
        return inst

    @classmethod
    def parse(cls, data):
        bind = data & 0b1
        confirmation = data & 0b10
        if confirmation:
            new_cls = cls(confirmation)
        else:
            new_cls = cls(bind)
        return new_cls

    @property
    def is_confirmation(self) -> bool:
        return bool(self.data & 0b10)

    @property
    def is_bind(self) -> bool:
        return bool(self.data & 0b1)

    @property
    def root_port(self) -> int:
        return self.data >> 8

    @property
    def vppb(self) -> bool:
        return (self.data >> 4) & 0xF

    @property
    def readable(self):
        data = ""
        if self.is_confirmation:
            data = "Host confirmation for "
        if self.is_bind:
            data += "Binding "
        else:
            data += "Unbinding "
        return data + f"Root Port: {self.root_port}, vPPB: {self.vppb}"


class HostFMConnManager:
    def __init__(self, api_client: MctpCciApiClient, host_fm_conn_server: ShortMsgConn):
        self._api_client = api_client
        self._host_fm_conn_server = host_fm_conn_server

    async def notify_host_bind(self, device_vppb: int, vcs_id: int):
        root_port = await self.get_usp_by_vcs_id(vcs_id)
        req = HostFMMsg.create(device_vppb, root_port, False, True)
        logger.info(
            f"Host bind notification root_port {root_port}, "
            f"device_vppb {device_vppb}, val {req.real_val}"
        )
        await self._host_fm_conn_server.send_irq_request(req, root_port)

    async def notify_host_unbind(self, device_vppb: int, vcs_id: int):
        root_port = await self.get_usp_by_vcs_id(vcs_id)
        req = HostFMMsg.create(device_vppb, root_port, False, False)
        logger.info(
            f"Host unbind notification root_port {root_port}, "
            f"device_vppb {device_vppb}, val {req.real_val}"
        )
        await self._host_fm_conn_server.send_irq_request(req, root_port)

    async def get_usp_by_vcs_id(self, vcs_id: int):
        vcs_info_tuple = await self._api_client.get_virtual_cxl_switch_info(
            GetVirtualCxlSwitchInfoRequestPayload(
                start_vppb=0, vppb_list_limit=255, vcs_id_list=[vcs_id]
            )
        )
        vcs_info_list = vcs_info_tuple[1]
        for vcs_info in vcs_info_list.vcs_info_list:
            if vcs_id == vcs_info.vcs_id:
                return vcs_info.usp_id


class FabricManagerSocketIoServer(RunnableComponent):
    def __init__(
        self,
        mctp_client: MctpCciApiClient,
        host_fm_conn_manager: HostFMConnManager,
        host: str = "0.0.0.0",
        port: int = 8200,
        mld_client=None,
    ):
        super().__init__()
        self._mctp_client = mctp_client
        self._host_fm_conn_manager = host_fm_conn_manager
        self._host = host
        self._port = port
        self._event_lock = asyncio.Lock()
        self._switch_identity = None
        self._stop_signal = False
        self._mld_client = mld_client

        # Create a new Aiohttp web app
        self._app = web.Application()

        # Create a Socket.IO server
        self._sio = socketio.AsyncServer(cors_allowed_origins="*")
        self._sio.attach(self._app)
        self._runner = web.AppRunner(self._app)
        self._fut = None

        self._register_handler("port:get")
        self._register_handler("vcs:get")
        self._register_handler("device:get")
        self._register_handler("vcs:bind")
        self._register_handler("vcs:unbind")
        self._register_handler("vcs:freeze")
        self._register_handler("vcs:unfreeze")
        self._register_handler("mld:get")
        self._register_handler("mld:getAllocation")
        self._register_handler("mld:setAllocation")
        self._register_handler("background:getStatus")
        self._mctp_client.register_notification_handler(self._handle_notifications)

    def _register_handler(self, event):
        self._sio.on(event, partial(self._handle_event, event))

    async def _handle_notifications(self, packet: CciMessagePacket):
        opcode = packet.cci_msg_header.command_opcode
        logger.debug(self._create_message(f"Handling Notification for 0x{opcode:x}"))
        opcode_str = get_opcode_string(opcode)
        if opcode == CCI_VENDOR_SPECIFIC_OPCODE.NOTIFY_PORT_UPDATE:
            await self._send_update_physical_ports_notification()
        elif opcode == CCI_VENDOR_SPECIFIC_OPCODE.NOTIFY_SWITCH_UPDATE:
            await self._send_update_virtual_cxl_switches_notification()
        elif opcode == CCI_VENDOR_SPECIFIC_OPCODE.NOTIFY_DEVICE_UPDATE:
            await self._send_update_devices_notification()
        else:
            logger.error(self._create_message(f"Unexpected Packet {opcode_str}"))

    async def _handle_event(self, event_type, _, data=None):
        async with self._event_lock:
            # Determine the event type and call the appropriate method
            logger.info(
                self._create_message(f"Received SocketIO Request: {event_type}, payload: {data}")
            )
            if event_type == "port:get":
                response = await self._get_physical_ports()
            elif event_type == "vcs:get":
                response = await self._get_virtual_switches()
            elif event_type == "device:get":
                response = await self._get_devices()
            elif event_type == "vcs:bind":
                response = await self._bind_vppb(data)
            elif event_type == "vcs:unbind":
                response = await self._unbind_vppb(data)
            elif event_type == "mld:get":
                response = await self._get_ld_info(data)
            elif event_type == "mld:getAllocation":
                response = await self._get_ld_allocation(data)
            elif event_type == "mld:setAllocation":
                response = await self._set_ld_allocation(data)
            elif event_type == "background:getStatus":
                response = await self._get_background_status()
            elif event_type == "vcs:freeze":
                response = await self._freeze_vppb(data)
            elif event_type == "vcs:unfreeze":
                response = await self._unfreeze_vppb(data)
            logger.info(self._create_message(f"Response: {pformat(response)}"))
            logger.debug(self._create_message("Completed SocketIO Request"))
            return response

    async def _get_switch_identity(self) -> IdentifySwitchDeviceResponsePayload:
        if self._switch_identity is None:
            (_, response) = await self._mctp_client.identify_switch_device()
            if not response:
                raise Exception("Failed to get switch identity")
            self._switch_identity = response
        return self._switch_identity

    async def _get_physical_ports(self) -> CommandResponse:
        switch_identity = await self._get_switch_identity()
        port_id_list = list(range(switch_identity.num_physical_ports))
        request = GetPhysicalPortStateRequestPayload(port_id_list)
        (return_code, response) = await self._mctp_client.get_physical_port_state(request)
        if response:
            return CommandResponse(error="", result=response.to_dict()["portInfoList"])
        return CommandResponse(error=return_code.name)

    async def _get_virtual_switches(self) -> CommandResponse:
        switch_identity = await self._get_switch_identity()
        vcs_id_list = list(range(switch_identity.num_vcss))
        request = GetVirtualCxlSwitchInfoRequestPayload(
            start_vppb=0, vppb_list_limit=255, vcs_id_list=vcs_id_list
        )
        (return_code, response) = await self._mctp_client.get_virtual_cxl_switch_info(request)
        if response:
            return CommandResponse(error="", result=response.to_dict()["vcsInfoList"])
        return CommandResponse(error=return_code.name)

    async def _get_devices(self) -> CommandResponse:
        (_, response) = await self._mctp_client.get_connected_devices()
        if response:
            return CommandResponse(error="", result=response.to_dict()["devices"])
        # When there are no devices, return empty array instead of error
        return CommandResponse(error="", result=[])

    async def _get_background_status(self) -> CommandResponse:
        (return_code, response) = await self._mctp_client.background_operation_status()
        if response:
            return CommandResponse(error="", result=response.to_dict())
        return CommandResponse(error=return_code.name)

    async def _bind_vppb(self, data) -> CommandResponse:
        ld_id = data.get("ldId")
        if ld_id is None:
            ld_id = 0  # SLD
        request = BindVppbRequestPayload(
            vcs_id=data["virtualCxlSwitchId"],
            vppb_id=data["vppbId"],
            physical_port_id=data["physicalPortId"],
            ld_id=ld_id,
        )
        (return_code, response) = await self._mctp_client.bind_vppb(request)
        if response is not None:
            await self._host_fm_conn_manager.notify_host_bind(
                data["vppbId"], data["virtualCxlSwitchId"]
            )
            return CommandResponse(error="", result=response.name)
        return CommandResponse(error="", result=return_code.name)

    async def _unbind_vppb(self, data) -> CommandResponse:
        request = UnbindVppbRequestPayload(
            vcs_id=data["virtualCxlSwitchId"],
            vppb_id=data["vppbId"],
        )
        # First send the unbinding command to the switch
        (return_code, response) = await self._mctp_client.unbind_vppb(request)

        # Then notify the host (even if this fails, the unbinding is already done)
        try:
            await self._host_fm_conn_manager.notify_host_unbind(
                data["vppbId"], data["virtualCxlSwitchId"]
            )
        except Exception as e:
            logger.warning(f"Failed to notify host about unbinding: {e}")

        if response is not None:
            return CommandResponse(error="", result=response.name)
        return CommandResponse(error="", result=return_code.name)

    async def _get_ld_info(self, data) -> CommandResponse:
        (return_code, response) = await self._mctp_client.get_ld_info(data["portIndex"])
        if response:
            # Get the actual memory size from the MLD Manager via socket server
            actual_memory_size = response.memory_size  # Start with FMLD response
            total_capacity = 4 * 1024 * 1024 * 1024  # 4GB default
            max_capacity = total_capacity
            device_capacity = response.memory_size  # Use FMLD response as default

            if self._mld_client is not None:
                try:
                    await self._mld_client.connect()
                    # Query the MLD Manager for the actual used capacity via socket server
                    port_index = data["portIndex"]

                    # Get capacity info from MLD Manager
                    capacity_info = await self._mld_client.get_capacity_info(port_index)
                    if capacity_info and capacity_info.get("success"):
                        actual_memory_size = capacity_info.get("used_capacity", 0)
                        total_capacity = capacity_info.get("total_capacity", total_capacity)
                        max_capacity = capacity_info.get("total_capacity", max_capacity)
                        device_capacity = actual_memory_size
                        logger.info(
                            f"Using MLD Manager capacity info: used={actual_memory_size} bytes, "
                            f"total={total_capacity} bytes"
                        )
                    else:
                        logger.warning(
                            f"Could not get capacity info from MLD Manager: {capacity_info}"
                        )
                        # Use FMLD response as fallback
                        actual_memory_size = response.memory_size
                        device_capacity = response.memory_size
                except Exception as e:
                    logger.warning(f"Could not get actual memory size from MLD Manager: {e}")
                    # Use FMLD response as fallback
                    actual_memory_size = response.memory_size
                    device_capacity = response.memory_size

            # Calculate remaining capacity
            remaining_capacity = total_capacity - device_capacity

            # Update the response with the actual memory size and capacity information
            response_dict = response.to_dict()
            if actual_memory_size > 0:
                response_dict["memorySize"] = actual_memory_size
                logger.info(
                    f"Final memory size: {actual_memory_size} bytes "
                    f"({actual_memory_size / (1024*1024):.2f} MB)"
                )

            # Add missing capacity fields
            response_dict["totalCapacity"] = total_capacity
            response_dict["maxCapacity"] = max_capacity
            response_dict["deviceCapacity"] = device_capacity
            response_dict["remainingCapacity"] = remaining_capacity

            logger.info(
                f"Added capacity information: totalCapacity={total_capacity}, "
                f"deviceCapacity={device_capacity}, remainingCapacity={remaining_capacity}"
            )

            return CommandResponse(error="", result=response_dict)
        return CommandResponse(error=return_code.name)

    async def _get_ld_allocation(self, data) -> CommandResponse:
        request = GetLdAllocationsRequestPayload(
            start_ld_id=data["startLdId"],
            ld_allocation_list_limit=data["ldAllocationListLimit"],
        )
        (return_code, response) = await self._mctp_client.get_ld_alloctaion(
            request, data["portIndex"]
        )
        if response:
            # Initialize capacity variables
            total_capacity = 4 * 1024 * 1024 * 1024  # 4GB default
            max_capacity = total_capacity
            device_capacity = 0

            # PRIORITY 1: Calculate capacity from FMLD allocation list (CORRECT)
            if response.ld_allocation_list:
                # Values are allocation multipliers
                # Granularity based on memory_granularity: 0h=256MB, 1h=512MB, 2h=1GB
                granularity_bytes = (256 * 1024 * 1024) * (2**response.memory_granularity)
                allocated_memory_bytes = sum(
                    multiplier * granularity_bytes
                    for multiplier in response.ld_allocation_list
                    if multiplier > 0
                )
                device_capacity = allocated_memory_bytes
                logger.info(
                    f"Using FMLD capacity calculation: {allocated_memory_bytes} bytes "
                    f"(granularity={response.memory_granularity})"
                )

            # PRIORITY 2: Use MLD Manager as fallback only if FMLD calculation failed
            elif self._mld_client is not None:
                try:
                    # Get capacity info from MLD Manager (fallback only)
                    capacity_info = await self._mld_client.get_capacity_info(data["portIndex"])
                    if capacity_info and capacity_info.get("success"):
                        total_capacity = capacity_info.get(
                            "total_capacity", total_capacity
                        )  # ← Use actual MLD capacity
                        max_capacity = capacity_info.get(
                            "total_capacity", max_capacity
                        )  # ← Use actual MLD capacity
                        device_capacity = capacity_info.get("used_capacity", 0)
                        logger.info(
                            f"Using MLD Manager capacity info as fallback: {device_capacity} bytes"
                        )
                except Exception as e:
                    logger.warning(f"Could not get capacity info from MLD Manager as fallback: {e}")
                    # Calculate capacity from the response data as fallback
                    if response.ld_allocation_list:
                        # Values are allocation multipliers
                        # Granularity based on memory_granularity: 0h=256MB, 1h=512MB, 2h=1GB
                        granularity_bytes = (256 * 1024 * 1024) * (2**response.memory_granularity)
                        allocated_memory_bytes = sum(
                            multiplier * granularity_bytes
                            for multiplier in response.ld_allocation_list
                            if multiplier > 0
                        )
                        device_capacity = allocated_memory_bytes
                        logger.info(
                            "Calculated device capacity from allocation multipliers: "
                            f"{allocated_memory_bytes} bytes "
                            f"(granularity={response.memory_granularity})"
                        )

            # ALWAYS get the correct total capacity from MLD Manager
            if self._mld_client is not None:
                try:
                    capacity_info = await self._mld_client.get_capacity_info(data["portIndex"])
                    if capacity_info and capacity_info.get("success"):
                        total_capacity = capacity_info.get(
                            "total_capacity", total_capacity
                        )  # ← Override with actual MLD capacity
                        max_capacity = capacity_info.get(
                            "total_capacity", max_capacity
                        )  # ← Override with actual MLD capacity
                        logger.info(f"Using MLD Manager total capacity: {total_capacity} bytes")
                except Exception as e:
                    logger.warning(f"Could not get total capacity from MLD Manager: {e}")

            # Calculate remaining capacity
            remaining_capacity = total_capacity - device_capacity

            # Update response with capacity information
            response_dict = response.to_dict()
            response_dict["totalCapacity"] = total_capacity
            response_dict["maxCapacity"] = max_capacity
            response_dict["deviceCapacity"] = device_capacity
            response_dict["remainingCapacity"] = remaining_capacity

            logger.info(
                f"Added capacity information to LD allocation response: "
                f"totalCapacity={total_capacity}, deviceCapacity={device_capacity}, "
                f"remainingCapacity={remaining_capacity}"
            )

            return CommandResponse(error="", result=response_dict)
        return CommandResponse(error=return_code.name)

    async def _set_ld_allocation(self, data) -> CommandResponse:
        # Convert ld_allocation_list from list of dicts to list of tuples
        # Handle both allocation format [{"range1": x, "range2": y}, ...] and
        # deallocation format [0, 1, 0, ...]

        # pylint: disable=too-many-return-statements
        ld_allocation_list = []
        for item in data["ldAllocationList"]:
            if isinstance(item, dict):
                # Allocation format: {"range1": x, "range2": y}
                ld_allocation_list.append((item["range1"], item["range2"]))
            elif isinstance(item, int):
                # Deallocation format: 0 = deallocate, 1 = allocate
                ld_allocation_list.append((item, 0))
            else:
                logger.error(f"Invalid item format in ldAllocationList: {item}")
                return CommandResponse(error="INVALID_ALLOCATION_FORMAT")

        # FIXED LOGIC: Treat range1 as memory size, not LD ID
        # Extract memory sizes from the allocation list
        memory_sizes = []
        for i, (range1, _) in enumerate(ld_allocation_list):
            if range1 > 0:
                # range1 is memory size in KB, convert to bytes
                memory_size_bytes = range1 * 1024
                memory_sizes.append(memory_size_bytes)
                logger.info(
                    f"Memory size request: position {i} -> {memory_size_bytes} bytes ({range1} KB)"
                )
            elif range1 == 0:
                # Skip deallocated positions
                logger.info(f"Deallocation request: position {i} -> skip")

        logger.info(f"Extracted memory sizes: {memory_sizes}")

        port_index = data["portIndex"]

        # Always send command to the switch via MCTP to keep allocation state synchronized
        request = SetLdAllocationsRequestPayload(
            number_of_lds=data["numberOfLds"],
            start_ld_id=data["startLdId"],
            ld_allocation_list=ld_allocation_list,
        )
        (return_code, response) = await self._mctp_client.set_ld_alloctaion(request, port_index)

        if not response:
            return CommandResponse(error=return_code.name)

        # Connect to MLD process if not already connected
        try:
            await self._mld_client.connect()
        except Exception as e:
            logger.warning(f"Could not connect to MLD process: {e}")
            # Continue anyway - the switch command succeeded

        # Sync MLD Manager state with switch state before any operations
        try:
            # Get the current switch allocation state
            get_allocation_request = GetLdAllocationsRequestPayload(
                start_ld_id=0, ld_allocation_list_limit=16
            )
            (return_code, current_allocation_response) = await self._mctp_client.get_ld_alloctaion(
                get_allocation_request, port_index
            )

            if current_allocation_response:
                # Extract LD IDs that are actually allocated in the switch
                # FMLD allocation list format: [range1_ld0, range2_ld0, range1_ld1, range2_ld1, ...]
                # where range1 is memory size (0=deallocated, 1=256MB, 2=512MB, etc.)
                # and range2 is always 0
                switch_ld_ids = []
                for i in range(
                    0, len(current_allocation_response.ld_allocation_list), 2
                ):  # Step by 2
                    ld_id = i // 2  # Convert index to LD ID
                    range1_value = current_allocation_response.ld_allocation_list[i]
                    if range1_value > 0:  # Non-zero range1 means allocated
                        switch_ld_ids.append(ld_id)

                logger.info(f"Switch has {len(switch_ld_ids)} LDs allocated: {switch_ld_ids}")

                # Sync MLD Manager with switch state
                sync_success = await self._mld_client.sync_with_switch_state(
                    port_index, switch_ld_ids, current_allocation_response.ld_allocation_list
                )
                if sync_success:
                    logger.info(
                        f"Successfully synced MLD Manager with switch state for port {port_index}"
                    )
                else:
                    logger.info(
                        f"Switch has {len(switch_ld_ids)} LDs allocated after deallocation: "
                        f"{switch_ld_ids}"
                    )
                    logger.warning(
                        f"Failed to sync MLD Manager with switch state for port {port_index}"
                    )
            else:
                logger.warning(
                    f"Could not get current switch allocation state for port {port_index}"
                )
        except Exception as e:
            logger.warning(f"Error syncing with switch state: {e}")

        # Handle allocation case (creating new LDs)
        if memory_sizes:
            # Check if this is actually a deallocation request (some range1 values are 0)
            has_deallocation = any(range1 == 0 for range1, _ in ld_allocation_list)

            if has_deallocation:
                # This is a partial deallocation request - don't create new LDs
                # Just let the switch handle the deallocation and sync the state
                logger.info(
                    f"Detected partial deallocation request for port {port_index}, "
                    f"skipping MLD creation"
                )

                # Sync with switch state after deallocation
                try:
                    # Get the current switch allocation state after deallocation
                    get_allocation_request = GetLdAllocationsRequestPayload(
                        start_ld_id=0, ld_allocation_list_limit=16
                    )
                    (return_code, current_allocation_response) = (
                        await self._mctp_client.get_ld_alloctaion(
                            get_allocation_request, port_index
                        )
                    )

                    if current_allocation_response:
                        # Extract LD IDs that are actually allocated in the switch
                        switch_ld_ids = []
                        for i, allocation in enumerate(
                            current_allocation_response.ld_allocation_list
                        ):
                            if allocation > 0:  # Non-zero means allocated
                                switch_ld_ids.append(i)

                        # Sync MLD Manager with switch state
                        sync_success = await self._mld_client.sync_with_switch_state(
                            port_index,
                            switch_ld_ids,
                            current_allocation_response.ld_allocation_list,
                        )
                        if sync_success:
                            logger.info(
                                "Successfully synced MLD Manager with switch state "
                                "after deallocation"
                            )
                        else:
                            logger.warning(
                                "Failed to sync MLD Manager with switch state after deallocation"
                            )
                    else:
                        logger.warning(
                            "Could not get current switch allocation state after deallocation"
                        )
                except Exception as e:
                    logger.warning(f"Error syncing with switch state after deallocation: {e}")

                # Return success for deallocation
                return CommandResponse(
                    error="",
                    result={
                        "created_ld_ids": [],
                        "deallocated_ld_ids": [],
                        "message": (
                            f"Successfully processed partial deallocation for port {port_index}"
                        ),
                    },
                )

            # This is a pure allocation request - create new LDs
            # But first, check if we need to sync with the switch state
            # to ensure we only create the missing LDs
            try:
                # Get the current switch allocation state
                get_allocation_request = GetLdAllocationsRequestPayload(
                    start_ld_id=0, ld_allocation_list_limit=16
                )
                (return_code, current_allocation_response) = (
                    await self._mctp_client.get_ld_alloctaion(get_allocation_request, port_index)
                )

                if current_allocation_response:
                    # Extract LD IDs that are actually allocated in the switch
                    switch_ld_ids = []
                    for i, allocation in enumerate(current_allocation_response.ld_allocation_list):
                        if allocation > 0:  # Non-zero means allocated
                            switch_ld_ids.append(i)

                    logger.info(f"Switch has {len(switch_ld_ids)} LDs allocated: {switch_ld_ids}")

                    # Use actual switch LD IDs directly
                    logger.info(f"Using actual switch LD IDs: {switch_ld_ids}")

                    # Sync MLD Manager with switch state first
                    sync_success = await self._mld_client.sync_with_switch_state(
                        port_index,
                        switch_ld_ids,
                        current_allocation_response.ld_allocation_list,
                    )
                    if sync_success:
                        logger.info(
                            f"Successfully synced MLD Manager with switch state for port "
                            f"{port_index}"
                        )
                    else:
                        logger.info(
                            f"Switch has {len(switch_ld_ids)} LDs allocated after "
                            f"deallocation: {switch_ld_ids}"
                        )
                        logger.warning(
                            f"Failed to sync MLD Manager with switch state for port {port_index}"
                        )
                else:
                    logger.warning(
                        f"Could not get current switch allocation state for port {port_index}"
                    )
            except Exception as e:
                logger.warning(f"Error syncing with switch state: {e}")

            # Generate LD IDs for the new allocation request
            # IMPORTANT: When set_ld_allocation is called with the entire allocation list,
            # it should replace all existing LDs, not add to them
            logger.info(
                f"Replacing all existing LDs with new allocation list for port {port_index}"
            )

            # First, clear all existing LDs to free up capacity
            # using the same approach as Force Clear All LDs
            try:
                logger.info(
                    f"Force clearing all existing LDs for port {port_index} "
                    f"before creating new ones"
                )

                # Step 1: Send deallocate command to switch/FMLD (same as Force Clear)
                get_allocation_request = GetLdAllocationsRequestPayload(
                    start_ld_id=0, ld_allocation_list_limit=16
                )
                (return_code, current_allocation_response) = (
                    await self._mctp_client.get_ld_alloctaion(get_allocation_request, port_index)
                )

                if current_allocation_response and current_allocation_response.number_of_lds > 0:
                    # Create deallocate all request with proper numberOfLds >= 1
                    current_number_of_lds = current_allocation_response.number_of_lds
                    logger.info(
                        f"Current allocation state shows {current_number_of_lds} LDs "
                        f"to deallocate"
                    )

                    # Create allocation list with all LDs set to 0 (deallocated)
                    deallocate_allocation_list = [(0, 0) for _ in range(current_number_of_lds)]

                    deallocate_all_request = SetLdAllocationsRequestPayload(
                        number_of_lds=current_number_of_lds,
                        start_ld_id=0,
                        ld_allocation_list=deallocate_allocation_list,
                    )
                else:
                    # No LDs currently allocated, but clear potential lingering LDs
                    logger.info("No LDs currently allocated, but clearing potential lingering LDs")
                    deallocate_allocation_list = [(0, 0) for _ in range(8)]  # Clear up to 8 LDs

                    deallocate_all_request = SetLdAllocationsRequestPayload(
                        number_of_lds=8,
                        start_ld_id=0,
                        ld_allocation_list=deallocate_allocation_list,
                    )

                # Send deallocate command to switch
                (return_code, response) = await self._mctp_client.set_ld_alloctaion(
                    deallocate_all_request, port_index
                )

                if response:
                    logger.info(
                        f"Successfully sent deallocate all command to switch for port "
                        f"{port_index}"
                    )
                else:
                    logger.warning(
                        f"Failed to send deallocate all command to switch for port {port_index}"
                    )
                    # Continue anyway - the MLD deallocation might still work

                # Step 2: Deallocate MLD devices with correct LD IDs (same as Force Clear)
                device_info = await self._mld_client.get_device_info(port_index)
                if device_info and isinstance(device_info, list):
                    devices = device_info
                    if devices:
                        # Extract actual LD IDs from device info
                        existing_ld_ids = []
                        for device in devices:
                            ld_id = device.get("ld_id")
                            if ld_id is not None:
                                existing_ld_ids.append(ld_id)
                            else:
                                logger.warning(f"Device missing ld_id: {device}")

                        logger.info(
                            f"Found {len(existing_ld_ids)} allocated LDs to clear: "
                            f"{existing_ld_ids}"
                        )

                        # Deallocate MLD devices with correct LD IDs
                        if existing_ld_ids:
                            clear_success = await self._mld_client.deallocate_logical_devices(
                                port_index=port_index,
                                ld_ids=existing_ld_ids,  # Use actual LD IDs, not assumed ones
                            )
                            if clear_success:
                                logger.info(
                                    f"Successfully cleared {len(existing_ld_ids)} existing LDs"
                                )
                            else:
                                logger.warning(
                                    "Failed to clear existing LDs, but continuing with "
                                    "allocation"
                                )
                        else:
                            logger.info("No existing LDs found to clear")
                    else:
                        logger.info("No devices found to clear")
                else:
                    logger.warning(
                        "Could not get device info for clearing, but continuing with allocation"
                    )

            except Exception as exc:
                logger.warning(
                    f"Error clearing existing LDs: {exc}, but continuing with allocation"
                )

            # Now create all the new LDs from the allocation list
            new_ld_ids = list(range(len(memory_sizes)))
            logger.info(
                f"Creating {len(new_ld_ids)} new LDs to replace existing ones: {new_ld_ids}"
            )

            success = await self._mld_client.create_logical_devices(
                port_index=port_index, ld_ids=new_ld_ids, memory_sizes=memory_sizes
            )

            if not success:
                logger.error(f"Failed to create logical devices dynamically for port {port_index}")
                return CommandResponse(
                    error="DYNAMIC_LD_CREATION_FAILED",
                    result={
                        "message": f"Switch command succeeded but dynamic LD creation "
                        f"failed for port {port_index}"
                    },
                )

            # Note: success is already checked in the if/else blocks above
            logger.info(
                f"Successfully created {len(new_ld_ids)} logical devices "
                f"dynamically: {new_ld_ids}"
            )

            # After successfully creating MLD devices, update FMLD with the new allocations
            try:
                logger.info(f"Updating FMLD with new LD allocations for port {port_index}")

                # Create the allocation list for the new LDs
                new_allocation_list = []
                for memory_size in memory_sizes:
                    # Convert bytes to KB (the format FMLD expects)
                    memory_kb = memory_size // 1024
                    new_allocation_list.append((memory_kb, 0))  # (range1, range2)

                # Send the new allocation to FMLD
                set_allocation_request = SetLdAllocationsRequestPayload(
                    number_of_lds=len(memory_sizes),
                    start_ld_id=0,
                    ld_allocation_list=new_allocation_list,
                )

                (return_code, response) = await self._mctp_client.set_ld_alloctaion(
                    set_allocation_request, port_index
                )

                if response:
                    logger.info(
                        f"Successfully updated FMLD with new LD allocations for port "
                        f"{port_index}"
                    )
                else:
                    logger.warning(
                        f"Failed to update FMLD with new LD allocations for port {port_index}"
                    )

            except Exception as exc:
                logger.warning(f"Error updating FMLD with new allocations: {exc}")

            # Prepare response for allocation
            return CommandResponse(
                error="",
                result={
                    "created_ld_ids": new_ld_ids,
                    "deallocated_ld_ids": [],
                    "message": f"Successfully created {len(new_ld_ids)} new LDs",
                },
            )

        # Handle deallocation case (no memory sizes provided)
        else:  # pylint: disable=no-else-return
            # Deallocate all existing LDs for this port
            try:
                logger.info(f"Deallocating all existing LDs for port {port_index}")
                # Get device info to see which LDs are currently allocated
                device_info = await self._mld_client.get_device_info(port_index)
                if device_info and isinstance(device_info, list):
                    devices = device_info
                    # Extract LD IDs from device serial numbers (they contain LD IDs)
                    existing_ld_ids = []
                    for device in devices:
                        serial_number = device.get("serial_number", "")
                        # Serial numbers are in format '000000000000000X' where X is the LD ID in hex # pylint: disable=line-too-long
                        try:
                            ld_id_hex = serial_number[-1]
                            ld_id = int(ld_id_hex, 16)  # Convert from hex to int
                            existing_ld_ids.append(ld_id)
                        except (ValueError, IndexError):
                            logger.warning(
                                f"Could not parse LD ID from serial number: {serial_number}"
                            )

                    logger.info(f"Found {len(existing_ld_ids)} allocated LDs: {existing_ld_ids}")
                else:
                    # Fallback: use empty list if no device info available
                    existing_ld_ids = []
                    logger.warning("Could not get device info, using empty LD IDs list")
            except Exception as e:
                logger.warning(f"Error getting device info for deallocation: {e}")
                # Fallback: use empty list if error occurs
                existing_ld_ids = []
                logger.info("Using empty LD IDs list due to error")

            # Deallocate all found LDs from MLD Manager
            if existing_ld_ids:
                success = await self._mld_client.deallocate_logical_devices(
                    port_index=port_index, ld_ids=existing_ld_ids
                )

                if success:
                    logger.info(
                        f"Successfully deallocated all LDs for port {port_index} from "
                        f"both switch and MLD"
                    )

                    # Sync with switch state after deallocation to ensure FMLD state is cleared
                    try:
                        # Get the current switch allocation state after deallocation
                        get_allocation_request = GetLdAllocationsRequestPayload(
                            start_ld_id=0, ld_allocation_list_limit=16
                        )
                        (return_code, current_allocation_response) = (
                            await self._mctp_client.get_ld_alloctaion(
                                get_allocation_request, port_index
                            )
                        )

                        if current_allocation_response:
                            # Extract LD IDs that are actually allocated in the switch
                            switch_ld_ids = []
                            for i, allocation in enumerate(
                                current_allocation_response.ld_allocation_list
                            ):
                                if allocation > 0:  # Non-zero means allocated
                                    switch_ld_ids.append(i)

                            logger.info(
                                f"Switch has {len(switch_ld_ids)} LDs allocated after "
                                f"deallocation: {switch_ld_ids}"
                            )

                            # Sync MLD Manager with switch state
                            sync_success = await self._mld_client.sync_with_switch_state(
                                port_index,
                                switch_ld_ids,
                                current_allocation_response.ld_allocation_list,
                            )
                            if sync_success:
                                logger.info(
                                    "Successfully synced MLD Manager with switch state after "
                                    "deallocation"
                                )
                            else:
                                logger.warning(
                                    "Failed to sync MLD Manager with switch state after "
                                    "deallocation"
                                )
                        else:
                            logger.warning(
                                "Could not get current switch allocation state after deallocation"
                            )
                    except Exception as e:
                        logger.warning(f"Error syncing with switch state after deallocation: {e}")

                    return CommandResponse(
                        error="",
                        result={
                            "created_ld_ids": [],
                            "deallocated_ld_ids": existing_ld_ids,
                            "message": f"Successfully deallocated all LDs for port {port_index}",
                        },
                    )

                logger.warning(
                    f"Switch deallocation succeeded but MLD deallocation failed for "
                    f"port {port_index}"
                )
                return CommandResponse(
                    error="",
                    result={
                        "created_ld_ids": [],
                        "deallocated_ld_ids": [],
                        "message": f"Switch deallocation succeeded but MLD deallocation "
                        f"failed for port {port_index}",
                    },
                )
            else:
                logger.info(f"No LDs found to deallocate from MLD Manager for port {port_index}")
                return CommandResponse(
                    error="",
                    result={
                        "created_ld_ids": [],
                        "deallocated_ld_ids": [],
                        "message": f"No LDs found to deallocate for port {port_index}",
                    },
                )

    async def _freeze_vppb(self, data) -> CommandResponse:
        request = FreezeVppbRequestPayload(
            vcs_id=data["virtualCxlSwitchId"],
            vppb_id=data["vppbId"],
        )
        (return_code, response) = await self._mctp_client.freeze_vppb(request)
        if response is not None:
            return CommandResponse(error="", result=response.name)
        return CommandResponse(error="", result=return_code.name)

    async def _unfreeze_vppb(self, data) -> CommandResponse:
        request = UnfreezeVppbRequestPayload(
            vcs_id=data["virtualCxlSwitchId"],
            vppb_id=data["vppbId"],
        )
        (return_code, response) = await self._mctp_client.unfreeze_vppb(request)
        if response is not None:
            return CommandResponse(error="", result=response.name)
        return CommandResponse(error="", result=return_code.name)

    async def _send_update_physical_ports_notification(self):
        # Emitting event without arguments
        await self._sio.emit("port:updated")

    async def _send_update_virtual_cxl_switches_notification(self):
        # Emitting event without arguments
        await self._sio.emit("vcs:updated")

    async def _send_update_devices_notification(self):
        # Emitting event without arguments
        await self._sio.emit("device:updated")

    async def _run(self):
        await self._runner.setup()
        site = web.TCPSite(self._runner, self._host, self._port)
        await site.start()
        logger.debug(
            self._create_message(f"Creating SocketIO Server at http://{self._host}:{self._port}")
        )
        await self._change_status_to_running()

        # Call Get LD Info for all MLD ports in the background after a delay
        # to allow MCTP and other components to fully connect first
        asyncio.create_task(self._delayed_startup_get_ld_info_calls())

        # wait until stopped
        self._fut = asyncio.Future()
        try:
            await self._fut
        except asyncio.CancelledError:
            # Handle cancellation gracefully
            logger.debug(self._create_message("SocketIO server cancelled"))
        except Exception as e:
            logger.debug(self._create_message(f"SocketIO server error: {e}"))

    async def _stop(self):
        logger.debug(self._create_message("Starting SocketIO server shutdown"))

        # Safely handle the future during shutdown
        if hasattr(self, "_fut") and self._fut is not None:
            logger.debug(
                self._create_message(
                    f"Future state: done={self._fut.done()}, cancelled={self._fut.cancelled()}"
                )
            )
            try:
                if not self._fut.done():
                    # Try to cancel the future instead of setting result
                    logger.debug(self._create_message("Cancelling future"))
                    self._fut.cancel()
                else:
                    logger.debug(self._create_message("Future already done"))
            except Exception as e:
                # Catch any unexpected errors during shutdown
                logger.debug(self._create_message(f"Error cancelling future during shutdown: {e}"))
        else:
            logger.debug(self._create_message("No future to cancel"))

        # Always cleanup the runner
        try:
            logger.debug(self._create_message("Cleaning up runner"))
            await self._runner.cleanup()
            logger.debug(self._create_message("Runner cleanup completed"))
        except Exception as e:
            logger.debug(self._create_message(f"Error during runner cleanup: {e}"))

        logger.debug(self._create_message("SocketIO server shutdown completed"))

    async def _delayed_startup_get_ld_info_calls(self):
        """Wrapper to call _startup_get_ld_info_calls after a delay."""
        try:
            # Wait for MCTP and other components to connect
            await asyncio.sleep(1.0)
            await self._startup_get_ld_info_calls()
        except asyncio.CancelledError:
            pass  # Ignore if cancelled during shutdown
        except Exception as e:
            logger.debug(self._create_message(f"Error in delayed startup: {e}"))

    async def _startup_get_ld_info_calls(self):
        """Call Get LD Info for all MLD ports at startup to inform UI about supported LD counts."""
        try:
            # Get all MLD port indices from the MCTP client's device configs
            # We need to find all ports that have MLD devices
            mld_port_indices = []

            # Try to get port indices from the MCTP client's device configs
            if hasattr(self._mctp_client, "_device_configs"):
                for (
                    device_config
                ) in self._mctp_client._device_configs:  # pylint: disable=protected-access
                    if hasattr(device_config, "port_index"):
                        mld_port_indices.append(device_config.port_index)
                        logger.info(
                            self._create_message(f"Found MLD port: {device_config.port_index}")
                        )

            # If no MLD ports configured, skip the Get LD Info calls
            if not mld_port_indices:
                logger.debug(self._create_message("No MLD ports configured, skipping Get LD Info"))
                return

            logger.info(self._create_message("Starting Get LD Info calls for all MLD ports..."))

            # Call Get LD Info for each MLD port
            for port_index in mld_port_indices:
                try:
                    logger.info(
                        self._create_message(f"Calling Get LD Info for port {port_index}...")
                    )

                    # Call the internal _get_ld_info method with a timeout
                    # to prevent hanging if the port doesn't respond
                    try:
                        response = await asyncio.wait_for(
                            self._get_ld_info({"portIndex": port_index}),
                            timeout=0.5,  # 0.5 second timeout per port
                        )
                    except asyncio.TimeoutError:
                        logger.debug(
                            self._create_message(f"Port {port_index}: Get LD Info timed out")
                        )
                        continue

                    # Check if response is a CommandResponse object
                    if hasattr(response, "error") and hasattr(response, "result"):
                        if response.error == "":
                            # Success - log the response
                            result = response.result
                            if result:
                                ld_count = result.get("ldCount", 0)
                                memory_size = result.get("memorySize", 0)
                                logger.info(
                                    self._create_message(
                                        f"Port {port_index}: LD Count = {ld_count}, "
                                        f"Memory Size = {memory_size} bytes"
                                    )
                                )
                            else:
                                logger.warning(
                                    self._create_message(
                                        f"Port {port_index}: No result in response"
                                    )
                                )
                        else:
                            logger.warning(
                                self._create_message(
                                    f"Port {port_index}: Get LD Info failed - {response.error}"
                                )
                            )
                    else:
                        # Response is not a CommandResponse object (might be a dict or other type)
                        logger.warning(
                            self._create_message(
                                f"Port {port_index}: Unexpected response type: {type(response)}"
                            )
                        )

                except Exception as e:
                    logger.warning(
                        self._create_message(f"Port {port_index}: Get LD Info error - {e}")
                    )
                    # Continue with other ports even if one fails
                    continue

            logger.info(self._create_message("Completed startup Get LD Info calls"))

        except Exception as e:
            logger.error(self._create_message(f"Error during startup Get LD Info calls: {e}"))
            # Don't fail the entire startup process if this fails
