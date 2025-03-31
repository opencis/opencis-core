"""
Copyright (c) 2024, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from opencis.cxl.features.mailbox import (
    CxlMailboxContext,
    CxlMailboxCommandBase,
    MAILBOX_RETURN_CODE,
)
from opencis.util.unaligned_bit_structure import UnalignedBitStructure

#
#   IdentifyMemoryDevice command (Opcode 4000h)
#


class IdentifyMemoryDevice(CxlMailboxCommandBase):
    identity: UnalignedBitStructure

    def __init__(self, identity: UnalignedBitStructure):
        super().__init__(0x4000)
        self.identity = identity

    def process(self, context: CxlMailboxContext) -> bool:
        if context.command["payload_length"] != 0:
            context.status["return_code"] = MAILBOX_RETURN_CODE.INVALID_INPUT
            return True

        context.payloads.copy_from(self.identity)
        context.command["payload_length"] = len(self.identity)
        return True
