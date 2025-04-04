"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from typing import Optional, TypedDict

from opencis.pci.config_space.pci import (
    PciConfigSpaceType1,
    PciConfigSpaceType1Options,
    PciConfigSpaceType0,
    PciConfigSpaceType0Options,
)
from opencis.pci.config_space.pcie.pcie_capability import (
    PciExpressCapabilityRegister,
    PciExpressCapabilityRegisterOptions,
)
from opencis.pci.config_space.pcie.msi import (
    MsiCapability,
    MsiCapabilityOptions,
)
from opencis.util.unaligned_bit_structure import (
    StructureField,
    ByteField,
    BitMaskedBitStructure,
    ShareableByteArray,
    FIELD_ATTR,
)
from opencis.pci.component.pci import (
    PciBridgeComponent,
    PciComponent,
    PciComponentIdentity,
)

PCI_CONFIG_OFFSET_MAX = 0xFF
PCIE_CONFIG_OFFSET_MAX = 0xFFF


class PciExpressDeviceConfigSpaceOptions(TypedDict):
    pci_component: PciComponent


class PciExpressPortConfigSpaceOptions(TypedDict):
    pci_bridge_component: PciBridgeComponent


class PciExpressConfigSpace(BitMaskedBitStructure):
    def __init__(
        self,
        data: Optional[ShareableByteArray] = None,
        parent_name: Optional[str] = None,
        options: Optional[PciExpressDeviceConfigSpaceOptions] = None,
    ):
        if options:
            # creating a PCI-only device (non-CXL)
            # assume non-bridge device
            self._pci_component = options["pci_component"]
            self._is_bridge = False
            self._fields = []
            start = self._append_pci_fields(self._pci_component.get_identity())
            self._append_reserved_pcix(start)
        super().__init__(data, parent_name)

    def _append_pci_fields(self, identity: PciComponentIdentity) -> int:
        start = 0
        start = self._append_pci_header(start)
        start = self._append_msicap(start)
        start = self._append_pcie_cap(start, identity)
        start = self._append_reserved(start)
        return start

    def _append_pci_header(self, start: int) -> int:
        if self._is_bridge:
            pci_type = PciConfigSpaceType1
            pci_options = PciConfigSpaceType1Options(
                pci_bridge_component=self._pci_component, capability_pointer=0
            )
            size = PciConfigSpaceType1.get_size_from_options(pci_options)
        else:
            pci_type = PciConfigSpaceType0
            pci_options = PciConfigSpaceType0Options(
                pci_component=self._pci_component, capability_pointer=0
            )
            size = PciConfigSpaceType0.get_size_from_options(pci_options)

        end = start + size - 1
        pci_options["capability_pointer"] = end + 1
        self._fields.append(
            StructureField("pci", start, end, pci_type, options=pci_options),
        )
        return end + 1

    def _append_msicap(self, start: int) -> int:
        msi_options = MsiCapabilityOptions(next_capability_offset=0)
        msi_cap_size = MsiCapability.get_size_from_options()
        end = start + msi_cap_size - 1
        msi_options["next_capability_offset"] = end + 1
        self._fields.append(
            StructureField("msi_capability", start, end, MsiCapability, options=msi_options)
        )
        return end + 1

    def _append_pcie_cap(self, start: int, identity: PciComponentIdentity) -> int:
        pcie_cap_options = PciExpressCapabilityRegisterOptions(pci_component_identity=identity)
        pcie_cap_size = PciExpressCapabilityRegister.get_size_from_options()
        end = start + pcie_cap_size - 1
        self._fields.append(
            StructureField(
                "pcie_capability",
                start,
                end,
                PciExpressCapabilityRegister,
                options=pcie_cap_options,
            )
        )
        return end + 1

    def _append_reserved(self, start: int) -> int:
        end = PCI_CONFIG_OFFSET_MAX
        self._fields.append(ByteField("reserved1", start, end, attribute=FIELD_ATTR.RESERVED))
        return end + 1

    def _append_reserved_pcix(self, start: int) -> int:
        end = PCIE_CONFIG_OFFSET_MAX
        self._fields.append(ByteField("reserved2", start, end, attribute=FIELD_ATTR.RESERVED))
        return end + 1
