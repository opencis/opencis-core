"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from opencis.cxl.features.mailbox import (
    CxlMailboxContext,
    CxlMailboxCommandBase,
    MAILBOX_RETURN_CODE,
)
from opencis.util.unaligned_bit_structure import ShareableByteArray


class GetSecurityState(CxlMailboxCommandBase):
    """Get Security State (Opcode 4500h)

    Spec description (for reference): Retrieves the persistent memory security state.
    Output payload (on success): 4-byte bitfield, but this implementation always
    returns Unsupported (all-zeroes).
    """

    def __init__(self):
        super().__init__(0x4500)

    def process(self, context: CxlMailboxContext) -> bool:
        # Return SUCCESS with a 4-byte security state payload.
        # For now, report all zeros (no passphrases set, not locked/frozen, etc.).
        context.status["return_code"] = MAILBOX_RETURN_CODE.SUCCESS
        security_state = (0).to_bytes(4, "little")

        sba = ShareableByteArray(len(security_state), bytearray(security_state))
        context.payloads.copy_from(sba)
        context.command["payload_length"] = len(security_state)
        return True
