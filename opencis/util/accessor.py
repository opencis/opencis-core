"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

import mmap
import os


class FileAccessor:
    def __init__(self, filename: str, size: int):
        with open(filename, "w+b") as file:
            fd = file.fileno()
            if os.path.isfile(filename):
                os.posix_fallocate(fd, 0, size)
            self._mmap = mmap.mmap(fd, size)

    async def write(self, offset: int, data: int, size: int):
        # TODO: Check for OOB
        data_bytes = data.to_bytes(size, "little")
        self._mmap[offset : offset + size] = data_bytes

    async def read(self, offset: int, size: int) -> int:
        # TODO: Check for OOB
        data = self._mmap[offset : offset + size]
        return int.from_bytes(data, "little")

    def close(self):
        self._mmap.close()
