"""
 Copyright (c) 2024, Eeum, Inc.

 This software is licensed under the terms of the Revised BSD License.
 See LICENSE for details.
"""


class FileAccessor:
    def __init__(self, filename: str, size: int):
        self.filename = filename
        with open(filename, "wb") as file:
            file.write(b"\x00" * size)
            file.flush()

    async def write(self, offset: int, data: int, size: int):
        # TODO: Check for OOB and use asyncio
        with open(self.filename, "r+b") as file:
            file.seek(offset)
            file.write(data.to_bytes(size, byteorder="little"))

    async def read(self, offset: int, size: int) -> int:
        # TODO: Check for OOB and use asyncio
        with open(self.filename, "rb") as file:
            file.seek(offset)
            data = file.read(size)
            return int.from_bytes(data, byteorder="little")
