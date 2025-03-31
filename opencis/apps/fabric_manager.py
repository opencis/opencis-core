"""
Copyright (c) 2024, Eeum, Inc.

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
        use_test_runner: bool = False,
    ):
        super().__init__()
        self._connection_manager = MctpConnectionManager(mctp_host, mctp_port)

        self._api_client = MctpCciApiClient(self._connection_manager.get_mctp_connection())
        self._host_fm_conn_server = ShortMsgConn(
            "FM_Server", port=host_fm_conn_port, server=True, msg_width=16, msg_type=HostFMMsg
        )
        self._host_fm_conn_manager = HostFMConnManager(self._api_client, self._host_fm_conn_server)
        self._socketio_server = FabricManagerSocketIoServer(
            self._api_client, self._host_fm_conn_manager, socketio_host, socketio_port
        )

        self._host_fm_conn_server.register_general_handler(HostFMMsg.CONFIRM, self._host_callback())
        self._use_test_runner = use_test_runner

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
        ]
        wait_tasks = [
            create_task(self._connection_manager.wait_for_ready()),
            create_task(self._socketio_server.wait_for_ready()),
            create_task(self._api_client.wait_for_ready()),
            create_task(self._host_fm_conn_server.wait_for_ready()),
        ]
        if self._use_test_runner:
            tasks.append(create_task(self._run_test()))
        await gather(*wait_tasks)
        await self._change_status_to_running()
        await gather(*tasks)

    async def _stop(self):
        await self._host_fm_conn_server.stop()
        await self._connection_manager.stop()
        await self._socketio_server.stop()
        await self._api_client.stop()
