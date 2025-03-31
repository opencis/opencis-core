"""
Copyright (c) 2024, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from dataclasses import dataclass, field
from opencis.pci.component.fifo_pair import FifoPair


@dataclass
class PciConnection:
    cfg_fifo: FifoPair = field(default_factory=FifoPair)
    mmio_fifo: FifoPair = field(default_factory=FifoPair)
