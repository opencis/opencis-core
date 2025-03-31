"""
Copyright (c) 2024, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from dataclasses import dataclass, field
from asyncio import Queue
from opencis.pci.component.pci_connection import PciConnection


@dataclass
class MctpConnection(PciConnection):
    controller_to_ep: Queue = field(default_factory=Queue)
    ep_to_controller: Queue = field(default_factory=Queue)
