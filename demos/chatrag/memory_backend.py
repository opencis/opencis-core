
import pickle
from typing import Tuple, Callable


class MemoryBackend:
    def __init__(self):
        self.memory = {}

    async def load(self, addr: int, size: int) -> int:
        assert size == 64
        print(f"loading a:{addr:x} s:{size:x}")
        return int.from_bytes(self.memory.get(addr, b"\x00" * 64), "little")

    async def store(self, addr: int, size: int, value: int):
        assert size == 64
        print(f"storing:{addr:x} s:{size:x}")
        self.memory[addr] = value.to_bytes(64, "little")


class AlignedMemoryBackend:
    def __init__(self, load_fn: Callable[[int, int], int], store_fn: Callable[[int, int, int], None]):
        self.load = load_fn
        self.store = store_fn

    def _align_range(self, addr: int, size: int) -> Tuple[int, int]:
        aligned_start = addr & ~0x3F
        aligned_end = (addr + size + 63) & ~0x3F
        return aligned_start, aligned_end

    async def read_bytes(self, addr: int, size: int) -> bytes:
        print(f"READ_BYTES: addr=0x{addr:X}, size={size}")
        aligned_start, aligned_end = self._align_range(addr, size)
        data = bytearray()
        for offset in range(aligned_start, aligned_end, 64):
            chunk = await self.load(offset, 64)
            data.extend(chunk.to_bytes(64, 'little'))
        start_offset = addr - aligned_start
        return bytes(data[start_offset:start_offset + size])

    async def write_bytes(self, addr: int, data: bytes):
        print(f"WRITE_BYTES: addr=0x{addr:X}, data_len={len(data)}")
        aligned_start, aligned_end = self._align_range(addr, len(data))
        start_offset = addr - aligned_start
        padded = bytearray((aligned_end - aligned_start))
        padded[start_offset:start_offset + len(data)] = data

        for offset in range(0, len(padded), 64):
            chunk = int.from_bytes(padded[offset:offset + 64], 'little')
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
        original_len = len(raw)
        addr = self._allocate(original_len)
        await self.backend.write_bytes(addr, raw)
        return addr, original_len

    async def load_object(self, addr: int, size: int):
        raw = await self.backend.read_bytes(addr, size)
        return pickle.loads(raw)