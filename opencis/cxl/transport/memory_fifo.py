"""
Copyright (c) 2024, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from asyncio import Queue
from dataclasses import dataclass, field
from enum import Enum, auto


class MEMORY_REQUEST_TYPE(Enum):
    READ = auto()
    WRITE = auto()
    UNCACHED_READ = auto()
    UNCACHED_WRITE = auto()


@dataclass
class MemoryRequest:
    type: MEMORY_REQUEST_TYPE
    addr: int
    size: int
    data: int = 0


class MEMORY_RESPONSE_STATUS(Enum):
    OK = auto()
    FAILED = auto()


@dataclass
class MemoryResponse:
    status: MEMORY_RESPONSE_STATUS
    data: int = 0


@dataclass
class MemoryFifoPair:
    request: Queue[MemoryRequest] = field(default_factory=Queue)
    response: Queue[MemoryResponse] = field(default_factory=Queue)
