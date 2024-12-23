"""
 Copyright (c) 2024, Eeum, Inc.

 This software is licensed under the terms of the Revised BSD License.
 See LICENSE for details.
"""

from asyncio import Event, Lock


class BoundEvent:
    def __init__(self):
        self.ev = Event()
        self._lock = Lock()
        self.res = None

    # def __await__(self):
    #     return self.ev.wait().__await__()

    async def set_result(self, result):
        async with self._lock:
            self.res = result
            self.ev.set()

    async def result(self):
        # change to "claim_result"
        async with self._lock:
            ret = self.res
            self.ev.clear()
        return ret
