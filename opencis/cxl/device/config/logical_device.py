"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from dataclasses import dataclass
from typing import List
from opencis.pci.component.pci import EEUM_VID, SW_SLD_DID, SW_MLD_DID


@dataclass(kw_only=True)
class LogicalDeviceConfig:
    port_index: int
    device_id: int
    vendor_id: int = EEUM_VID
    subsystem_vendor_id: int = 0
    subsystem_id: int = 0


@dataclass(kw_only=True)
class SingleLogicalDeviceConfig(LogicalDeviceConfig):
    memory_size: int  # in bytes
    memory_file: str
    serial_number: str
    device_id: int = SW_SLD_DID


@dataclass(kw_only=True)
class MultiLogicalDeviceConfig(LogicalDeviceConfig):
    memory_sizes: List[int]  # in bytes
    ld_list: List[int]
    memory_files: List[str]
    serial_numbers: List[str]
    ld_count: int
    device_id: int = SW_MLD_DID
