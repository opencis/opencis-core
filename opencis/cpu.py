"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

import asyncio
from typing import Callable, Awaitable
from tqdm.auto import tqdm

from opencis.util.component import RunnableComponent
from opencis.cxl.component.cxl_memory_hub import CxlMemoryHub


class CPU(RunnableComponent):
    def __init__(
        self,
        cxl_memory_hub: CxlMemoryHub,
        sys_sw_app: Callable[[], Awaitable[None]],
        user_app: Callable[[], Awaitable[None]],
    ):
        super().__init__()
        self._cxl_memory_hub = cxl_memory_hub
        self._sys_sw_app = sys_sw_app
        self._user_app = user_app
        self._fut = None
        self._app_task = None

    async def _run_sys_sw_app(self, *args, **kwargs):
        kwargs["cxl_memory_hub"] = self._cxl_memory_hub
        await self._sys_sw_app(*args, **kwargs)

    async def _run_user_app(self, *args, **kwargs):
        kwargs["cpu"] = self
        kwargs["cxl_memory_hub"] = self._cxl_memory_hub
        await self._user_app(*args, **kwargs)

    def create_message(self, message):
        return self._create_message(message)

    async def load(self, addr: int, size: int) -> int:
        if size <= 64:
            data = await self._cxl_memory_hub.load(addr, size)
        else:
            data_bytes = await self.load_bytes(addr, size)
            data = int.from_bytes(data_bytes, "little")
        return data

    async def load_bytes(self, addr: int, size: int, prog_bar: bool = False) -> bytes:
        end = addr + size
        result = b""
        with tqdm(
            total=size,
            desc="Reading Data",
            unit="iB",
            unit_scale=True,
            unit_divisor=1024,
            disable=not prog_bar,
        ) as pbar:
            for cacheline_offset in range(addr, addr + size, 64):
                cacheline = await self._cxl_memory_hub.load(cacheline_offset, 64)
                chunk_size = min(64, (end - cacheline_offset))
                chunk_data = cacheline.to_bytes(64, "little")
                result += chunk_data[:chunk_size]
                pbar.update(chunk_size)
        return result

    async def store(self, addr: int, size: int, value: int, prog_bar: bool = False):
        if size <= 64:
            res = await self._cxl_memory_hub.store(addr, size, value)
        else:
            if addr % 64 or size % 64:
                raise Exception("Size and address must be aligned to 64!")

            with tqdm(
                total=size,
                desc="Writing Data",
                unit="iB",
                unit_scale=True,
                unit_divisor=1024,
                disable=not prog_bar,
            ) as pbar:
                chunk_count = 0
                while size > 0:
                    low_64_byte = value & ((1 << (64 * 8)) - 1)
                    res = await self._cxl_memory_hub.store(
                        addr + (chunk_count * 64), 64, low_64_byte
                    )
                    if not res:
                        return res
                    size -= 64
                    chunk_count += 1
                    value >>= 64 * 8
                    pbar.update(64)
        return res

    async def _app_run_task(self):
        return await self._user_app(_cpu=self, _mem_hub=self._cxl_memory_hub)

    async def _run(self):
        await self._run_sys_sw_app()
        self._app_task = asyncio.create_task(self._run_user_app())
        await self._change_status_to_running()
        self._fut = asyncio.Future()
        await self._app_task
        await self._fut

    async def _stop(self):
        self._app_task.cancel()
        self._fut.set_result("CPU Done")
