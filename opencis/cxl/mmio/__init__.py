"""
Copyright (c) 2024, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from typing import List, TypedDict, Optional, cast
from opencis.util.unaligned_bit_structure import (
    BitMaskedBitStructure,
    ShareableByteArray,
    StructureField,
)
from opencis.cxl.mmio.component_register import (
    CxlComponentRegister,
    CxlComponentRegisterOptions,
)
from opencis.cxl.mmio.device_register import (
    CxlDeviceRegister,
    CxlDeviceRegisterOptions,
)
from opencis.cxl.component.cxl_component import (
    CxlComponent,
    CxlDeviceComponent,
)
from opencis.cxl.component.common import CXL_COMPONENT_TYPE
from opencis.cxl.config_space.dvsec.register_locator import (
    RegisterOffsetOptions,
    BLOCK_IDENTIFIER,
)


class CombinedMmioRegiterOptions(TypedDict):
    cxl_component: CxlComponent


class CombinedMmioRegister(BitMaskedBitStructure):
    def __init__(
        self,
        data: Optional[ShareableByteArray] = None,
        parent_name: Optional[str] = None,
        options: Optional[CombinedMmioRegiterOptions] = None,
    ):
        if not options:
            raise Exception("options is required")

        self._cxl_component = options["cxl_component"]
        self._fields = []
        self._dvsec_offsets: List[RegisterOffsetOptions] = []

        offset = 0
        offset = self._add_cxl_component_register(offset)
        offset = self._add_cxl_device_register(offset)

        super().__init__(data, parent_name)

    def _add_cxl_component_register(self, offset: int) -> int:
        options = CxlComponentRegisterOptions(cxl_component=self._cxl_component)
        component_register_size = CxlComponentRegister.get_size_from_options(options)
        self._fields.append(
            StructureField(
                "component",
                offset,
                offset + component_register_size - 1,
                CxlComponentRegister,
                options=options,
            )
        )
        self._dvsec_offsets.append(
            RegisterOffsetOptions(
                bir=0,
                block_identifier=BLOCK_IDENTIFIER.COMPONENT_REGISTER,
                block_offset=offset,
            )
        )
        return offset + component_register_size

    def _add_cxl_device_register(self, offset: int) -> int:
        if self._cxl_component.get_component_type() != CXL_COMPONENT_TYPE.D2:
            return offset

        cxl_device_component = cast(CxlDeviceComponent, self._cxl_component)
        options = CxlDeviceRegisterOptions(cxl_device_component=cxl_device_component)
        device_register_size = CxlDeviceRegister.get_size_from_options(options)
        self._fields.append(
            StructureField(
                "device",
                offset,
                offset + device_register_size - 1,
                CxlDeviceRegister,
                options=options,
            )
        )
        self._dvsec_offsets.append(
            RegisterOffsetOptions(
                bir=0,
                block_identifier=BLOCK_IDENTIFIER.CXL_DEVICE_REGISTER,
                block_offset=offset,
            )
        )
        return offset + device_register_size

    def get_dvsec_register_offsets(self) -> List[RegisterOffsetOptions]:
        return self._dvsec_offsets

    @staticmethod
    def get_size_from_options(
        options: Optional[CombinedMmioRegiterOptions] = None,
    ) -> int:
        if not options:
            raise Exception("options is required")

        cxl_component = options["cxl_component"]

        size = CxlComponentRegister.get_size_from_options(
            CxlComponentRegisterOptions(cxl_component=cxl_component)
        )

        if cxl_component.get_component_type() == CXL_COMPONENT_TYPE.D2:
            cxl_device_component = cast(CxlDeviceComponent, cxl_component)
            size += CxlDeviceRegister.get_size_from_options(
                CxlDeviceRegisterOptions(cxl_device_component=cxl_device_component)
            )
        return size
