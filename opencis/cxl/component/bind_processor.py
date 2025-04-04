"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from asyncio import Queue, create_task, gather
from dataclasses import dataclass

from opencis.cxl.component.cxl_connection import CxlConnection
from opencis.util.component import RunnableComponent


@dataclass
class BindPair:
    source: Queue
    destination: Queue


class GenericBindProcessor(RunnableComponent):
    def __init__(
        self,
        downsteam_connection: CxlConnection,
        upstream_connection: CxlConnection,
    ):
        super().__init__()
        self._dsc = downsteam_connection
        self._usc = upstream_connection

        self._pairs = [
            BindPair(self._dsc.cfg_fifo.host_to_target, self._usc.cfg_fifo.host_to_target),
            BindPair(self._usc.cfg_fifo.target_to_host, self._dsc.cfg_fifo.target_to_host),
            BindPair(self._dsc.mmio_fifo.host_to_target, self._usc.mmio_fifo.host_to_target),
            BindPair(self._usc.mmio_fifo.target_to_host, self._dsc.mmio_fifo.target_to_host),
            BindPair(
                self._dsc.cxl_mem_fifo.host_to_target,
                self._usc.cxl_mem_fifo.host_to_target,
            ),
            BindPair(
                self._usc.cxl_mem_fifo.target_to_host,
                self._dsc.cxl_mem_fifo.target_to_host,
            ),
            BindPair(
                self._dsc.cxl_cache_fifo.host_to_target,
                self._usc.cxl_cache_fifo.host_to_target,
            ),
            BindPair(
                self._usc.cxl_cache_fifo.target_to_host,
                self._dsc.cxl_cache_fifo.target_to_host,
            ),
        ]

    def _create_message(self, message):
        message = f"[{self.__class__.__name__}] {message}"
        return message

    # Similar code with pci_to_pci_bridge_device.py:*_process()
    # pylint: disable=duplicate-code
    async def _process(self, source: Queue, destination: Queue):
        while True:
            packet = await source.get()
            if packet is None:
                break
            await destination.put(packet)

    async def _run(self):
        tasks = []
        for pair in self._pairs:
            task = create_task(self._process(pair.source, pair.destination))
            tasks.append(task)
        await self._change_status_to_running()
        await gather(*tasks)

    async def _stop(self):
        for pair in self._pairs:
            await pair.source.put(None)


class PpbDspBindProcessor(GenericBindProcessor):
    # vcs_id and vppb_id are not needed in PPB-DSP relation
    def _create_message(self, message):
        message = f"[{self.__class__.__name__}] {message}"
        return message


class VppbPpbBindProcessor(GenericBindProcessor):
    def __init__(
        self,
        vcs_id: int,
        vppb_id: int,
        downsteam_connection: CxlConnection,
        upstream_connection: CxlConnection,
    ):
        super().__init__(downsteam_connection, upstream_connection)
        self._vcs_id = vcs_id
        self._vppb_id = vppb_id

    def _create_message(self, message):
        message = f"[{self.__class__.__name__}:VCS{self._vcs_id}:vPPB{self._vppb_id}] {message}"
        return message
