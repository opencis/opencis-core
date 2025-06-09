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
from new_packet.transaction import (
    CciMessagePacket,
    CciPayloadPacket,
    GetLdInfoRequestPacket,
    GetLdAllocationsRequestPacket,
    SetLdAllocationsRequestPacket,
)
from new_packet.packet_constants import CCI_MCTP_MESSAGE_CATEGORY

from opencis.cxl.cci.common import CCI_FM_API_COMMAND_OPCODE, get_opcode_string
from opencis.util.logger import logger


class MctpCciExecutor(RunnableComponent):
    def __init__(
        self,
        mctp_connection: MctpConnection,
        switch_connection_manager: SwitchConnectionManager,
        port_configs: List[PortConfig],
        label: Optional[str] = None,
    ):
        super().__init__(label)
        self._message_tag_list = {}
        self._mctp_connection = mctp_connection
        self._cci_executor = CciExecutor(label="MCTP")
        self._switch_connection_manager = switch_connection_manager
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
        return CciRequest(opcode=packet.header.command_opcode, payload=packet.get_payload())

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

        response_packet_tmc = CciPayloadPacket.create(
            response_packet, response_packet.get_total_size()
        )

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
            cci_packet = cci_packet_tmc.get_packet()

            opcode = cci_packet.header.command_opcode
            port_index = cci_packet_tmc.cci_header.port_index

            opcodes_for_ld = [
                CCI_FM_API_COMMAND_OPCODE.GET_LD_INFO,
                CCI_FM_API_COMMAND_OPCODE.GET_LD_ALLOCATIONS,
                CCI_FM_API_COMMAND_OPCODE.SET_LD_ALLOCATIONS,
            ]
            if opcode in opcodes_for_ld:
                # Pass down to MLD
                # ld_index = cci_packet_tmc.cci_header.port_index
                message_tag = cci_packet.header.message_tag
                self._message_tag_list[message_tag] = port_index

                downstream_packet = None
                if opcode == CCI_FM_API_COMMAND_OPCODE.GET_LD_INFO:
                    downstream_packet = GetLdInfoRequestPacket.create_from_cci_message(cci_packet)
                if opcode == CCI_FM_API_COMMAND_OPCODE.GET_LD_ALLOCATIONS:
                    downstream_packet = GetLdAllocationsRequestPacket.create_from_cci_message(
                        cci_packet
                    )

                if opcode == CCI_FM_API_COMMAND_OPCODE.SET_LD_ALLOCATIONS:
                    downstream_packet = SetLdAllocationsRequestPacket.create_from_cci_message(
                        cci_packet
                    )

                await self._downstream_port_connections[port_index].cci_fifo.host_to_target.put(
                    downstream_packet
                )
            else:
                # Convert packet to CciRequest and send it to CciExecutor
                request = self._packet_to_request(cci_packet)
                response = await self._cci_executor.execute_command(request)
                await self._send_response(response, cci_packet.header.message_tag)

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

            cci_packet = packet.create_cci_message()
            cci_packet_tmc = CciPayloadPacket.create(cci_packet, cci_packet.get_total_size())

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
            await downstream_connection.target_to_host.put(None)
        await self._cci_executor.stop()

    async def get_background_command_status(self) -> CciBackgroundStatus:
        status = await self._cci_executor.get_background_command_status()
        return status

    async def send_notification(self, request: CciRequest):
        message_packet = CciMessagePacket.create(
            request.payload,
            message_category=CCI_MCTP_MESSAGE_CATEGORY.REQUEST,
            opcode=request.opcode,
        )
        opcode_str = get_opcode_string(request.opcode)
        message_packet_tmc = CciPayloadPacket.create(
            message_packet, message_packet.get_total_size()
        )
        logger.debug(self._create_message(f"Sending {opcode_str}"))
        await self._mctp_connection.ep_to_controller.put(message_packet_tmc)
