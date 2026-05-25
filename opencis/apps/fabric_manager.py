"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from asyncio import create_task, gather
import traceback
from opencis.cxl.component.mctp.mctp_connection_manager import (
    MctpConnectionManager,
)
from opencis.cxl.component.mctp.mctp_cci_api_client import (
    MctpCciApiClient,
    GetPhysicalPortStateRequestPayload,
    GetVirtualCxlSwitchInfoRequestPayload,
    BindVppbRequestPayload,
    UnbindVppbRequestPayload,
)
from opencis.cxl.component.fabric_manager.socketio_server import (
    FabricManagerSocketIoServer,
    HostFMConnManager,
    HostFMMsg,
)
from opencis.cxl.component.short_msg_conn import ShortMsgConn
from opencis.cxl.component.mctp.fm_mctp_cci_server import FmMctpCciServer
from opencis.cxl.component.pbr_switch_manager import (
    PbrSwitchManager,
    PidTarget,
    PidTargetType,
)
from opencis.cxl.cci.fabric_manager.pbr_switch import (
    IdentifyPbrSwitchCommand,
    ConfigurePidAssignmentCommand,
    GetPidBindingCommand,
    ConfigurePidBindingCommand,
    GetDrtCommand,
    SetDrtCommand,
)
from opencis.util.component import RunnableComponent
from opencis.util.logger import logger


class CxlFabricManager(RunnableComponent):
    def __init__(
        self,
        mctp_host: str = "0.0.0.0",
        mctp_port: int = 8100,
        socketio_host: str = "0.0.0.0",
        socketio_port: int = 8200,
        host_fm_conn_port: int = 8700,
        fm_mctp_cci_port: int = 8300,
        use_test_runner: bool = False,
        config_file: str = None,  # Add config file parameter
    ):
        super().__init__()
        self._connection_manager = MctpConnectionManager(mctp_host, mctp_port)

        self._api_client = MctpCciApiClient(self._connection_manager.get_mctp_connection())

        # Load device configs from config file if provided
        self._device_configs = []
        if config_file:
            try:
                from opencis.cxl.environment.environment import parse_cxl_environment

                env = parse_cxl_environment(config_file)
                self._device_configs = env.multi_logical_device_configs
                # Make device configs available to the API client
                self._api_client.set_device_configs(self._device_configs)
            except Exception as e:
                logger.warning(f"Could not load device configs from {config_file}: {e}")

        self._host_fm_conn_server = ShortMsgConn(
            "FM_Server", port=host_fm_conn_port, server=True, msg_width=16, msg_type=HostFMMsg
        )
        self._host_fm_conn_manager = HostFMConnManager(self._api_client, self._host_fm_conn_server)

        # Initialize MLD client for cross-process communication
        from opencis.cxl.component.mld_client import mld_client

        self._mld_client = mld_client

        self._socketio_server = FabricManagerSocketIoServer(
            self._api_client,
            self._host_fm_conn_manager,
            socketio_host,
            socketio_port,
            self._mld_client,
        )

        self._host_fm_conn_server.register_general_handler(HostFMMsg.CONFIRM, self._host_callback())
        self._use_test_runner = use_test_runner

        # --- FM-side authoritative PBR state ---
        # Phase 3: this single PbrSwitchManager instance is shared between
        #   port 8300 (FmMctpCciServer  — direct MCTP CCI)
        #   port 8200 (FabricManagerSocketIoServer — CLI commands)
        # Both paths read/write the same object, so the FM always has a
        # consistent authoritative view of the PBR control-plane state.
        self._fm_pbr_manager = PbrSwitchManager(
            num_drts=2,
            num_rgts=1,
            pid_targets=[
                PidTarget(target_id=0, target_type=PidTargetType.FABRIC_PORT,
                          instance_id=0, vcs_id=0, physical_port_id=0),
                PidTarget(target_id=1, target_type=PidTargetType.HOST_EDGE_PORT,
                          instance_id=0, vcs_id=0, physical_port_id=1),
                PidTarget(target_id=2, target_type=PidTargetType.DOWNSTREAM_EDGE_PORT,
                          instance_id=0, vcs_id=0, physical_port_id=2),
            ],
            label="FM-PbrManager",
        )
        pbr_commands = [
            IdentifyPbrSwitchCommand(self._fm_pbr_manager),
            ConfigurePidAssignmentCommand(self._fm_pbr_manager),
            GetPidBindingCommand(self._fm_pbr_manager),
            ConfigurePidBindingCommand(self._fm_pbr_manager),
            GetDrtCommand(self._fm_pbr_manager),
            SetDrtCommand(self._fm_pbr_manager),
        ]

        # Phase 2: pass self._api_client so the FM automatically mirrors
        # write commands (SetDRT, ConfigurePidAssignment, ConfigurePidBinding)
        # received on port 8300 to the physical switch on port 8100.
        self._fm_mctp_cci_server = FmMctpCciServer(
            host=mctp_host,
            port=fm_mctp_cci_port,
            cci_commands=pbr_commands,
            switch_api_client=self._api_client,   # Phase 2 — switch mirroring
        )
        logger.info(self._create_message(
            f"FM MCTP CCI server configured on port {fm_mctp_cci_port} "
            "(switch mirroring enabled via api_client)"
        ))

    # ------------------------------------------------------------------
    # Public accessors (Phase 3 — expose shared manager for testing/CLI)
    # ------------------------------------------------------------------

    def get_fm_pbr_manager(self) -> PbrSwitchManager:
        """Return the shared FM-side PbrSwitchManager instance.

        Tests and CLI tools may inspect this to verify that commands sent
        on port 8300 (MCTP) are reflected in FM state without querying the
        switch directly.
        """
        return self._fm_pbr_manager

    def get_fm_mctp_cci_port(self) -> int:
        """Return the actual port number used by FmMctpCciServer."""
        return self._fm_mctp_cci_server.get_port()


    def get_host_fm_port(self):
        return self._host_fm_conn_server.get_port()

    def _host_callback(self):
        async def _func(_: int, data: HostFMMsg):
            print(f"Received {data.readable} from host (root port={data.root_port})")

        return _func

    async def _run_test(self):
        try:
            await self._api_client.identify_switch_device()
            await self._api_client.get_physical_port_state(
                GetPhysicalPortStateRequestPayload([0, 1, 2, 3, 4])
            )
            await self._api_client.get_virtual_cxl_switch_info(
                GetVirtualCxlSwitchInfoRequestPayload(
                    start_vppb=0, vppb_list_limit=255, vcs_id_list=[0]
                )
            )
            await self._api_client.get_connected_devices()
            await self._api_client.unbind_vppb(UnbindVppbRequestPayload(vcs_id=0, vppb_id=0))
            await self._api_client.unbind_vppb(UnbindVppbRequestPayload(vcs_id=0, vppb_id=1))
            await self._api_client.unbind_vppb(UnbindVppbRequestPayload(vcs_id=0, vppb_id=2))
            await self._api_client.unbind_vppb(UnbindVppbRequestPayload(vcs_id=0, vppb_id=3))
            await self._api_client.bind_vppb(
                BindVppbRequestPayload(vcs_id=0, vppb_id=0, physical_port_id=1)
            )
            await self._api_client.bind_vppb(
                BindVppbRequestPayload(vcs_id=0, vppb_id=1, physical_port_id=2)
            )
            await self._api_client.bind_vppb(
                BindVppbRequestPayload(vcs_id=0, vppb_id=2, physical_port_id=3)
            )
            await self._api_client.bind_vppb(
                BindVppbRequestPayload(vcs_id=0, vppb_id=3, physical_port_id=4)
            )
        except Exception as e:
            logger.error(
                self._create_message(
                    f"{self.__class__.__name__} error: {str(e)}, {traceback.format_exc()}"
                )
            )

    async def _run(self):
        tasks = [
            create_task(self._connection_manager.run()),
            create_task(self._socketio_server.run()),
            create_task(self._api_client.run()),
            create_task(self._host_fm_conn_server.run()),
            create_task(self._fm_mctp_cci_server.run()),
        ]
        wait_tasks = [
            create_task(self._connection_manager.wait_for_ready()),
            create_task(self._socketio_server.wait_for_ready()),
            create_task(self._api_client.wait_for_ready()),
            create_task(self._host_fm_conn_server.wait_for_ready()),
            create_task(self._fm_mctp_cci_server.wait_for_ready()),
        ]
        if self._use_test_runner:
            tasks.append(create_task(self._run_test()))
        await gather(*wait_tasks)
        await self._change_status_to_running()
        await gather(*tasks)

    async def _stop(self):
        # Disconnect from MLD process
        if hasattr(self, "_mld_client") and self._mld_client:
            try:
                await self._mld_client.disconnect()
            except Exception as e:
                logger.warning(f"Error disconnecting from MLD process: {e}")

        await self._fm_mctp_cci_server.stop()
        await self._host_fm_conn_server.stop()
        await self._connection_manager.stop()
        await self._socketio_server.stop()
        await self._api_client.stop()
