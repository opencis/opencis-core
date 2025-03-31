"""
Copyright (c) 2024, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from dataclasses import dataclass

from opencis.pci.component.config_space_manager import ConfigSpaceManager
from opencis.pci.component.mmio_manager import MmioManager


@dataclass
class CxlIoCallbackData:
    mmio_manager: MmioManager
    config_space_manager: ConfigSpaceManager
    ld_id: int = 0  # ld_id is used meaningfully only used for MLD, default is 0
