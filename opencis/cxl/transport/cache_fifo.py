"""
 Copyright (c) 2024, Eeum, Inc.

 This software is licensed under the terms of the Revised BSD License.
 See LICENSE for details.
"""

from asyncio import Queue
from dataclasses import dataclass, field
from enum import Enum, auto


class CACHE_REQUEST_TYPE(Enum):
    READ = auto()
    WRITE = auto()
    SNP_DATA = auto()
    SNP_INV = auto()
    SNP_CUR = auto()
    WRITE_BACK = auto()
    WRITE_BACK_CLEAN = auto()
    UNCACHED_WRITE = auto()
    UNCACHED_READ = auto()


@dataclass
class CacheRequest:
    type: CACHE_REQUEST_TYPE
    addr: int
    size: int = 0
    data: int = 0

    def get_address(self) -> int:
        return self.addr


class CACHE_RESPONSE_STATUS(Enum):
    OK = auto()
    FAILED = auto()
    RSP_V = auto()
    RSP_M = auto()
    RSP_E = auto()
    RSP_S = auto()
    RSP_I = auto()
    RSP_MISS = auto()


@dataclass
class CacheResponse:
    status: CACHE_RESPONSE_STATUS
    data: int = 0


@dataclass
class CacheFifoPair:
    request: Queue[CacheRequest] = field(default_factory=Queue)
    response: Queue[CacheResponse] = field(default_factory=Queue)
