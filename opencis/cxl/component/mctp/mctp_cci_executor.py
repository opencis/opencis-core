"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from asyncio import create_task, gather
from typing import Optional, cast, List
from opencis.util.component import RunnableComponent
from opencis.cxl.component.mctp.mctp_connection import MctpConnection
from opencis.cxl.component.cci_executor import (
    CciExecutor,
    CciRequest,
    CciResponse,
    CciCommand,
    CciBackgroundStatus,
)
from opencis.cxl.component.cxl_connection import CxlConnection
from opencis.cxl.component.switch_connection_manager import SwitchConnectionManager
from opencis.cxl.component.cxl_component import (
    PORT_TYPE,
    PortConfig,
)
from opencis.cxl.transport.cci_packets import (
    CciMessagePacket,
    CciPayloadPacket,
    GetLdInfoRequestPacket,
    GetLdAllocationsRequestPacket,
    SetLdAllocationsRequestPacket,
)
from opencis.cxl.cci.fabric_manager.mld_components.set_ld_allocations import (
    SetLdAllocationsRequestPayload,
)
from opencis.cxl.transport.packet_constants import CCI_MCTP_MESSAGE_CATEGORY

from opencis.cxl.cci.common import CCI_FM_API_COMMAND_OPCODE, CCI_RETURN_CODE, get_opcode_string
from opencis.util.logger import logger


class MctpCciExecutor(RunnableComponent):
    def __init__(
        self,
        mctp_connection: MctpConnection,
        switch_connection_manager: SwitchConnectionManager,
        port_configs: List[PortConfig],
        virtual_switch_manager=None,
        label: Optional[str] = None,
    ):
        super().__init__(label)
        self._message_tag_list = {}
        self._mctp_connection = mctp_connection
        self._cci_executor = CciExecutor(label="MCTP")
        self._switch_connection_manager = switch_connection_manager
        self._virtual_switch_manager = virtual_switch_manager
        self._downstream_port_connections = {}

        for port_index, port_config in enumerate(port_configs):
            if port_config.type == PORT_TYPE.DSP:
                self._downstream_port_connections[port_index] = (
                    self._switch_connection_manager.get_cxl_connection(port_index)
                )

    def register_cci_commands(self, commands: List[CciCommand]):
        for command in commands:
            self._cci_executor.register_command(command.get_opcode(), command)

    def _packet_to_request(self, packet: CciMessagePacket) -> CciRequest:
        return CciRequest(opcode=packet.cci_msg_header.command_opcode, payload=packet.get_payload())

    async def _send_response(self, response: CciResponse, message_tag: int):
        response_packet = CciMessagePacket.create(
            message_category=CCI_MCTP_MESSAGE_CATEGORY.RESPONSE,
            opcode=0,
            data=response.payload,
            message_tag=message_tag,
            vendor_specific_extended_status=response.vendor_specific_status,
            return_code=response.return_code,
            background_operation=int(response.bo_flag),
        )
        response_packet_tmc = CciPayloadPacket.create(response_packet)

        await self._mctp_connection.ep_to_controller.put(response_packet_tmc)

    async def _process_incoming_requests(self):
        logger.debug(self._create_message("Started processing incoming request"))
        while True:
            # Wait for incoming packets from the MCTP connection
            packet = await self._mctp_connection.controller_to_ep.get()
            if packet is None:
                logger.debug(self._create_message("Stopped processing incoming request"))
                break

            # Unpack
            cci_packet_tmc = cast(CciPayloadPacket, packet)
            port_index = cci_packet_tmc.cci_header.port_index

            cci_message = cci_packet_tmc.get_cci_message()
            command_opcode = cci_message.cci_msg_header.command_opcode
            opcodes_for_ld = [
                CCI_FM_API_COMMAND_OPCODE.GET_LD_INFO,
                CCI_FM_API_COMMAND_OPCODE.GET_LD_ALLOCATIONS,
                CCI_FM_API_COMMAND_OPCODE.SET_LD_ALLOCATIONS,
            ]
            if command_opcode in opcodes_for_ld:
                # Pass down to MLD
                # ld_index = cci_packet_tmc.cci_header.port_index
                message_tag = cci_message.cci_msg_header.message_tag
                self._message_tag_list[message_tag] = port_index

                # Check if the port_index exists in downstream port connections
                if port_index not in self._downstream_port_connections:
                    ports = list(self._downstream_port_connections.keys())
                    logger.error(
                        self._create_message(
                            f"Port index {port_index} is not a valid downstream port. "
                            f"Available downstream ports: {ports}"
                        )
                    )
                    # Send error response
                    error_response = CciResponse(
                        return_code=CCI_RETURN_CODE.INVALID_INPUT,
                        payload=b"Invalid port index",
                        vendor_specific_status=0,
                        bo_flag=False,
                    )
                    await self._send_response(error_response, message_tag)
                    continue

                packet = None
                match command_opcode:
                    case CCI_FM_API_COMMAND_OPCODE.GET_LD_INFO:
                        packet = GetLdInfoRequestPacket.create_from_cci_message(cci_message)
                    case CCI_FM_API_COMMAND_OPCODE.GET_LD_ALLOCATIONS:
                        packet = GetLdAllocationsRequestPacket.create_from_cci_message(cci_message)
                    case CCI_FM_API_COMMAND_OPCODE.SET_LD_ALLOCATIONS:
                        packet = SetLdAllocationsRequestPacket.create_from_cci_message(cci_message)

                        # Also update the virtual switch manager with the new LD allocations
                        # This ensures that binding/unbinding will work for dynamically created LDs
                        try:
                            # Extract LD IDs from the request payload
                            request_payload = SetLdAllocationsRequestPayload.parse(
                                cci_message.get_data()
                            )
                            logger.info(f"Parsed SET_LD_ALLOCATIONS request: {request_payload}")

                            # Update virtual switch manager with the new LD allocations
                            if self._virtual_switch_manager is not None:
                                if request_payload.number_of_lds == 0:
                                    # Deallocate all - clear all LD allocations
                                    # Ensures state sync with MLD Manager and Virtual Switch
                                    self._virtual_switch_manager.update_ld_allocations(
                                        port_index, []
                                    )
                                else:
                                    # Extract allocated LD IDs from the request
                                    allocated_ld_ids = []
                                    for i in range(request_payload.number_of_lds):
                                        ld_id = request_payload.start_ld_id + i
                                        # Check if this LD is allocated (range1 > 0)
                                        if i < len(request_payload.ld_allocation_list):
                                            range1 = request_payload.ld_allocation_list[i][
                                                0
                                            ]  # (range1, range2)
                                            if range1 > 0:
                                                allocated_ld_ids.append(ld_id)

                                    logger.info(
                                        f"Updating virtual switch manager with LD IDs: "
                                        f"{allocated_ld_ids}"
                                    )
                                    self._virtual_switch_manager.update_ld_allocations(
                                        port_index, allocated_ld_ids
                                    )
                            else:
                                logger.warning(
                                    "Virtual switch manager not available for LD allocation update"
                                )
                        except Exception as e:
                            logger.warning(f"Failed to update virtual switch manager: {e}")
                            import traceback

                            logger.warning(f"Traceback: {traceback.format_exc()}")

                    case _:
                        break

                await self._downstream_port_connections[port_index].cci_fifo.host_to_target.put(
                    packet
                )
            else:
                # Convert packet to CciRequest and send it to CciExecutor
                request = self._packet_to_request(cci_message)
                response = await self._cci_executor.execute_command(request)
                await self._send_response(response, cci_message.cci_msg_header.message_tag)

    async def _process_outcoming_responses(self, downstream_connection: CxlConnection):
        logger.debug(self._create_message("Started processing outcoming request"))
        while True:
            # Wait for incoming packets from the MCTP connection
            packet = await downstream_connection.cci_fifo.target_to_host.get()
            if packet is None:
                logger.debug(self._create_message("Stopped processing outcoming request"))
                break

            # set LD table
            opcode = packet.get_command_opcode()
            if opcode == CCI_FM_API_COMMAND_OPCODE.SET_LD_ALLOCATIONS:
                logger.info(self._create_message("switch received SetLdAllocationsResponsePacket"))
                port_index = self._message_tag_list.get(packet.cci_msg_header.message_tag, None)
                if port_index is None:
                    raise ValueError("Invalid message tag")

            self._message_tag_list.pop(packet.cci_msg_header.message_tag)

            cci_packet = packet.get_cci_message()
            cci_packet_tmc = CciPayloadPacket.create(cci_packet)

            await self._mctp_connection.ep_to_controller.put(cci_packet_tmc)

    async def _run(self):
        tasks = [
            create_task(self._process_incoming_requests()),
            create_task(self._cci_executor.run()),
        ]
        for downstream_connection in self._downstream_port_connections.values():
            tasks.append(create_task(self._process_outcoming_responses(downstream_connection)))
        await self._change_status_to_running()
        await gather(*tasks)

    async def _stop(self):
        # Stop the executor
        await self._mctp_connection.controller_to_ep.put(None)
        for downstream_connection in self._downstream_port_connections.values():
            await downstream_connection.cci_fifo.target_to_host.put(None)
        await self._cci_executor.stop()

    async def get_background_command_status(self) -> CciBackgroundStatus:
        status = await self._cci_executor.get_background_command_status()
        return status

    async def send_notification(self, request: CciRequest):
        message_packet = CciMessagePacket.create(
            data=request.payload,
            message_category=CCI_MCTP_MESSAGE_CATEGORY.REQUEST,
            opcode=request.opcode,
        )
        opcode_str = get_opcode_string(request.opcode)
        message_packet_tmc = CciPayloadPacket.create(message_packet)
        logger.debug(self._create_message(f"Sending {opcode_str}"))
        await self._mctp_connection.ep_to_controller.put(message_packet_tmc)
