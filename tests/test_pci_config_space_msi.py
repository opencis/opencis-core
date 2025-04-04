"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from opencis.pci.config_space.pcie.msi import (
    MsiCapability,
    MsiCapabilityHeader,
    MsiCapabilityOptions,
)


def test_msi_without_options():
    msi = MsiCapability()
    assert len(msi) == msi.get_size_from_options()


def test_msi_with_options():
    options: MsiCapabilityOptions = {"next_capability_offset": 1}
    msi = MsiCapability(options=options)
    assert len(msi) == msi.get_size_from_options(options)
    assert msi.capability_header.next_capability_offset == 1


def test_msi_cap_header_without_options():
    msi_cap_header = MsiCapabilityHeader()
    assert len(msi_cap_header) == msi_cap_header.get_size_from_options()
