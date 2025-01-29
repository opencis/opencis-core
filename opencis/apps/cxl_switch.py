"""
 Copyright (c) 2024, Eeum, Inc.

 This software is licensed under the terms of the Revised BSD License.
 See LICENSE for details.
"""

from asyncio import gather, create_task
from dataclasses import dataclass, field
import os
import signal
from typing import List

from opencis.pci.component.pci import SW_SWITCH_DID

from opencis.cxl.component.physical_port_manager import (
    PhysicalPortManager,
    PortConfig,
    PORT_TYPE,
)
from opencis.cxl.component.virtual_switch_manager import (
    VirtualSwitchManager,
    VirtualSwitchConfig,
)
from opencis.cxl.component.virtual_switch.virtual_switch import (
    SwitchUpdateEvent,
)
from opencis.cxl.component.switch_connection_manager import (
    SwitchConnectionManager,
    PortUpdateEvent,
)
from opencis.cxl.component.mctp.mctp_connection_client import (
    MctpConnectionClient,
)
from opencis.cxl.component.mctp.mctp_cci_executor import MctpCciExecutor
from opencis.cxl.cci.generic.information_and_status import (
    IdentifyCommand,
    IdentifyComponentType,
    IdentifyResponsePayload,
    BackgroundOperationStatusCommand,
)
from opencis.cxl.cci.fabric_manager.physical_switch import (
    IdentifySwitchDeviceCommand,
    GetPhysicalPortStateCommand,
)
from opencis.cxl.cci.fabric_manager.virtual_switch import (
    GetVirtualCxlSwitchInfoCommand,
    BindVppbCommand,
    UnbindVppbCommand,
)
from opencis.cxl.cci.vendor_specfic import (
    NotifySwitchUpdateRequestPayload,
    NotifyPortUpdateRequestPayload,
    NotifyDeviceUpdateRequestPayload,
    GetConnectedDevicesCommand,
)
from opencis.util.component import RunnableComponent
from opencis.cxl.device.config.logical_device import (
    LogicalDeviceConfig,
    MultiLogicalDeviceConfig,
)


@dataclass
class CxlSwitchConfig:
    port_configs: List[PortConfig] = field(default_factory=list)
    virtual_switch_configs: List[VirtualSwitchConfig] = field(default_factory=list)
    host: str = "0.0.0.0"
    port: int = 8000
    mctp_host: str = "0.0.0.0"
    mctp_port: int = 8100
    run_as_child: bool = False


class CxlSwitch(RunnableComponent):
    # TODO: CE-35, device enumeration from DSP is not supported yet.
    # Passing device configs from an environment file to PhysicalPortManager
    # as a workaround.
    def __init__(
        self,
        switch_config: CxlSwitchConfig,
        device_configs: List[LogicalDeviceConfig],
        start_mctp: bool = True,
    ):
        super().__init__()
        # Passed to GetPhysicalPortStateCommand so that port:get can retrieve SLD/MLD info
        # TODO: Remove it when FM initializes all SLD/MLD in runtime

        # FM set-allocate-ld command's pseudo function
        allocated_ld = {}
        for device in device_configs:
            port_index = device.port_index
            if isinstance(device, MultiLogicalDeviceConfig):
                for ld in device.ld_list:
                    allocated_ld.setdefault(port_index, []).append(ld)
            else:
                allocated_ld[port_index] = [0]

        self._device_configs = device_configs
        self._switch_connection_manager = SwitchConnectionManager(
            switch_config.port_configs, switch_config.host, switch_config.port
        )
        self._physical_port_manager = PhysicalPortManager(
            self._switch_connection_manager, switch_config.port_configs, self._device_configs
        )
        self._virtual_switch_manager = VirtualSwitchManager(
            switch_config.virtual_switch_configs,
            self._physical_port_manager,
            allocated_ld,
        )

        self._start_mctp = start_mctp
        if self._start_mctp:
            self._mctp_connection_client = MctpConnectionClient(
                switch_config.mctp_host, switch_config.mctp_port
            )
            self._mctp_cci_executor = MctpCciExecutor(
                self._mctp_connection_client.get_mctp_connection(),
                self._switch_connection_manager,
                switch_config.port_configs,
            )
            self._initialize_mctp_endpoint()

        self._run_as_child = switch_config.run_as_child

    def _initialize_mctp_endpoint(self):
        ident_payload = IdentifyResponsePayload(
            device_id=SW_SWITCH_DID, component_type=IdentifyComponentType.SWITCH
        )
        commands = [
            IdentifyCommand(ident_payload),
            BackgroundOperationStatusCommand(self._mctp_cci_executor),
            IdentifySwitchDeviceCommand(self._physical_port_manager, self._virtual_switch_manager),
            GetPhysicalPortStateCommand(self._switch_connection_manager, self._device_configs),
            GetVirtualCxlSwitchInfoCommand(self._virtual_switch_manager),
            BindVppbCommand(self._physical_port_manager, self._virtual_switch_manager),
            UnbindVppbCommand(self._virtual_switch_manager),
            GetConnectedDevicesCommand(self._physical_port_manager),
        ]
        self._mctp_cci_executor.register_cci_commands(commands)

        async def handle_port_event(event: PortUpdateEvent):
            payload = NotifyPortUpdateRequestPayload(event.port_id, event.connected)
            request = payload.create_request()
            await self._mctp_cci_executor.send_notification(request)
            switch_ports = self._switch_connection_manager.get_switch_ports()
            if switch_ports[event.port_id].port_config.type == PORT_TYPE.DSP:
                payload = NotifyDeviceUpdateRequestPayload()
                request = payload.create_request()
                await self._mctp_cci_executor.send_notification(request)

        async def handle_switch_event(event: SwitchUpdateEvent):
            payload = NotifySwitchUpdateRequestPayload(
                event.vcs_id, event.vppb_id, event.binding_status
            )
            request = payload.create_request()
            await self._mctp_cci_executor.send_notification(request)

        self._switch_connection_manager.register_event_handler(handle_port_event)
        self._virtual_switch_manager.register_event_handler(handle_switch_event)

    async def _run(self):
        components = [
            self._switch_connection_manager,
            self._physical_port_manager,
            self._virtual_switch_manager,
        ]
        if self._start_mctp:
            components.extend([self._mctp_cci_executor, self._mctp_connection_client])

        run_tasks = [create_task(comp.run()) for comp in components]

        wait_tasks = [create_task(comp.wait_for_ready()) for comp in components]

        await gather(*wait_tasks)
        if self._run_as_child:
            os.kill(os.getppid(), signal.SIGCONT)
        await self._change_status_to_running()
        if self._run_as_child:
            os.kill(os.getppid(), signal.SIGCONT)
        await gather(*run_tasks)

    async def _stop(self):
        stop_tasks = [
            create_task(self._switch_connection_manager.stop()),
            create_task(self._physical_port_manager.stop()),
            create_task(self._virtual_switch_manager.stop()),
        ]
        if self._start_mctp:
            stop_tasks.append(create_task(self._mctp_connection_client.stop()))
            stop_tasks.append(create_task(self._mctp_cci_executor.stop()))
        await gather(*stop_tasks)
