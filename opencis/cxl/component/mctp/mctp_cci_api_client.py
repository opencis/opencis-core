"""
 Copyright (c) 2024, Eeum, Inc.

 This software is licensed under the terms of the Revised BSD License.
 See LICENSE for details.
"""

from asyncio import Condition
from typing import cast, Any, Tuple, Optional, Callable, Dict, Coroutine

from opencis.cxl.component.mctp.mctp_connection import MctpConnection
from opencis.cxl.transport.transaction import (
    CciMessagePacket,
    CciMessageHeaderPacket,
    CCI_MCTP_MESSAGE_CATEGORY,
    CciPayloadPacket,
)
from opencis.cxl.cci.common import get_opcode_string
from opencis.cxl.cci.generic.information_and_status import (
    BackgroundOperationStatusCommand,
    BackgroundOperationStatusResponsePayload,
)
from opencis.cxl.cci.fabric_manager.physical_switch import (
    IdentifySwitchDeviceCommand,
    IdentifySwitchDeviceResponsePayload,
    GetPhysicalPortStateCommand,
    GetPhysicalPortStateRequestPayload,
    GetPhysicalPortStateResponsePayload,
)
from opencis.cxl.cci.fabric_manager.virtual_switch import (
    GetVirtualCxlSwitchInfoCommand,
    GetVirtualCxlSwitchInfoRequestPayload,
    GetVirtualCxlSwitchInfoResponsePayload,
    BindVppbCommand,
    BindVppbRequestPayload,
    UnbindVppbCommand,
    UnbindVppbRequestPayload,
)
from opencis.cxl.cci.fabric_manager.mld_components import (
    GetLdInfoCommand,
    GetLdInfoResponsePayload,
    GetLdAllocationsCommand,
    GetLdAllocationsRequestPayload,
    GetLdAllocationsResponsePayload,
    SetLdAllocationsCommand,
    SetLdAllocationsRequestPayload,
    SetLdAllocationsResponsePayload,
)
from opencis.cxl.cci.vendor_specfic import (
    GetConnectedDevicesCommand,
    GetConnectedDevicesResponsePayload,
)
from opencis.cxl.cci.common import CCI_RETURN_CODE
from opencis.cxl.component.cci_executor import CciRequest
from opencis.util.component import RunnableComponent
from opencis.util.logger import logger

CreateRequestFuncType = Callable[[Optional[Any]], CciRequest]
AsyncEventHandlerType = Callable[[CciMessagePacket], Coroutine[Any, Any, None]]


class MctpCciApiClient(RunnableComponent):
    def __init__(self, mctp_connection: MctpConnection):
        super().__init__()
        self._mctp_connection = mctp_connection
        self._tag = 0
        self._responses: Dict[int, CciMessagePacket] = {}
        self._condition = Condition()
        self._notification_handler = None

    async def _process_incoming_packets(self):
        while True:
            raw_response = await self._mctp_connection.ep_to_controller.get()
            if raw_response is None:
                break

            response_tmc1 = cast(CciPayloadPacket, raw_response)
            response = response_tmc1.get_packet()
            if response.header.message_category == CCI_MCTP_MESSAGE_CATEGORY.REQUEST:
                opcode_str = get_opcode_string(response.header.command_opcode)
                logger.debug(
                    self._create_message(f"Received request (notification) packet {opcode_str}")
                )
                if self._notification_handler is not None:
                    await self._notification_handler(response)
            else:
                logger.debug(self._create_message("Received response packet"))
                await self._condition.acquire()
                self._responses[response.header.message_tag] = response
                self._condition.notify_all()
                self._condition.release()

    async def _run(self):
        await self._change_status_to_running()
        await self._process_incoming_packets()

    async def _stop(self):
        await self._mctp_connection.ep_to_controller.put(None)

    async def _get_response(self, message_tag: int) -> CciMessagePacket:
        await self._condition.acquire()
        logger.debug(self._create_message(f"Waiting for Message {message_tag}"))
        while message_tag not in self._responses:
            await self._condition.wait()
        logger.debug(self._create_message(f"Received Message {message_tag}"))
        response = self._responses[message_tag]
        self._condition.release()
        return response

    async def _send_request(self, request: CciMessagePacket, port_index=0, _=0) -> CciMessagePacket:
        request.header.message_tag = self._get_next_tag()
        opcode_name = get_opcode_string(request.header.command_opcode)
        req_tag = request.header.message_tag
        logger.debug(self._create_message(f"Sending {opcode_name} (Tag: {req_tag})"))
        # wrapping
        request_tmc = CciPayloadPacket.create(request, request.get_total_size(), port_index)

        await self._mctp_connection.controller_to_ep.put(request_tmc)
        response = await self._get_response(req_tag)
        res_tag = response.header.message_tag
        logger.debug(self._create_message(f"Received Response (Tag: {res_tag})"))

        if (
            response.header.background_operation
            and response.header.return_code == CCI_RETURN_CODE.BACKGROUND_COMMAND_STARTED
        ):
            logger.debug(self._create_message("Background Command Started"))
            return response

        if response.header.return_code != CCI_RETURN_CODE.SUCCESS:
            return_code_str = CCI_RETURN_CODE(response.header.return_code).name
            message = f"Command failed with status: {return_code_str}"
            logger.debug(self._create_message(message))

        return response

    def _get_next_tag(self) -> int:
        tag = self._tag
        self._tag += 1
        return tag

    def _create_request_packet(self, request: CciRequest) -> CciMessagePacket:
        header = CciMessageHeaderPacket()
        header.message_category = CCI_MCTP_MESSAGE_CATEGORY.REQUEST
        header.command_opcode = request.opcode
        header.set_message_payload_length(len(request.payload))
        message_packet = CciMessagePacket.create(header, request.payload)
        return message_packet

    async def _wait_for_background_operation(self) -> CCI_RETURN_CODE:
        completed = False
        while not completed:
            (return_code, result) = await self.background_operation_status()
            if not result:
                continue
            completed = not result.background_operation_status.operation_in_progress
            if completed:
                return return_code
        # TODO: Handle timeout

    async def _send_cci_command(
        self, create_request_func: CreateRequestFuncType, request=None, port_index=0, ld_id=0
    ):
        cci_request = create_request_func() if request is None else create_request_func(request)
        request_message_packet = self._create_request_packet(cci_request)
        return await self._send_request(request_message_packet, port_index, ld_id)

    def register_notification_handler(self, notification_handler: AsyncEventHandlerType):
        self._notification_handler = notification_handler

    async def background_operation_status(
        self,
    ) -> Tuple[CCI_RETURN_CODE, Optional[BackgroundOperationStatusResponsePayload]]:
        response_message_packet = await self._send_cci_command(
            BackgroundOperationStatusCommand.create_cci_request
        )

        return_code = CCI_RETURN_CODE(response_message_packet.header.return_code)
        if return_code != CCI_RETURN_CODE.SUCCESS:
            return (return_code, None)
        response = BackgroundOperationStatusCommand.parse_response_payload(
            response_message_packet.get_payload()
        )
        # logger.debug(self._create_message(response.get_pretty_print()))
        return (return_code, response)

    async def identify_switch_device(
        self,
    ) -> Tuple[CCI_RETURN_CODE, Optional[IdentifySwitchDeviceResponsePayload]]:
        response_message_packet = await self._send_cci_command(
            IdentifySwitchDeviceCommand.create_cci_request
        )

        return_code = CCI_RETURN_CODE(response_message_packet.header.return_code)
        if return_code != CCI_RETURN_CODE.SUCCESS:
            return (return_code, None)
        response = IdentifySwitchDeviceCommand.parse_response_payload(
            response_message_packet.get_payload()
        )
        logger.debug(self._create_message(response.get_pretty_print()))
        return (return_code, response)

    async def get_physical_port_state(
        self, request: GetPhysicalPortStateRequestPayload
    ) -> Tuple[CCI_RETURN_CODE, Optional[GetPhysicalPortStateResponsePayload]]:
        response_message_packet = await self._send_cci_command(
            GetPhysicalPortStateCommand.create_cci_request, request
        )

        return_code = CCI_RETURN_CODE(response_message_packet.header.return_code)
        if return_code != CCI_RETURN_CODE.SUCCESS:
            return (return_code, None)
        response = GetPhysicalPortStateCommand.parse_response_payload(
            response_message_packet.get_payload()
        )
        # logger.debug(self._create_message(response.get_pretty_print()))
        return (return_code, response)

    async def get_virtual_cxl_switch_info(
        self, request: GetVirtualCxlSwitchInfoRequestPayload
    ) -> Tuple[CCI_RETURN_CODE, Optional[GetVirtualCxlSwitchInfoResponsePayload]]:
        response_message_packet = await self._send_cci_command(
            GetVirtualCxlSwitchInfoCommand.create_cci_request, request
        )

        return_code = CCI_RETURN_CODE(response_message_packet.header.return_code)
        if return_code != CCI_RETURN_CODE.SUCCESS:
            return (return_code, None)
        response = GetVirtualCxlSwitchInfoCommand.parse_response_payload(
            response_message_packet.get_payload(),
            request.start_vppb,
            request.vppb_list_limit,
        )
        logger.debug(self._create_message(response.get_pretty_print()))
        return (return_code, response)

    async def bind_vppb(
        self, request: BindVppbRequestPayload, wait_for_completion: bool = True
    ) -> Tuple[CCI_RETURN_CODE, Optional[CCI_RETURN_CODE]]:
        response_message_packet = await self._send_cci_command(
            BindVppbCommand.create_cci_request, request
        )

        return_code = CCI_RETURN_CODE(response_message_packet.header.return_code)
        if wait_for_completion:
            return_code = await self._wait_for_background_operation()
        has_error = return_code not in (
            CCI_RETURN_CODE.SUCCESS,
            CCI_RETURN_CODE.BACKGROUND_COMMAND_STARTED,
        )
        if has_error:
            return (return_code, None)
        return (return_code, return_code)

    async def unbind_vppb(
        self, request: UnbindVppbRequestPayload, wait_for_completion: bool = True
    ) -> Tuple[CCI_RETURN_CODE, Optional[CCI_RETURN_CODE]]:
        response_message_packet = await self._send_cci_command(
            UnbindVppbCommand.create_cci_request, request
        )

        return_code = CCI_RETURN_CODE(response_message_packet.header.return_code)
        if wait_for_completion:
            return_code = await self._wait_for_background_operation()
        has_error = return_code not in (
            CCI_RETURN_CODE.SUCCESS,
            CCI_RETURN_CODE.BACKGROUND_COMMAND_STARTED,
        )
        if has_error:
            return (return_code, None)
        return (return_code, return_code)

    async def get_connected_devices(
        self,
    ) -> Tuple[CCI_RETURN_CODE, Optional[GetConnectedDevicesResponsePayload]]:
        response_message_packet = await self._send_cci_command(
            GetConnectedDevicesCommand.create_cci_request
        )

        return_code = CCI_RETURN_CODE(response_message_packet.header.return_code)
        if return_code != CCI_RETURN_CODE.SUCCESS:
            return (return_code, None)
        response = GetConnectedDevicesCommand.parse_response_payload(
            response_message_packet.get_payload()
        )
        # logger.debug(self._create_message(response.get_pretty_print()))
        return (return_code, response)

    async def get_ld_info(
        self, port_index: int
    ) -> Tuple[CCI_RETURN_CODE, Optional[GetLdInfoResponsePayload]]:
        response_message_packet = await self._send_cci_command(
            GetLdInfoCommand.create_cci_request, port_index=port_index
        )

        return_code = CCI_RETURN_CODE(response_message_packet.header.return_code)
        if return_code != CCI_RETURN_CODE.SUCCESS:
            return (return_code, None)
        response = GetLdInfoCommand.parse_response_payload(response_message_packet.get_payload())
        return (return_code, response)

    async def get_ld_alloctaion(
        self, request: GetLdAllocationsRequestPayload, port_index: int
    ) -> Tuple[CCI_RETURN_CODE, Optional[GetLdAllocationsResponsePayload]]:
        response_message_packet = await self._send_cci_command(
            GetLdAllocationsCommand.create_cci_request, request, port_index=port_index
        )

        return_code = CCI_RETURN_CODE(response_message_packet.header.return_code)
        if return_code != CCI_RETURN_CODE.SUCCESS:
            return (return_code, None)
        response = GetLdAllocationsCommand.parse_response_payload(
            response_message_packet.get_payload()
        )
        return (return_code, response)

    async def set_ld_alloctaion(
        self, request: SetLdAllocationsRequestPayload, port_index: int
    ) -> Tuple[CCI_RETURN_CODE, Optional[SetLdAllocationsResponsePayload]]:
        response_message_packet = await self._send_cci_command(
            SetLdAllocationsCommand.create_cci_request, request, port_index=port_index
        )

        return_code = CCI_RETURN_CODE(response_message_packet.header.return_code)
        if return_code != CCI_RETURN_CODE.SUCCESS:
            return (return_code, None)
        response = SetLdAllocationsCommand.parse_response_payload(
            response_message_packet.get_payload()
        )
        return (return_code, response)
