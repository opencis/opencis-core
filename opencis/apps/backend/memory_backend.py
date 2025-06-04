"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

import pickle
from typing import Tuple, Callable

from opencis.util.logger import logger

class AlignedMemoryBackend:
    def __init__(
        self,
        load_fn: Callable[[int, int], int],
        store_fn: Callable[[int, int, int], None],
        hpa_base_addr: int = 0,
    ):
        self._base_addr = hpa_base_addr
        self._load_fn = load_fn
        self._store_fn = store_fn

    def set_base_addr(self, addr: int):
        self._base_addr = addr

    async def load(self, addr: int, size: int) -> int:
        addr += self._base_addr
        return await self._load_fn(addr, size)

    async def store(self, addr: int, size: int, value: int):
        addr += self._base_addr
        await self._store_fn(addr, size, value)

    def _align_range(self, addr: int, size: int) -> Tuple[int, int]:
        aligned_start = addr & ~0x3F
        aligned_end = (addr + size + 63) & ~0x3F
        return aligned_start, aligned_end

    async def read_bytes(self, addr: int, size: int) -> bytes:
        logger.debug(f"READ_BYTES: addr=0x{addr:X}, size={size}")
        aligned_start, aligned_end = self._align_range(addr, size)
        data = bytearray()
        for offset in range(aligned_start, aligned_end, 64):
            chunk = await self.load(offset, 64)
            data.extend(chunk.to_bytes(64, "little"))
        start_offset = addr - aligned_start
        return bytes(data[start_offset : start_offset + size])

    async def write_bytes(self, addr: int, data: bytes):
        logger.debug(f"WRITE_BYTES: addr=0x{addr:X}, data_len={len(data)}")
        aligned_start, aligned_end = self._align_range(addr, len(data))
        start_offset = addr - aligned_start
        padded = bytearray(aligned_end - aligned_start)
        padded[start_offset : start_offset + len(data)] = data

        for offset in range(0, len(padded), 64):
            chunk = int.from_bytes(padded[offset : offset + 64], "little")
            await self.store(aligned_start + offset, 64, chunk)


class StructuredMemoryAdapter:
    def __init__(self, backend: AlignedMemoryBackend):
        self.backend = backend
        self.ptr = 0

    def _allocate(self, size: int) -> int:
        aligned_size = (size + 63) & ~0x3F
        addr = self.ptr
        self.ptr += aligned_size
        return addr

    async def store_object(self, obj) -> Tuple[int, int]:
        raw = pickle.dumps(obj)
        raw_len = len(raw)
        addr = self._allocate(raw_len)
        await self.backend.write_bytes(addr, raw)
        return addr, raw_len

    async def load_object(self, addr: int, size: int):
        raw = await self.backend.read_bytes(addr, size)
        return pickle.loads(raw)
