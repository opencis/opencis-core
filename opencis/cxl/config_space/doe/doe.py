"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from typing import Optional, TypedDict, List

from opencis.pci.config_space.pcie.doe import (
    DoeExtendedCapability,
    DoeExtendedCapabilityOptions,
    DoeExtendedCapabilityHeaderOptions,
)
from opencis.util.unaligned_bit_structure import (
    ShareableByteArray,
)
from opencis.cxl.config_space.doe.cdat import CDAT_ENTRY
from opencis.cxl.config_space.doe.doe_table_access import (
    DoeTableAccessProtocol,
)


class CxlDoeExtendedCapabilityOptions(TypedDict):
    next: Optional[int]
    cdat_entries: List[CDAT_ENTRY]


class CxlDoeExtendedCapability(DoeExtendedCapability):
    def __init__(
        self,
        data: Optional[ShareableByteArray] = None,
        parent_name: Optional[str] = None,
        options: Optional[CxlDoeExtendedCapabilityOptions] = None,
    ):
        header_options: DoeExtendedCapabilityHeaderOptions = {}
        cdat_entries = []
        if options:
            header_options["next_capability_offset"] = options.get("next", 0)
            cdat_entries = options.get("cdat_entries", cdat_entries)

        doe_options: DoeExtendedCapabilityOptions = {
            "header": header_options,
            "protocols": [DoeTableAccessProtocol(cdat_entries)],
        }
        super().__init__(data, parent_name, doe_options)
