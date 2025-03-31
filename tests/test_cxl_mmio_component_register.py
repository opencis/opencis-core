"""
Copyright (c) 2024, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from opencis.cxl.mmio.component_register import (
    CxlComponentRegister,
    CxlComponentRegisterOptions,
)
from opencis.cxl.component.cxl_memory_device_component import (
    CxlMemoryDeviceComponent,
    MemoryDeviceIdentity,
)


def test_cxl_component_register():
    # pylint: disable=duplicate-code
    identity = MemoryDeviceIdentity()
    identity.fw_revision = MemoryDeviceIdentity.ascii_str_to_int("EEUM EMU 1.0", 16)
    identity.total_capacity = 256 * 1024 * 1024
    identity.volatile_only_capacity = 256 * 1024 * 1024
    identity.persistent_only_capacity = 0
    identity.partition_alignment = 0
    cxl_memory_device_component = CxlMemoryDeviceComponent(identity)
    options = CxlComponentRegisterOptions(cxl_component=cxl_memory_device_component)
    CxlComponentRegister(options=options)
