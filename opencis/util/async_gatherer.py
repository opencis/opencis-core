"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

import asyncio


class AsyncGatherer:
    def __init__(self):
        self._tasks = set()
        self._event = asyncio.Event()

    def add_task(self, coro):
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._on_task_done)
        return task

    def _on_task_done(self, task):
        self._tasks.remove(task)
        if not self._tasks:
            self._event.set()

    async def wait_for_completion(self):
        while self._tasks:
            await self._event.wait()
            self._event.clear()
