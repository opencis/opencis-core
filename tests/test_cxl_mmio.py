"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from opencis.cxl.mmio import CombinedMmioRegister, CombinedMmioRegiterOptions
from opencis.cxl.component.cxl_memory_device_component import (
    CxlMemoryDeviceComponent,
    MemoryDeviceIdentity,
)


def test_mmio_register_with_cxl_memory_device_component():
    # pylint: disable=duplicate-code
    # CE-94
    identity = MemoryDeviceIdentity()
    identity.fw_revision = MemoryDeviceIdentity.ascii_str_to_int("EEUM EMU 1.0", 16)
    identity.total_capacity = 256 * 1024 * 1024
    identity.volatile_only_capacity = 256 * 1024 * 1024
    identity.persistent_only_capacity = 0
    identity.partition_alignment = 0
    cxl_component = CxlMemoryDeviceComponent(identity)
    options = CombinedMmioRegiterOptions(cxl_component=cxl_component)
    register = CombinedMmioRegister(options=options)
    len_expected = CombinedMmioRegister.get_size_from_options(options)
    assert len_expected == len(register)
