"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from unittest.mock import MagicMock
import pytest

from opencis.pci.config_space.pci import (
    PciConfigSpaceClassCode,
    PciConfigSpaceType0,
    PciConfigSpaceOptions,
    PCI_CONFIG_SPACE_HEADER_SIZE,
)
from opencis.pci.component.mmio_manager import BarInfo
from opencis.pci.component.pci import PciComponent, PciComponentIdentity


def test_pci_config_space_class_code():
    with pytest.raises(Exception) as exception_info:
        PciConfigSpaceClassCode()

    assert str(exception_info.value) == "options is required"


def test_pci_config_space_type0():
    mmio_manager = MagicMock()
    identity = PciComponentIdentity(
        vendor_id=0x1234,
        device_id=0x5678,
        base_class_code=1,
        sub_class_coce=2,
        programming_interface=3,
        subsystem_vendor_id=4,
        subsystem_id=5,
    )

    pci_component = PciComponent(identity=identity, mmio_manager=mmio_manager)
    get_bar_size = MagicMock()
    get_bar_size.side_effect = [0x1000, 0, 0, 0, 0, 0]
    mmio_manager.get_bar_size = get_bar_size
    get_bar_info = MagicMock()
    get_bar_info.side_effect = [BarInfo(), None, None, None, None, None]
    mmio_manager.get_bar_info = get_bar_info

    options = PciConfigSpaceOptions(capability_pointer=0x40, pci_component=pci_component)
    register = PciConfigSpaceType0(options=options)
    assert register.vendor_id == 0x1234
    assert register.device_id == 0x5678

    options = PciConfigSpaceOptions(capability_pointer=0x40)
    register = PciConfigSpaceType0(options=options)
    assert register.vendor_id == 0
    assert register.device_id == 0

    expected_size = PciConfigSpaceType0.get_size_from_options(options)
    assert expected_size == PCI_CONFIG_SPACE_HEADER_SIZE
