"""
Copyright (c) 2024, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from unittest.mock import MagicMock

from opencis.cxl.mmio.device_register.mailbox_register import (
    MailboxRegister,
    MailboxRegisterOptions,
    MIN_PAYLOAD_SIZE,
)
from opencis.cxl.mmio.device_register.device_capabilities import (
    CxlDeviceCapabilityRegister,
    CxlDeviceCapabilityRegisterOptions,
    CXL_DEVICE_CAPABILITY_TYPE,
)
from opencis.cxl.mmio.device_register.device_status_register import (
    DeviceStatusRegisters,
    DeviceStatusRegistersOptions,
    EventStatus,
)
from opencis.cxl.mmio.device_register.memory_device_capabilities import (
    MemoryDeviceStatusRegisters,
    MemoryDeviceStatusRegistersOptions,
    MemoryDeviceStatus,
    MEDIA_STATUS,
    RESET_REQUEST,
)
from opencis.cxl.mmio.device_register import CxlDeviceRegisterOptions
from opencis.cxl.features.mailbox import (
    MailboxCapabilities,
    MailboxStatus,
    MailboxBackgroundCommandStatus,
)
from opencis.cxl.component.cxl_memory_device_component import (
    CxlMemoryDeviceComponent,
    MemoryDeviceIdentity,
)


def test_cxl_mailbox_register():
    register = MailboxRegister()
    assert len(register) == MailboxRegister.get_size_from_options()


def test_cxl_mailbox_capabilities_register():
    register = MailboxRegister()
    assert len(register) == MailboxRegister.get_size_from_options()
    assert register.read_bytes(0x00, 0x03) == MIN_PAYLOAD_SIZE
    assert register.capabilities.payload_size == MIN_PAYLOAD_SIZE

    mailbox = MagicMock()
    mailbox.get_capabilities.return_value = MailboxCapabilities(
        payload_size=MIN_PAYLOAD_SIZE + 1,
        mb_doorbell_interrupt_capable=0,
        background_command_complete_interrupt_capable=0,
        interrupt_message_number=0,
        mailbox_ready_time=0,
    )
    options = MailboxRegisterOptions(cxl_mailbox=mailbox)
    register = MailboxRegister(options=options)
    assert len(register) == MailboxRegister.get_size_from_options(options)
    assert register.read_bytes(0x00, 0x03) == (MIN_PAYLOAD_SIZE + 1)
    assert register.capabilities.payload_size == MIN_PAYLOAD_SIZE + 1


def test_cxl_mailbox_control_register():
    mailbox = MagicMock()
    mailbox.get_capabilities.return_value = MailboxCapabilities(
        payload_size=MIN_PAYLOAD_SIZE,
        mb_doorbell_interrupt_capable=0,
        background_command_complete_interrupt_capable=0,
        interrupt_message_number=0,
        mailbox_ready_time=0,
    )
    options = MailboxRegisterOptions(cxl_mailbox=mailbox)
    register = MailboxRegister(options=options)
    assert len(register) == MailboxRegister.get_size_from_options(options)
    register.write_bytes(0x04, 0x07, 0x01)
    mailbox.set_control.assert_called()

    # Read register.control.doorbell
    assert register.read_bytes(0x04, 0x07) == 0x01
    assert register.read_bytes(0x04, 0x07) == register.control.doorbell


def test_cxl_mailbox_command_register():
    mailbox = MagicMock()
    mailbox.get_capabilities = MagicMock()
    mailbox.get_capabilities.return_value = MailboxCapabilities(
        payload_size=MIN_PAYLOAD_SIZE,
        mb_doorbell_interrupt_capable=0,
        background_command_complete_interrupt_capable=0,
        interrupt_message_number=0,
        mailbox_ready_time=0,
    )
    options = MailboxRegisterOptions(cxl_mailbox=mailbox)
    register = MailboxRegister(options=options)
    assert len(register) == MailboxRegister.get_size_from_options(options)
    mailbox.get_capabilities.assert_called()

    register.write_bytes(0x08, 0x0F, 0x201234)
    mailbox.set_command.assert_called()
    assert register.read_bytes(0x08, 0x0F) == 0x201234
    assert register.read_bytes(0x08, 0x09) == register.command.command_opcode
    assert register.read_bytes(0x0A, 0x0F) == register.command.payload_length


def test_cxl_mailbox_status_register():
    mailbox = MagicMock()
    mailbox.get_capabilities.return_value = MailboxCapabilities(
        payload_size=MIN_PAYLOAD_SIZE,
        mb_doorbell_interrupt_capable=0,
        background_command_complete_interrupt_capable=0,
        interrupt_message_number=0,
        mailbox_ready_time=0,
    )
    options = MailboxRegisterOptions(cxl_mailbox=mailbox)
    register = MailboxRegister(options=options)
    assert len(register) == MailboxRegister.get_size_from_options(options)
    mailbox.get_capabilities.assert_called()

    assert register.read_bytes(0x10, 0x17) == 0
    mailbox.status = MailboxStatus(
        background_operation=1, return_code=1, vendor_specific_extended_status=1
    )
    assert register.read_bytes(0x10, 0x17) == 0x0001000100000001
    assert register.read_bytes(0x10, 0x13) == register.status.background_operation
    assert register.read_bytes(0x14, 0x15) == register.status.return_code
    assert register.read_bytes(0x16, 0x17) == register.status.vendor_specific_extended_status


def test_cxl_mailbox_background_command_status_register():
    mailbox = MagicMock()
    mailbox.get_capabilities.return_value = MailboxCapabilities(
        payload_size=MIN_PAYLOAD_SIZE,
        mb_doorbell_interrupt_capable=0,
        background_command_complete_interrupt_capable=0,
        interrupt_message_number=0,
        mailbox_ready_time=0,
    )
    options = MailboxRegisterOptions(cxl_mailbox=mailbox)
    register = MailboxRegister(options=options)
    assert len(register) == MailboxRegister.get_size_from_options(options)
    mailbox.get_capabilities.assert_called()

    # Read test #1
    assert register.read_bytes(0x18, 0x1F) == 0

    # Read test #2: after setting background_command_status
    mailbox.background_command_status = MailboxBackgroundCommandStatus(
        command_opcode=1,
        percentage_complete=1,
        return_code=1,
        vendor_specific_extended_status=1,
    )
    assert register.read_bytes(0x18, 0x1F) == 0x0001000100010001
    assert register.read_bytes(0x18, 0x19) == register.background_command_status.command_opcode
    assert register.read_bytes(0x1A, 0x1B) == register.background_command_status.percentage_complete
    assert register.read_bytes(0x1C, 0x1D) == register.background_command_status.return_code
    assert (
        register.read_bytes(0x1E, 0x1F)
        == register.background_command_status.vendor_specific_extended_status
    )


def test_cxl_mailbox_command_payloads_register():
    mailbox = MagicMock()
    mailbox.get_capabilities.return_value = MailboxCapabilities(
        payload_size=MIN_PAYLOAD_SIZE,
        mb_doorbell_interrupt_capable=0,
        background_command_complete_interrupt_capable=0,
        interrupt_message_number=0,
        mailbox_ready_time=0,
    )
    options = MailboxRegisterOptions(cxl_mailbox=mailbox)
    register = MailboxRegister(options=options)
    assert len(register) == MailboxRegister.get_size_from_options(options)
    mailbox.get_capabilities.assert_called()
    mailbox.payloads.read_bytes.return_value = 0

    # test read_bytes
    assert register.read_bytes(0x20, len(register) - 1) == 0
    mailbox.payloads.read_bytes.assert_called()

    # test write_bytes
    register.write_bytes(0x20, 0x23, 1)
    mailbox.payloads.write_bytes.assert_called()

    # test read_bytes when cxl_mailbox is not provided
    register = MailboxRegister()
    register.write_bytes(0x20, 0x23, 1)
    assert register.read_bytes(0x20, 0x23) == 1


def test_device_capability_register():
    options = CxlDeviceCapabilityRegisterOptions(
        type=CXL_DEVICE_CAPABILITY_TYPE.MEMORY_DEVICE,
        capabilities={"primary_mailbox": (0x100, 0x10), "device_status": (0x110, 0x10)},
    )
    capability = CxlDeviceCapabilityRegister(options=options)
    expected_len = CxlDeviceCapabilityRegister.get_size_from_options(options)
    assert len(capability) == expected_len
    assert capability.capabilities_array.capabilities_count == 2


def test_device_status_register():
    cxl_device_component = MagicMock()
    event_manager = MagicMock()
    cxl_device_component.get_event_manager.return_value = event_manager
    event_manager.get_status.return_value = EventStatus(
        informational_event_log=0,
        warning_event_log=1,
        failure_event_log=0,
        fatal_event_log=1,
        dynamic_capacity_event_log=0,
    )
    options = DeviceStatusRegistersOptions(cxl_device_component=cxl_device_component)
    expected_len = DeviceStatusRegisters.get_size_from_options(options)
    register = DeviceStatusRegisters(options=options)
    assert expected_len == len(register)
    register.read_bytes(0, 8)
    assert register.event_status.informational_event_log == 0
    assert register.event_status.warning_event_log == 1
    assert register.event_status.failure_event_log == 0
    assert register.event_status.fatal_event_log == 1
    assert register.event_status.dynamic_capacity_event_log == 0


def test_memory_device_register():
    cxl_memory_device_component = MagicMock()
    cxl_memory_device_component.get_status.return_value = MemoryDeviceStatus(
        device_fatal=1,
        fw_halt=0,
        media_status=MEDIA_STATUS.ERROR,
        mailbox_interfaces_ready=1,
        reset_needed=RESET_REQUEST.NOT_NEEDED,
    )
    options = MemoryDeviceStatusRegistersOptions(
        cxl_memory_device_component=cxl_memory_device_component
    )
    expected_len = MemoryDeviceStatusRegisters.get_size_from_options(options)
    register = MemoryDeviceStatusRegisters(options=options)
    assert len(register) == expected_len
    register.read_bytes(0, 8)
    assert register.status.device_fatal == 1
    assert register.status.fw_halt == 0
    assert register.status.media_status == MEDIA_STATUS.ERROR
    assert register.status.mailbox_interfaces_ready == 1
    assert register.status.reset_needed == RESET_REQUEST.NOT_NEEDED


def test_device_register():
    identity = MemoryDeviceIdentity()
    identity.fw_revision = MemoryDeviceIdentity.ascii_str_to_int("EEUM EMU 1.0", 16)
    identity.total_capacity = 256 * 1024 * 1024
    identity.volatile_only_capacity = 256 * 1024 * 1024
    identity.persistent_only_capacity = 0
    identity.partition_alignment = 0
    cxl_memory_device_component = CxlMemoryDeviceComponent(identity)
    CxlDeviceRegisterOptions(cxl_device_component=cxl_memory_device_component)
