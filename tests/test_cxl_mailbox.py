"""
Copyright (c) 2024, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from opencis.cxl.features.mailbox import (
    CxlMailbox,
    CxlMailboxContext,
    MailboxCapabilities,
    MailboxCommand,
    MailboxControl,
    MAILBOX_RETURN_CODE,
    MAILBOX_TYPE,
    CxlMailboxCommandBase,
)


class SampleCommand(CxlMailboxCommandBase):
    def __init__(self, is_sync: bool):
        super().__init__(0x0000)
        self._is_sync = is_sync

    def process(self, context: CxlMailboxContext) -> bool:
        return self._is_sync


def test_cxl_mailbox_get_capabilities():
    capabilities = MailboxCapabilities(
        payload_size=8,
        mb_doorbell_interrupt_capable=0,
        background_command_complete_interrupt_capable=0,
        interrupt_message_number=0,
        mailbox_ready_time=0,
        type=MAILBOX_TYPE.MEMORY_DEVICE_COMMANDS,
    )

    mailbox = CxlMailbox(capabilities, [])
    assert mailbox.get_capabilities() == capabilities


def test_cxl_mailbox_set_command():
    capabilities = MailboxCapabilities(
        payload_size=8,
        mb_doorbell_interrupt_capable=0,
        background_command_complete_interrupt_capable=0,
        interrupt_message_number=0,
        mailbox_ready_time=0,
        type=MAILBOX_TYPE.MEMORY_DEVICE_COMMANDS,
    )

    mailbox = CxlMailbox(capabilities, [])
    command = MailboxCommand(command_opcode=1, payload_length=1)
    mailbox.set_command(command)
    assert mailbox.command["command_opcode"] == command["command_opcode"]
    assert mailbox.command["payload_length"] == command["payload_length"]
    assert mailbox.command is not command
    assert mailbox.command == command


def test_cxl_mailbox_with_unsupported_command():
    capabilities = MailboxCapabilities(
        payload_size=8,
        mb_doorbell_interrupt_capable=0,
        background_command_complete_interrupt_capable=0,
        interrupt_message_number=0,
        mailbox_ready_time=0,
        type=MAILBOX_TYPE.MEMORY_DEVICE_COMMANDS,
    )

    mailbox = CxlMailbox(capabilities, [])
    assert len(mailbox.payloads) == mailbox.get_payload_size()

    mailbox.set_control(
        MailboxControl(doorbell=1, mb_doorbell_interrupt=0, background_command_complete_interrupt=0)
    )
    control = mailbox.get_control()
    assert control["doorbell"] == 0
    assert mailbox.status["return_code"] == MAILBOX_RETURN_CODE.UNSUPPORTED


def test_cxl_mailbox_with_valid_command():
    capabilities = MailboxCapabilities(
        payload_size=8,
        mb_doorbell_interrupt_capable=0,
        background_command_complete_interrupt_capable=0,
        interrupt_message_number=0,
        mailbox_ready_time=0,
        type=MAILBOX_TYPE.MEMORY_DEVICE_COMMANDS,
    )

    commands = [SampleCommand(True)]
    mailbox = CxlMailbox(capabilities, commands)
    mailbox.set_control(
        MailboxControl(doorbell=1, mb_doorbell_interrupt=0, background_command_complete_interrupt=0)
    )
    assert mailbox.get_control()["doorbell"] == 0
    assert mailbox.status["background_operation"] == 0
    assert mailbox.status["return_code"] == MAILBOX_RETURN_CODE.SUCCESS


def test_cxl_mailbox_with_background_command():
    capabilities = MailboxCapabilities(
        payload_size=8,
        mb_doorbell_interrupt_capable=0,
        background_command_complete_interrupt_capable=0,
        interrupt_message_number=0,
        mailbox_ready_time=0,
        type=MAILBOX_TYPE.MEMORY_DEVICE_COMMANDS,
    )

    commands = [SampleCommand(False)]
    mailbox = CxlMailbox(capabilities, commands)
    mailbox.set_control(
        MailboxControl(doorbell=1, mb_doorbell_interrupt=0, background_command_complete_interrupt=0)
    )
    assert mailbox.get_control()["doorbell"] == 0
    assert mailbox.status["background_operation"] == 1
    assert mailbox.status["return_code"] == MAILBOX_RETURN_CODE.BACKGROUND_COMMAND_STARTED

    mailbox.set_control(
        MailboxControl(doorbell=1, mb_doorbell_interrupt=0, background_command_complete_interrupt=0)
    )
    assert mailbox.get_control()["doorbell"] == 0
    assert mailbox.status["background_operation"] == 1
    assert mailbox.status["return_code"] == MAILBOX_RETURN_CODE.BUSY


def test_cxl_mailbox_enable_interrupt():
    capabilities = MailboxCapabilities(
        payload_size=8,
        mb_doorbell_interrupt_capable=1,
        background_command_complete_interrupt_capable=1,
        interrupt_message_number=0,
        mailbox_ready_time=0,
        type=MAILBOX_TYPE.MEMORY_DEVICE_COMMANDS,
    )

    mailbox = CxlMailbox(capabilities, {})
    mailbox.set_control(
        MailboxControl(doorbell=0, mb_doorbell_interrupt=1, background_command_complete_interrupt=0)
    )
    assert mailbox.get_control()["mb_doorbell_interrupt"] == 1

    mailbox = CxlMailbox(capabilities, {})
    mailbox.set_control(
        MailboxControl(doorbell=0, mb_doorbell_interrupt=0, background_command_complete_interrupt=1)
    )
    assert mailbox.get_control()["background_command_complete_interrupt"] == 1

    capabilities = MailboxCapabilities(
        payload_size=8,
        mb_doorbell_interrupt_capable=0,
        background_command_complete_interrupt_capable=0,
        interrupt_message_number=0,
        mailbox_ready_time=0,
        type=MAILBOX_TYPE.MEMORY_DEVICE_COMMANDS,
    )

    mailbox = CxlMailbox(capabilities, {})
    mailbox.set_control(
        MailboxControl(doorbell=0, mb_doorbell_interrupt=1, background_command_complete_interrupt=0)
    )
    assert mailbox.get_control()["mb_doorbell_interrupt"] == 0

    mailbox = CxlMailbox(capabilities, {})
    mailbox.set_control(
        MailboxControl(doorbell=0, mb_doorbell_interrupt=0, background_command_complete_interrupt=1)
    )
    assert mailbox.get_control()["background_command_complete_interrupt"] == 0
