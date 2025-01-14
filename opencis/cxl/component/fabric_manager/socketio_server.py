"""
 Copyright (c) 2024, Eeum, Inc.

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
    CciMessagePacket,
    GetLdAllocationsRequestPayload,
    SetLdAllocationsRequestPayload,
)
from opencis.cxl.cci.common import (
    CCI_VENDOR_SPECIFIC_OPCODE,
    get_opcode_string,
)


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
    ):
        super().__init__()
        self._mctp_client = mctp_client
        self._host_fm_conn_manager = host_fm_conn_manager
        self._host = host
        self._port = port
        self._event_lock = asyncio.Lock()
        self._switch_identity = None
        self._stop_signal = False

        # Create a new Aiohttp web app
        self._app = web.Application()

        # Create a Socket.IO server
        self._sio = socketio.AsyncServer(cors_allowed_origins="*")
        self._sio.attach(self._app)
        self._runner = web.AppRunner(self._app)

        self._register_handler("port:get")
        self._register_handler("vcs:get")
        self._register_handler("device:get")
        self._register_handler("vcs:bind")
        self._register_handler("vcs:unbind")
        self._register_handler("mld:get")
        self._register_handler("mld:getAllocation")
        self._register_handler("mld:setAllocation")
        self._mctp_client.register_notification_handler(self._handle_notifications)

    def _register_handler(self, event):
        self._sio.on(event, partial(self._handle_event, event))

    async def _handle_notifications(self, packet: CciMessagePacket):
        logger.debug(self._create_message("Handling Notification"))
        opcode = packet.header.command_opcode
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
        (return_code, response) = await self._mctp_client.get_connected_devices()
        if response:
            return CommandResponse(error="", result=response.to_dict()["devices"])
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
        await self._host_fm_conn_manager.notify_host_unbind(
            data["vppbId"], data["virtualCxlSwitchId"]
        )
        (return_code, response) = await self._mctp_client.unbind_vppb(request)
        if response is not None:
            return CommandResponse(error="", result=response.name)
        return CommandResponse(error="", result=return_code.name)

    async def _get_ld_info(self, data) -> CommandResponse:
        (return_code, response) = await self._mctp_client.get_ld_info(data["portIndex"])
        if response:
            return CommandResponse(error="", result=response.to_dict())
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
            return CommandResponse(error="", result=response.to_dict())
        return CommandResponse(error=return_code.name)

    async def _set_ld_allocation(self, data) -> CommandResponse:
        request = SetLdAllocationsRequestPayload(
            number_of_lds=data["numberOfLds"],
            start_ld_id=data["startLdId"],
            ld_allocation_list=data["ldAllocationList"],
        )
        (return_code, response) = await self._mctp_client.set_ld_alloctaion(
            request, data["portIndex"]
        )
        if response:
            return CommandResponse(
                error="",
                result=[response.number_of_lds, response.start_ld_id, response.ld_allocation_list],
            )
        return CommandResponse(error=return_code.name)

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

        # Here you could add a condition to run indefinitely or until a stop signal is received
        while not self._stop_signal:
            await asyncio.sleep(1)  # Run forever or until a stop signal is set

    async def _stop(self):
        self._stop_signal = True
        await self._runner.cleanup()
