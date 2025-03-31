"""
Copyright (c) 2024, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from typing import TypedDict, Optional, cast
from opencis.util.unaligned_bit_structure import (
    BitMaskedBitStructure,
    ShareableByteArray,
    StructureField,
)
from opencis.cxl.component.cxl_component import (
    CxlDeviceComponent,
    CXL_DEVICE_CAPABILITY_TYPE,
)
from opencis.cxl.component.cxl_memory_device_component import (
    CxlMemoryDeviceComponent,
)
from opencis.cxl.mmio.device_register.device_capabilities import (
    CxlDeviceCapabilityRegisterOptions,
    CxlDeviceCapabilityRegister,
    CapabilityOption,
)
from opencis.cxl.mmio.device_register.device_status_register import (
    DeviceStatusRegisters,
    DeviceStatusRegistersOptions,
)
from opencis.cxl.mmio.device_register.mailbox_register import (
    MailboxRegister,
    MailboxRegisterOptions,
)
from opencis.cxl.mmio.device_register.memory_device_capabilities import (
    MemoryDeviceStatusRegisters,
    MemoryDeviceStatusRegistersOptions,
)
from opencis.cxl.features.mailbox import CxlMailbox


class CxlDeviceRegisterOptions(TypedDict):
    cxl_device_component: CxlDeviceComponent


class CxlDeviceRegister(BitMaskedBitStructure):
    def __init__(
        self,
        data: Optional[ShareableByteArray] = None,
        parent_name: Optional[str] = None,
        options: Optional[CxlDeviceRegisterOptions] = None,
    ):
        if not options:
            raise Exception("options is required")

        self._cxl_device_component = options["cxl_device_component"]

        self._fields = []

        (offset, capabilities) = self._add_capability_register()
        offset = self._add_primary_mailbox_capability(capabilities, offset)
        offset = self._add_secondary_mailbox_capability(capabilities, offset)
        offset = self._add_device_status_register(capabilities, offset)
        offset = self._add_memory_device_status_register(capabilities, offset)

        super().__init__(data, parent_name)

    def _add_capability_register(self) -> int:
        capabilities = self.construct_capability_option(self._cxl_device_component)

        capability_register_options = CxlDeviceCapabilityRegisterOptions()
        capability_register_options["type"] = self._cxl_device_component.get_capability_type()
        capability_register_options["capabilities"] = capabilities
        capability_register_size = CxlDeviceCapabilityRegister.get_size_from_options(
            capability_register_options
        )

        self._fields.append(
            StructureField(
                "capability",
                0x00,
                capability_register_size - 1,
                CxlDeviceCapabilityRegister,
                options=capability_register_options,
            )
        )

        return capability_register_size, capabilities

    def _add_device_status_register(
        self,
        capabilities: CapabilityOption,
        offset: int,
    ):
        device_status_register_options = DeviceStatusRegistersOptions(
            cxl_device_component=self._cxl_device_component
        )
        device_status_register_size = DeviceStatusRegisters.get_size_from_options(
            device_status_register_options
        )
        self._fields.append(
            StructureField(
                "device_status",
                offset,
                offset + device_status_register_size - 1,
                DeviceStatusRegisters,
                options=device_status_register_options,
            )
        )
        capabilities["device_status"] = (offset, device_status_register_size)
        return offset + device_status_register_size

    def _add_mailbox_capability(
        self,
        mailbox: CxlMailbox,
        capabilities: CapabilityOption,
        capability_name: str,
        offset: int,
    ) -> int:
        mailbox_register_options = MailboxRegisterOptions(cxl_mailbox=mailbox)
        mailbox_register_size = MailboxRegister.get_size_from_options(mailbox_register_options)
        self._fields.append(
            StructureField(
                capability_name,
                offset,
                offset + mailbox_register_size - 1,
                MailboxRegister,
                options=mailbox_register_options,
            )
        )
        capabilities[capability_name] = (offset, mailbox_register_size)
        return offset + mailbox_register_size

    def _add_primary_mailbox_capability(
        self,
        capabilities: CapabilityOption,
        offset: int,
    ) -> int:
        if self._cxl_device_component.get_primary_mailbox() is None:
            return offset

        capability_name = "primary_mailbox"
        offset = self._add_mailbox_capability(
            self._cxl_device_component.get_primary_mailbox(),
            capabilities,
            capability_name,
            offset,
        )
        return offset

    def _add_secondary_mailbox_capability(
        self,
        capabilities: CapabilityOption,
        offset: int,
    ) -> int:
        if self._cxl_device_component.get_secondary_mailbox() is None:
            return offset

        capability_name = "secondary_mailbox"
        offset = self._add_mailbox_capability(
            self._cxl_device_component.get_secondary_mailbox(),
            capabilities,
            capability_name,
            offset,
        )
        return offset

    def _add_memory_device_status_register(
        self,
        capabilities: CapabilityOption,
        offset: int,
    ) -> int:
        if (
            self._cxl_device_component.get_capability_type()
            != CXL_DEVICE_CAPABILITY_TYPE.MEMORY_DEVICE
        ):
            return offset

        if not isinstance(self._cxl_device_component, CxlMemoryDeviceComponent):
            raise Exception("device type mismatch")

        cxl_memory_device_component = cast(CxlMemoryDeviceComponent, self._cxl_device_component)
        memory_device_status_register_options = MemoryDeviceStatusRegistersOptions(
            cxl_memory_device_component=cxl_memory_device_component
        )
        memory_device_status_register_size = MemoryDeviceStatusRegisters.get_size_from_options(
            memory_device_status_register_options
        )
        self._fields.append(
            StructureField(
                "memory_device_status",
                offset,
                offset + memory_device_status_register_size - 1,
                MemoryDeviceStatusRegisters,
                options=memory_device_status_register_options,
            )
        )
        capabilities["memory_device_status"] = (
            offset,
            memory_device_status_register_size,
        )
        return offset + memory_device_status_register_size

    @staticmethod
    def construct_capability_option(
        cxl_device_component: CxlDeviceComponent,
    ) -> CapabilityOption:
        # Note: Add capabilities with zero register offset and size.
        # The register offset and size will be updated when an actual register
        # is added later.
        capabilities: CapabilityOption = {}

        capabilities["device_status"] = (0, 0)
        if cxl_device_component.get_primary_mailbox():
            capabilities["primary_mailbox"] = (0, 0)
        if cxl_device_component.get_secondary_mailbox():
            capabilities["secondary_mailbox"] = (0, 0)

        type = cxl_device_component.get_capability_type()
        if type == CXL_DEVICE_CAPABILITY_TYPE.MEMORY_DEVICE:
            capabilities["memory_device_status"] = (0, 0)
        return capabilities

    @staticmethod
    def get_size_from_options(
        options: Optional[CxlDeviceRegisterOptions] = None,
    ) -> int:
        if not options:
            raise Exception("options is required")

        cxl_device_componet = options["cxl_device_component"]
        size = 0

        capabilities = CxlDeviceRegister.construct_capability_option(cxl_device_componet)
        capability_register_options = CxlDeviceCapabilityRegisterOptions()
        capability_register_options["type"] = cxl_device_componet.get_capability_type()
        capability_register_options["capabilities"] = capabilities
        size += CxlDeviceCapabilityRegister.get_size_from_options(capability_register_options)

        device_status_register_options = DeviceStatusRegistersOptions(
            cxl_device_componet=cxl_device_componet
        )
        size += DeviceStatusRegisters.get_size_from_options(device_status_register_options)
        if cxl_device_componet.get_primary_mailbox():
            mailbox_register_options = MailboxRegisterOptions(
                cxl_mailbox=cxl_device_componet.get_primary_mailbox()
            )
            size += MailboxRegister.get_size_from_options(mailbox_register_options)
        if cxl_device_componet.get_secondary_mailbox():
            mailbox_register_options = MailboxRegisterOptions(
                cxl_mailbox=cxl_device_componet.get_secondary_mailbox()
            )
            size += MailboxRegister.get_size_from_options(mailbox_register_options)
        if cxl_device_componet.get_capability_type() == CXL_DEVICE_CAPABILITY_TYPE.MEMORY_DEVICE:
            if not isinstance(cxl_device_componet, CxlMemoryDeviceComponent):
                raise Exception("device type mismatch")
            cxl_memory_device_component = cast(CxlMemoryDeviceComponent, cxl_device_componet)
            memory_device_status_register_options = MemoryDeviceStatusRegistersOptions(
                cxl_memory_device_component=cxl_memory_device_component
            )
            size += MemoryDeviceStatusRegisters.get_size_from_options(
                memory_device_status_register_options
            )
        return size
