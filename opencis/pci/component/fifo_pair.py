"""
Copyright (c) 2024, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from asyncio import Queue
from dataclasses import dataclass, field


@dataclass
class FifoPair:
    host_to_target: Queue = field(default_factory=Queue)
    target_to_host: Queue = field(default_factory=Queue)
