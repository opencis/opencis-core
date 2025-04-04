"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from typing import Dict, TypedDict, Optional, List, Tuple
from opencis.util.unaligned_bit_structure import (
    BitMaskedBitStructure,
    BitField,
    DataField,
    StructureField,
    FIELD_ATTR,
    ShareableByteArray,
)
from opencis.cxl.component.cxl_component import CXL_DEVICE_CAPABILITY_TYPE


class CxlDeviceCapabilitiesArrayRegisterOptions(TypedDict):
    type: Optional[CXL_DEVICE_CAPABILITY_TYPE]
    capabilities_count: Optional[int]


class CxlDeviceCapabilitiesArrayRegister(BitMaskedBitStructure):
    capability_id: int
    version: int
    type: int
    capabilities_count: int

    def __init__(
        self,
        data: Optional[ShareableByteArray] = None,
        parent_name: Optional[str] = None,
        options: Optional[CxlDeviceCapabilitiesArrayRegisterOptions] = None,
    ):
        if not options:
            options = CxlDeviceCapabilitiesArrayRegisterOptions()
        type = options.get("type", CXL_DEVICE_CAPABILITY_TYPE.INFER_PCI_CLASS_CODE)
        capabilities_count = options.get("capabilities_count", 0)

        self._fields = [
            BitField("capability_id", 0, 15, FIELD_ATTR.RO, 0x0000),
            BitField("version", 16, 23, FIELD_ATTR.RO, 0x01),
            BitField("type", 24, 27, FIELD_ATTR.RO, type),
            BitField("reserved1", 28, 31, FIELD_ATTR.RESERVED),
            BitField("capabilities_count", 32, 47, FIELD_ATTR.RO, capabilities_count),
            BitField("reserved2", 48, 127, FIELD_ATTR.RESERVED),
        ]

        super().__init__(data, parent_name)

    @classmethod
    def get_size(cls, fields: List[DataField] | None = None) -> int:
        return 16


class CxlDeviceCapabilityHeaderRegisterOptions(TypedDict):
    capability_id: int
    version: int
    offset: int
    length: int


class CapabilityMapItem(TypedDict):
    capability_id: int
    version: int
    type: Optional[CXL_DEVICE_CAPABILITY_TYPE]


CapabilityMap = Dict[str, CapabilityMapItem]

CAPABILITIES_MAP: CapabilityMap = {
    "device_status": {"capability_id": 0x0001, "version": 0x02, "type": None},
    "primary_mailbox": {"capability_id": 0x0002, "version": 0x01, "type": None},
    "secondary_mailbox": {"capability_id": 0x0003, "version": 0x01, "type": None},
    "memory_device_status": {
        "capability_id": 0x4000,
        "version": 0x01,
        "type": CXL_DEVICE_CAPABILITY_TYPE.MEMORY_DEVICE,
    },
}


class CxlDeviceCapabilityHeaderRegister(BitMaskedBitStructure):
    def __init__(
        self,
        data: Optional[ShareableByteArray] = None,
        parent_name: Optional[str] = None,
        options: Optional[CxlDeviceCapabilityHeaderRegisterOptions] = None,
    ):
        if not options:
            raise Exception('"options" parameter is required')

        capability_id = options["capability_id"]
        version = options["version"]
        offset = options["offset"]
        length = options["length"]

        self._fields = [
            BitField("capability_id", 0, 15, FIELD_ATTR.RO, capability_id),
            BitField("version", 16, 23, FIELD_ATTR.RO, version),
            BitField("reserved1", 24, 31, FIELD_ATTR.RESERVED),
            BitField("offset", 32, 63, FIELD_ATTR.RO, offset),
            BitField("length", 64, 95, FIELD_ATTR.RO, length),
            BitField("reserved2", 96, 127, FIELD_ATTR.RESERVED),
        ]

        super().__init__(data, parent_name)

    @classmethod
    def get_size(cls, fields: List[DataField] | None = None) -> int:
        return 16


CapabilityOption = Dict[str, Tuple[int, int]]


class CxlDeviceCapabilityRegisterOptions(TypedDict):
    type: CXL_DEVICE_CAPABILITY_TYPE
    capabilities: CapabilityOption


class CxlDeviceCapabilityRegister(BitMaskedBitStructure):
    capabilities_array: CxlDeviceCapabilitiesArrayRegister

    def __init__(
        self,
        data: Optional[ShareableByteArray] = None,
        parent_name: Optional[str] = None,
        options: Optional[CxlDeviceCapabilityRegisterOptions] = None,
    ):
        if not options:
            raise Exception("options is required")

        capabilities = options["capabilities"]
        type = options["type"]
        capabilities_array_options = CxlDeviceCapabilitiesArrayRegisterOptions(
            capabilities_count=len(capabilities), type=type
        )
        self._fields = [
            StructureField(
                "capabilities_array",
                0x00,
                0x0F,
                CxlDeviceCapabilitiesArrayRegister,
                options=capabilities_array_options,
            )
        ]
        self.add_headers(type, capabilities)

        super().__init__(data, parent_name)

    def add_headers(self, type: CXL_DEVICE_CAPABILITY_TYPE, capabilities: CapabilityOption):
        offset = CxlDeviceCapabilitiesArrayRegister.get_size()
        header_id = 1
        header_size = CxlDeviceCapabilityHeaderRegister.get_size()
        for capability_name, capability_value in capabilities.items():
            (capability_offset, capability_length) = capability_value

            if capability_offset == 0 or capability_length == 0:
                continue

            if capability_name not in CAPABILITIES_MAP:
                raise Exception(f'capability "{capability_name}" is undefined')

            capability_id = CAPABILITIES_MAP[capability_name]["capability_id"]
            version = CAPABILITIES_MAP[capability_name]["version"]
            capability_type = CAPABILITIES_MAP[capability_name]["type"]

            if capability_type and type != capability_type:
                raise Exception(f'capability "{capability_name}" is not defiend for type {type}')

            options = CxlDeviceCapabilityHeaderRegisterOptions(
                capability_id=capability_id,
                version=version,
                offset=capability_offset,
                length=capability_length,
            )
            self._fields.append(
                StructureField(
                    f"capabilities{header_id}_header",
                    offset,
                    offset + header_size - 1,
                    CxlDeviceCapabilityHeaderRegister,
                    options=options,
                )
            )
            offset += header_size
            header_id += 1

    @staticmethod
    def get_size_from_options(
        options: Optional[CxlDeviceCapabilityRegisterOptions] = None,
    ) -> int:
        if not options:
            raise Exception("options is required")

        headers_count = len(options["capabilities"])
        return (
            CxlDeviceCapabilitiesArrayRegister.get_size()
            + headers_count * CxlDeviceCapabilityHeaderRegister.get_size()
        )
