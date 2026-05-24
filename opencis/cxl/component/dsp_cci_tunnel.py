"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.

DspCciTunnel — Send a CCI command to a GFD over the switch DSP cci_fifo
========================================================================

The switch maintains one `CxlConnection` per DSP port.  Each connection
exposes `cci_fifo: FifoPair` with:

  cci_fifo.host_to_target  — asyncio.Queue the switch writes to; the GFD's
                              CxlPacketProcessor reads from it and forwards to
                              the GFD's CciExecutor.

  cci_fifo.target_to_host  — asyncio.Queue the GFD writes its response to;
                              MctpCciExecutor's _process_outcoming_responses()
                              reads from it.

This class provides a simple `send_and_wait()` coroutine that:
  1. Wraps a CciRequest as a CciMessagePacket and writes it to host_to_target.
  2. Waits for the matching response on target_to_host (matched by message_tag).
  3. Returns the response as a CciResponse.

It is used by:
  - FabricCrawlOutCommand (5701h) — the switch-side command handler
  - GaeManager.start_proxy()      — the GAE proxy mechanism (5809h)

Thread safety: Each concurrent call uses a unique message_tag (0..255 cycling).
The tag namespace is local to this tunnel instance, so concurrent calls from
different tunnels (ports) do not interfere.
"""

import asyncio
from typing import Dict, Optional

from opencis.cxl.component.cci_executor import CciRequest, CciResponse
from opencis.cxl.cci.common import CCI_RETURN_CODE
from opencis.cxl.transport.cci_packets import CciMessagePacket, CciRequestPacket
from opencis.cxl.transport.packet_constants import CCI_MCTP_MESSAGE_CATEGORY
from opencis.pci.component.fifo_pair import FifoPair
from opencis.util.logger import logger

# Default timeout for waiting for a GFD CCI response (seconds)
_DEFAULT_TIMEOUT_S = 5.0


class DspCciTunnel:
    """
    Sends a CCI command to a GFD device over the switch DSP cci_fifo and
    waits for the response.

    Parameters
    ----------
    cci_fifo:
        The `FifoPair` from `CxlConnection.cci_fifo` for the target DSP port.
    port_index:
        The DSP port number (for logging only).
    timeout_s:
        Seconds to wait for a GFD response before giving up.
    """

    def __init__(
        self,
        cci_fifo: FifoPair,
        port_index: int = 0,
        timeout_s: float = _DEFAULT_TIMEOUT_S,
        label: Optional[str] = None,
    ):
        self._cci_fifo = cci_fifo
        self._port_index = port_index
        self._timeout_s = timeout_s
        self._label = label or f"DspCciTunnel:Port{port_index}"
        self._tag: int = 0
        self._tag_lock = asyncio.Lock()
        # Pending response futures keyed by message_tag
        self._pending: Dict[int, asyncio.Future] = {}
        # Background task that drains target_to_host responses
        self._drain_task: Optional[asyncio.Task] = None

    # ------------------------------------------------------------------
    # Lifecycle helpers — call start() once, stop() on teardown
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Launch the background response-drain task."""
        if self._drain_task is None or self._drain_task.done():
            self._drain_task = asyncio.create_task(
                self._drain_responses(), name=f"DspCciTunnel-drain-port{self._port_index}"
            )

    async def stop(self) -> None:
        """Cancel the background drain task."""
        if self._drain_task and not self._drain_task.done():
            self._drain_task.cancel()
            try:
                await self._drain_task
            except asyncio.CancelledError:
                pass

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def send_and_wait(self, request: CciRequest) -> CciResponse:
        """
        Forward a CciRequest to the GFD via `cci_fifo.host_to_target` and
        wait for the matching response from `cci_fifo.target_to_host`.

        Returns a CciResponse.  On timeout returns RETRY_REQUIRED.
        """
        tag = await self._alloc_tag()
        fut: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[tag] = fut

        # Build CCI message packet
        msg = CciMessagePacket.create(
            data=request.payload or b"",
            message_category=CCI_MCTP_MESSAGE_CATEGORY.REQUEST,
            opcode=request.opcode,
            message_tag=tag,
        )

        logger.debug(
            f"[{self._label}] → GFD opcode={request.opcode:#06x} tag={tag}"
        )

        # Write to switch→GFD queue
        await self._cci_fifo.host_to_target.put(msg)

        # Wait for response (with timeout)
        try:
            cci_resp_msg: CciMessagePacket = await asyncio.wait_for(
                fut, timeout=self._timeout_s
            )
        except asyncio.TimeoutError:
            logger.error(
                f"[{self._label}] timeout waiting for GFD response "
                f"(opcode={request.opcode:#06x}, tag={tag})"
            )
            self._pending.pop(tag, None)
            return CciResponse(return_code=CCI_RETURN_CODE.RETRY_REQUIRED)

        rc = CCI_RETURN_CODE(cci_resp_msg.cci_msg_header.return_code)
        payload = cci_resp_msg.get_payload()
        logger.debug(
            f"[{self._label}] ← GFD rc={rc.name} payload_len={len(payload)} tag={tag}"
        )
        return CciResponse(return_code=rc, payload=payload)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _alloc_tag(self) -> int:
        async with self._tag_lock:
            tag = self._tag & 0xFF
            self._tag = (self._tag + 1) & 0xFF
            return tag

    async def _drain_responses(self) -> None:
        """
        Long-running coroutine that reads CCI response packets from
        `cci_fifo.target_to_host` and resolves the matching pending future.

        Note: `target_to_host` carries raw CciRequestPacket / CciResponsePacket
        objects (as put by the GFD's CxlPacketProcessor).  We read the
        CciMessagePacket out of them.
        """
        logger.debug(f"[{self._label}] drain task started")
        while True:
            try:
                packet = await self._cci_fifo.target_to_host.get()
            except asyncio.CancelledError:
                break
            if packet is None:
                break

            # Extract CciMessagePacket — packet may be a CciResponsePacket or
            # a raw CciMessagePacket depending on which side put it.
            try:
                if hasattr(packet, "get_cci_message"):
                    cci_msg: CciMessagePacket = packet.get_cci_message()
                elif isinstance(packet, CciMessagePacket):
                    cci_msg = packet
                else:
                    # Try to get as CciMessagePacket from raw bytes
                    cci_msg = CciMessagePacket(bytearray(bytes(packet)))
            except Exception as exc:
                logger.error(f"[{self._label}] failed to parse response packet: {exc}")
                continue

            tag = cci_msg.cci_msg_header.message_tag
            fut = self._pending.pop(tag, None)
            if fut is not None and not fut.done():
                fut.set_result(cci_msg)
            else:
                logger.warning(
                    f"[{self._label}] received response for unknown/expired tag={tag}"
                )
        logger.debug(f"[{self._label}] drain task stopped")
