"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from asyncio import gather, create_task
from dataclasses import dataclass, field
import os
import signal
from typing import List, Optional

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
from opencis.cxl.cci.fabric_manager.mld_components import (
    SetLdAllocationsCommand,
)
from opencis.cxl.cci.fabric_manager.physical_switch import (
    IdentifySwitchDeviceCommand,
    GetPhysicalPortStateCommand,
)
from opencis.cxl.cci.fabric_manager.virtual_switch import (
    GetVirtualCxlSwitchInfoCommand,
    BindVppbCommand,
    UnbindVppbCommand,
    FreezeVppbCommand,
    UnfreezeVppbCommand,
)
from opencis.cxl.cci.vendor_specfic import (
    NotifySwitchUpdateRequestPayload,
    NotifyPortUpdateRequestPayload,
    NotifyDeviceUpdateRequestPayload,
    GetConnectedDevicesCommand,
)
from opencis.cxl.cci.fabric_manager.pbr_switch import (
    IdentifyPbrSwitchCommand,
    ConfigurePidAssignmentCommand,
    GetPidBindingCommand,
    ConfigurePidBindingCommand,
    GetDrtCommand,
    SetDrtCommand,
)
from opencis.cxl.cci.fabric_manager.gae import (
    IdentifyGaeCommand,
    GetPidAccessVectorsCommand,
    ProxyGfdMgmtCommand,
    GetProxyThreadStatusCommand,
    CancelProxyThreadCommand,
)
from opencis.cxl.component.gae_manager import GaeManager
from opencis.cxl.component.pbr_switch_manager import PbrSwitchManager
from opencis.cxl.component.pbr_switch_router import PbrSwitchRouter
from opencis.cxl.component.hdm_decoder import (
    PbrHdmDecoderManager,
    HdmDecoderCapabilities,
    HDM_DECODER_COUNT,
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
    enable_pbr: bool = False
    hdm_decoder_capabilities: Optional[dict] = None


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
                # Only add LDs if the ld_list is not empty (for dynamic configurations)
                if device.ld_list:
                    for ld in device.ld_list:
                        allocated_ld.setdefault(port_index, []).append(ld)
                # For empty ld_list (dynamic config), don't add any LDs
            else:
                # For single logical devices, add LD 0
                allocated_ld[port_index] = [0]

        self._device_configs = device_configs
        self._switch_connection_manager = SwitchConnectionManager(
            switch_config.port_configs,
            switch_config.host,
            switch_config.port,
            connection_timeout_ms=5000,  # Add this parameter
            device_configs=device_configs,  # Use keyword argument
        )
        self._physical_port_manager = PhysicalPortManager(
            self._switch_connection_manager, switch_config.port_configs, self._device_configs
        )
        self._virtual_switch_manager = VirtualSwitchManager(
            switch_config.virtual_switch_configs,
            self._physical_port_manager,
            allocated_ld,
        )

        # PBR Switch Manager — only instantiated if enable_pbr=True
        self._pbr_switch_manager = PbrSwitchManager() if switch_config.enable_pbr else None
        self._pbr_switch_router = None
        self._enable_pbr = switch_config.enable_pbr

        # GAE Manager — one per switch, tracks proxy threads and vPPB list
        # Instantiated alongside PbrSwitchManager so GAE CCI commands can be registered.
        self._gae_manager = (
            GaeManager(vppbs=[], label="Switch0:GAE") if switch_config.enable_pbr else None
        )

        if switch_config.enable_pbr and self._pbr_switch_manager is not None:
            # Gap 3 — HDM decoder manager: maps Host Physical Address → DPID at ingress.
            # Initialised with a single decoder slot; the FM CLI programs it via
            # pbr:setDrt / future pbr:setHdmDecoder command, or it can be pre-committed
            # by the launch script.
            if switch_config.hdm_decoder_capabilities is not None:
                _pbr_hdm_caps: HdmDecoderCapabilities = switch_config.hdm_decoder_capabilities
            else:
                _pbr_hdm_caps: HdmDecoderCapabilities = {
                    "decoder_count": HDM_DECODER_COUNT.DECODER_2,
                    "target_count": 2,
                    "a11to8_interleave_capable": 0,
                    "a14to12_interleave_capable": 0,
                    "poison_on_decoder_error_capability": 0,
                    "three_six_twelve_way_interleave_capable": 0,
                    "sixteen_way_interleave_capable": 0,
                    "uio_capable": 0,
                    "uio_capable_decoder_count": 0,
                    "mem_data_nxm_capable": 0,
                    "bi_capable": False,
                }
            self._pbr_hdm_decoder_manager = PbrHdmDecoderManager(
                _pbr_hdm_caps, label="PbrHdmDecoderManager"
            )
            # Gap 1 — PbrSwitchRouter: data-plane engine, wired to physical-port FIFOs.
            # get_port_fifos() is called lazily in _run() after PhysicalPortManager is ready.
            self._pbr_switch_router = PbrSwitchRouter(
                switch_id=0,
                pbr_switch_manager=self._pbr_switch_manager,
                port_fifos=self._physical_port_manager.get_port_fifos(),
                hdm_decoder_manager=self._pbr_hdm_decoder_manager,
                port_types=[pc.type == PORT_TYPE.USP for pc in switch_config.port_configs],
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
                self._virtual_switch_manager,
            )
            self._initialize_mctp_endpoint()

        self._run_as_child = switch_config.run_as_child

    def get_port(self):
        return self._switch_connection_manager.get_port()

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
            FreezeVppbCommand(self._virtual_switch_manager),
            UnfreezeVppbCommand(self._virtual_switch_manager),
            SetLdAllocationsCommand(self._virtual_switch_manager),
        ]
        # Register PBR + GAE commands only if the switch is in PBR mode
        if self._enable_pbr and self._pbr_switch_manager:
            commands.extend([
                # PBR Switch control plane (0x5700–0x5709)
                IdentifyPbrSwitchCommand(self._pbr_switch_manager),
                ConfigurePidAssignmentCommand(self._pbr_switch_manager),
                GetPidBindingCommand(self._pbr_switch_manager),
                ConfigurePidBindingCommand(self._pbr_switch_manager),
                GetDrtCommand(self._pbr_switch_manager),
                SetDrtCommand(self._pbr_switch_manager),
            ])
        if self._enable_pbr and self._gae_manager:
            commands.extend([
                # GAE control plane (0x5800–0x580B) — §7.7.14
                IdentifyGaeCommand(self._gae_manager),
                GetPidAccessVectorsCommand(self._gae_manager),
                ProxyGfdMgmtCommand(self._gae_manager),
                GetProxyThreadStatusCommand(self._gae_manager),
                CancelProxyThreadCommand(self._gae_manager),
            ])
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
                # Bind GFD DSP CCI tunnel to GaeManager so proxy commands can
                # be forwarded to the GFD's CciExecutor over the switch cci_fifo.
                if event.connected and self._gae_manager is not None:
                    tunnel = self._mctp_cci_executor.get_tunnel(event.port_id)
                    if tunnel is not None:
                        self._gae_manager.set_gfd_tunnel(tunnel)
                elif not event.connected and self._gae_manager is not None:
                    # GFD disconnected — clear the tunnel binding
                    self._gae_manager.set_gfd_tunnel(None)

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
        # Gap 1 — start the PBR data-plane router alongside the other switch components
        if self._pbr_switch_router is not None:
            components.append(self._pbr_switch_router)

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
        if self._pbr_switch_router is not None:
            stop_tasks.append(create_task(self._pbr_switch_router.stop()))
        await gather(*stop_tasks)
