"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from enum import IntEnum
from abc import ABC, abstractmethod
from typing import Dict, TypedDict, List
from dataclasses import dataclass, field

from opencis.util.unaligned_bit_structure import ShareableByteArray
from opencis.util.logger import logger

MIN_PAYLOAD_SIZE = 8  # 256


class MAILBOX_TYPE(IntEnum):
    INFER_PCI_CLASS_CODE = 0
    MEMORY_DEVICE_COMMANDS = 1
    FM_API_COMMANDS = 2


class MailboxCapabilities(TypedDict):
    # pylint: disable=duplicate-code
    payload_size: int
    mb_doorbell_interrupt_capable: int
    background_command_complete_interrupt_capable: int
    interrupt_message_number: int
    mailbox_ready_time: int
    type: MAILBOX_TYPE


class MailboxControl(TypedDict):
    doorbell: int
    mb_doorbell_interrupt: int
    background_command_complete_interrupt: int


class MailboxCommand(TypedDict):
    command_opcode: int
    payload_length: int


class MailboxStatus(TypedDict):
    background_operation: int
    return_code: int
    vendor_specific_extended_status: int


class MailboxBackgroundCommandStatus(TypedDict):
    command_opcode: int
    percentage_complete: int
    return_code: int
    vendor_specific_extended_status: int


class MAILBOX_RETURN_CODE(IntEnum):
    SUCCESS = 0x0000
    BACKGROUND_COMMAND_STARTED = 0x0001
    INVALID_INPUT = 0x0002
    UNSUPPORTED = 0x0003
    INTERNAL_ERROR = 0x0004
    RETRY_REQUIRED = 0x0005
    BUSY = 0x0006
    MEDIA_DISABLED = 0x0007
    FW_TRANSFER_IN_PROGRESS = 0x0008
    FW_TRANSFER_OUT_OF_ORDER = 0x0009
    FW_VERIFICATION_FAILED = 0x000A
    INVALID_SLOT = 0x000B
    ACTIVATION_FAILED_FW_ROLLED_BACK = 0x000C
    ACTIVATION_FAILED_COLD_RESET_REQUIRED = 0x000D
    INVALID_HANDLE = 0x000E
    INVALID_PHYSICAL_ADDRESS = 0x000F
    INJECT_POSITION_LIMIT_REACHED = 0x0010
    PERMANENT_MEDIA_FAILURE = 0x0011
    ABORTED = 0x0012
    INVALID_SECURITY_STATE = 0x0013
    INCORRECT_PASSPHRASE = 0x0014
    UNSUPPORTED_MAILBOX_OR_CCI = 0x0015
    INVALID_PAYLOAD_LENGTH = 0x0016
    INVALID_LOG = 0x0017
    INTERRUPTED = 0x0018
    UNSUPPORTED_FEATURE_VERSION = 0x0019
    UNSUPPORTED_FEATURE_SELECTION_VALUE = 0x001A
    FEATURE_TRANSFER_IN_PROGRESS = 0x001B
    FEATURE_TRANSFER_OUT_OF_ORDER = 0x001C
    RESOURCES_EXHAUSTED = 0x001D
    INVALID_EXTENT_LIST = 0x001E


@dataclass
class CxlMailboxContext:
    command: MailboxCommand = field(default_factory=dict)
    control: MailboxControl = field(default_factory=dict)
    status: MailboxStatus = field(default_factory=dict)
    payloads: ShareableByteArray = field(default_factory=ShareableByteArray)


class CxlMailboxCommandBase(ABC):
    def __init__(self, opcode: int):
        self._opcode = opcode

    @abstractmethod
    def process(self, context: CxlMailboxContext) -> bool:
        """this is an abastrct class"""

    def get_opcode(self) -> int:
        return self._opcode


CxlMailboxCommands = Dict[int, CxlMailboxCommandBase]


class CxlMailbox:
    payloads: ShareableByteArray
    capabilities: MailboxCapabilities
    control: MailboxControl
    status: MailboxStatus
    commands: CxlMailboxCommands
    background_command_status: MailboxBackgroundCommandStatus

    def __init__(self, capabilities: MailboxCapabilities, commands: List[CxlMailboxCommandBase]):
        self.capabilities = capabilities
        self.commands: CxlMailboxCommands = {}
        for command in commands:
            self.commands[command.get_opcode()] = command

        self.command = MailboxCommand(command_opcode=0, payload_length=0)
        self._control = MailboxControl(
            doorbell=0,
            mb_doorbell_interrupt=0,
            background_command_complete_interrupt=0,
        )
        self.status = MailboxStatus(
            background_operation=0, return_code=0, vendor_specific_extended_status=0
        )
        self.background_command_status = MailboxBackgroundCommandStatus(
            command_opcode=0,
            percentage_complete=0,
            return_code=0,
            vendor_specific_extended_status=0,
        )
        self.payloads = ShareableByteArray(self.get_payload_size())

    def process_command(self):
        command_opcode = self.command["command_opcode"]
        if command_opcode not in self.commands:
            logger.info(f"[CCI] Unsupported Command Opcode 0x{command_opcode:04x}")
            self.status["return_code"] = MAILBOX_RETURN_CODE.UNSUPPORTED
            return

        payload_length = self.command["payload_length"]
        max_payload_size = self.get_payload_size()
        if payload_length > max_payload_size:
            logger.info(
                f"[CCI] Command payload length exceeds allowed maximum payload length, "
                f"{max_payload_size}"
            )
            self.status["return_code"] = MAILBOX_RETURN_CODE.INVALID_PAYLOAD_LENGTH
            return

        if self.status["background_operation"] == 1:
            logger.info("[CCI] Mailbox Busy")
            self.status["return_code"] = MAILBOX_RETURN_CODE.BUSY
            return

        command_processor = self.commands[command_opcode]

        context = CxlMailboxContext(
            command=self.command,
            control=self._control,
            status=self.status,
            payloads=self.payloads,
        )

        # NOTE: background commands are not supported. All commands will block
        # until completed
        self._control["doorbell"] = 1
        self.status["return_code"] = MAILBOX_RETURN_CODE.SUCCESS

        command_name = command_processor.__class__.__name__
        logger.info(f"[CCI] Executing {command_name} command")
        completed = command_processor.process(context)
        self._control["doorbell"] = 0
        if completed:
            if self.status["return_code"] == MAILBOX_RETURN_CODE.SUCCESS:
                logger.info(f"[CCI] Completed {command_name} command successfully")
            else:
                return_code_str = MAILBOX_RETURN_CODE(self.status["return_code"])
                logger.info(f"[CCI] Command {command_name} failed. Return Code: {return_code_str}")
            self.generate_doorbell_interrupt()
        else:
            # NOTE: when not completed, assume the command is running in a
            # separate thread. Use synchronization primitives such as mutex
            # to prevent race conditions
            self.status["return_code"] = MAILBOX_RETURN_CODE.BACKGROUND_COMMAND_STARTED
            self.status["background_operation"] = 1

    def get_payload_size(self) -> int:
        return 1 << self.capabilities["payload_size"]

    def generate_doorbell_interrupt(self):
        if self._control["doorbell"] == 0:
            return

        # TODO: generate MSI or MSIX interrupt

    def enable_mb_doorbell_interrupt(self):
        if not self.capabilities["mb_doorbell_interrupt_capable"]:
            return
        self._control["mb_doorbell_interrupt"] = 1

    def enable_background_command_complete_interrupt(self):
        if not self.capabilities["background_command_complete_interrupt_capable"]:
            return
        self._control["background_command_complete_interrupt"] = 1

    def get_capabilities(self) -> MailboxCapabilities:
        return self.capabilities

    def set_control(self, control: MailboxControl):
        if self._control["doorbell"] == 0 and control["doorbell"] == 1:
            self.process_command()
        if self._control["doorbell"] == 0:
            if (
                self._control["mb_doorbell_interrupt"] == 0
                and control["mb_doorbell_interrupt"] == 1
            ):
                self.enable_mb_doorbell_interrupt()
            if (
                self._control["background_command_complete_interrupt"] == 0
                and control["background_command_complete_interrupt"] == 1
            ):
                self.enable_background_command_complete_interrupt()

    def get_control(self) -> MailboxControl:
        return self._control

    def set_command(self, command: MailboxCommand):
        for key, value in command.items():
            self.command[key] = value
