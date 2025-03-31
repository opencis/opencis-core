"""
Copyright (c) 2024, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from typing import Optional

from opencis.cxl.config_space.dvsec import (
    DvsecConfigSpace,
    DvsecConfigSpaceOptions,
    CXL_DEVICE_TYPE,
)
from opencis.cxl.config_space.doe.doe import (
    CxlDoeExtendedCapability,
    CxlDoeExtendedCapabilityOptions,
)
from opencis.cxl.config_space.serial_number.common import (
    DeviceSNCapability,
    DeviceSNCapabilityOptions,
)
from opencis.pci.config_space import PciExpressConfigSpace
from opencis.util.unaligned_bit_structure import (
    StructureField,
    ShareableByteArray,
)


class CxlConfigSpace(PciExpressConfigSpace):
    def __init__(
        self,
        device_type: CXL_DEVICE_TYPE,
        data: Optional[ShareableByteArray] = None,
        parent_name: Optional[str] = None,
    ):
        self._dvsec_options: DvsecConfigSpaceOptions
        self._doe_options: CxlDoeExtendedCapabilityOptions
        self._sn_options: DeviceSNCapabilityOptions
        self._is_bridge = device_type in (CXL_DEVICE_TYPE.USP, CXL_DEVICE_TYPE.DSP)
        self._fields = []
        start = self._append_pci_fields(self._pci_component.get_identity())
        start = self._append_cxl_fields(start, device_type)
        self._append_reserved_pcix(start)

        # calls constructor for BitMaskedBitStructure
        super().__init__(data, parent_name)

    def _append_cxl_fields(self, start: int, device_type: CXL_DEVICE_TYPE) -> int:
        if device_type == CXL_DEVICE_TYPE.LD:
            if self._sn_options is not None:
                start = self._append_sn(start)
        else:
            # TODO: remove placeholder SN for non-LD devices
            self._sn_options = DeviceSNCapabilityOptions(sn="1111111111111111")
            start = self._append_sn(start)
        if self._dvsec_options is not None:
            start = self._append_dvsec(start, device_type)
        if self._doe_options is not None:
            start = self._append_doe(start)
        return start

    def _append_dvsec(self, start: int, device_type: CXL_DEVICE_TYPE) -> int:
        options = self._dvsec_options
        dvsec_size = DvsecConfigSpace.get_size_from_options(options)
        end = start + dvsec_size - 1
        options["next"] = end + 1
        options["offset"] = start
        options["device_type"] = device_type
        self._fields.append(
            StructureField(
                "dvsec",
                start,
                end,
                DvsecConfigSpace,
                options=options,
            )
        )
        return end + 1

    def _append_doe(self, start: int) -> int:
        options = self._doe_options
        doe_size = CxlDoeExtendedCapability.get_size()
        end = start + doe_size - 1
        self._fields.append(
            StructureField("doe", start, end, CxlDoeExtendedCapability, options=options)
        )
        return end + 1

    def _append_sn(self, start: int) -> int:
        options = self._sn_options
        sn_size = DeviceSNCapability.get_size()
        end = start + sn_size - 1
        options["next"] = end + 1
        self._fields.append(
            StructureField("serial_number", start, end, DeviceSNCapability, options=options)
        )
        return end + 1
