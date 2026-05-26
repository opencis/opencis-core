"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.

PbrCommandService — Shared switch programming service for FM ports
==================================================================

Single authoritative service that routes PBR write CCI commands to the
physical switch via MctpCciApiClient.

Shared by:
  - FmMctpCciServer (port 8300, MCTP-over-TCP)
      calls  pbr_service.forward(opcode, raw_bytes)
  - FabricManagerSocketIoServer (port 8200, Socket.IO CLI)
      calls  pbr_service.configure_pid_assignment / set_drt / configure_pid_binding

Keeping the switch call in one place means:
  - No duplicated opcode routing
  - Single connection-health check (is_connected)
  - Single log source for switch mirroring
"""

from typing import Optional, TYPE_CHECKING

from opencis.util.logger import logger
from opencis.cxl.cci.common import CCI_FM_API_COMMAND_OPCODE
from opencis.cxl.cci.fabric_manager.pbr_switch import (
    ConfigurePidAssignmentRequestPayload,
    ConfigurePidBindingRequestPayload,
    SetDrtRequestPayload,
)

if TYPE_CHECKING:
    from opencis.cxl.component.mctp.mctp_cci_api_client import MctpCciApiClient


class PbrCommandService:
    """
    Thin service that wraps MctpCciApiClient PBR write methods.

    Instantiated once by CxlFabricManager and injected into both FM ports
    so they share the same switch-programming path.
    """

    def __init__(
        self,
        api_client: "MctpCciApiClient",
        label: str = "PbrCommandService",
    ):
        self._api_client = api_client
        self._label = label

    # ------------------------------------------------------------------
    # Connection health
    # ------------------------------------------------------------------

    def is_connected(self) -> bool:
        """Return True when the switch-side MCTP client is running."""
        from opencis.util.component import COMPONENT_STATUS
        return (
            self._api_client is not None
            and self._api_client._status == COMPONENT_STATUS.RUNNING
        )

    # ------------------------------------------------------------------
    # Port 8300 entry point — routes raw opcode + bytes to switch
    # ------------------------------------------------------------------

    async def forward(self, opcode: int, payload: bytes) -> None:
        """
        Route a raw CCI write opcode to the physical switch.

        Called by FmMctpCciServer after local FM execution succeeds.

        Only the three write opcodes are forwarded:
          0x5704  ConfigurePidAssignment
          0x5706  ConfigurePidBinding
          0x5709  SetDrt

        Read-only opcodes (0x5700 Identify, 0x5705 GetPidBinding,
        0x5708 GetDrt) fall through silently — they read FM state only.

        Graceful degradation: if the switch is offline a warning is
        logged and control returns; FM state is already committed.
        """
        if self._api_client is None:
            return

        if not self.is_connected():
            logger.warning(
                f"[{self._label}] Switch not connected; "
                f"skipping mirror for opcode {opcode:#06x}. FM state was updated."
            )
            return

        try:
            if opcode == CCI_FM_API_COMMAND_OPCODE.CONFIGURE_PID_ASSIGNMENT:
                await self.configure_pid_assignment(
                    ConfigurePidAssignmentRequestPayload.parse(payload)
                )

            elif opcode == CCI_FM_API_COMMAND_OPCODE.SET_DRT:
                await self.set_drt(SetDrtRequestPayload.parse(payload))

            elif opcode == CCI_FM_API_COMMAND_OPCODE.CONFIGURE_PID_BINDING:
                await self.configure_pid_binding(
                    ConfigurePidBindingRequestPayload.parse(payload)
                )
            # 0x5700 / 0x5705 / 0x5708 — read-only, no switch action

        except Exception as exc:
            # Non-fatal: FM state is already committed; log and continue
            logger.warning(
                f"[{self._label}] Failed to mirror opcode {opcode:#06x} "
                f"to switch: {exc}"
            )

    # ------------------------------------------------------------------
    # Port 8200 / direct call entry points
    # Also used by forward() above after payload parsing
    # ------------------------------------------------------------------

    async def configure_pid_assignment(
        self, payload: ConfigurePidAssignmentRequestPayload
    ):
        """Send ConfigurePidAssignment (0x5704) to the physical switch."""
        result = await self._api_client.configure_pid_assignment(payload)
        logger.debug(f"[{self._label}] Mirrored CONFIGURE_PID_ASSIGNMENT to switch")
        return result

    async def set_drt(self, payload: SetDrtRequestPayload):
        """Send SetDrt (0x5709) to the physical switch."""
        result = await self._api_client.set_drt(payload)
        logger.debug(f"[{self._label}] Mirrored SET_DRT to switch")
        return result

    async def configure_pid_binding(
        self, payload: ConfigurePidBindingRequestPayload
    ):
        """Send ConfigurePidBinding (0x5706) to the physical switch."""
        result = await self._api_client.configure_pid_binding(payload)
        logger.debug(f"[{self._label}] Mirrored CONFIGURE_PID_BINDING to switch")
        return result
