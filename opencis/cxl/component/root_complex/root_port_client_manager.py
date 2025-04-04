"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

import asyncio
from dataclasses import dataclass, field
from typing import List
from opencis.util.component import RunnableComponent
from opencis.cxl.component.cxl_connection import CxlConnection
from opencis.cxl.component.switch_connection_client import SwitchConnectionClient
from opencis.cxl.component.common import CXL_COMPONENT_TYPE


@dataclass
class RootPortClientConfig:
    port_index: int
    switch_host: str
    switch_port: int


@dataclass
class RootPortClientManagerConfig:
    host_name: str
    client_configs: List[RootPortClientConfig] = field(default_factory=list)


@dataclass
class RootPortConnection:
    connection: CxlConnection
    port_index: int


class RootPortClientManager(RunnableComponent):
    def __init__(self, config: RootPortClientManagerConfig):
        super().__init__(lambda class_name: f"{config.host_name}:{class_name}:")

        self._sw_conn_clients: List[SwitchConnectionClient] = []
        for client_config in config.client_configs:
            connection_client = SwitchConnectionClient(
                client_config.port_index,
                CXL_COMPONENT_TYPE.R,
                host=client_config.switch_host,
                port=client_config.switch_port,
                parent_name=self.get_message_label(),
            )
            self._sw_conn_clients.append(connection_client)

    def get_cxl_connections(self) -> List[RootPortConnection]:
        connections = []
        for client in self._sw_conn_clients:
            connections.append(
                RootPortConnection(
                    connection=client.get_cxl_connection(), port_index=client.get_port_index()
                )
            )
        return connections

    async def _run(self):
        run_tasks = [asyncio.create_task(client.run()) for client in self._sw_conn_clients]
        wait_tasks = [
            asyncio.create_task(client.wait_for_ready()) for client in self._sw_conn_clients
        ]
        await asyncio.gather(*wait_tasks)
        await self._change_status_to_running()
        await asyncio.gather(*run_tasks)

    async def _stop(self):
        stop_tasks = [asyncio.create_task(client.stop()) for client in self._sw_conn_clients]
        await asyncio.gather(*stop_tasks)
