"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.

GaeManager — Global Memory Access Endpoint state owner
======================================================

A GaeManager is created once per PBR switch and injected into every GAE CCI
command handler.  It tracks:

  - The list of vPPBs that have (optional) G-FAM support
  - Active proxy threads (asyncio tasks) spawned by Proxy GFD Mgmt Cmd (5809h)
  - A reference to the GFD's CciExecutor (set when the GFD connects)

For a **simple-device GFD** (no G-FAM, no FAST decoders):
  - num_vppbs  = 0  (no G-FAM vPPBs)
  - The proxy mechanism works the same — the host can still issue CCI
    commands to the GFD via the proxy path.

Architecture
------------
The GAE itself is part of the switch Host-Edge USP.  We implement its command
handlers as CciForegroundCommands registered on the switch-side CciExecutor
(via McpCciExecutor or FmMctpCciServer), exactly like the PBR switch commands.

The GFD's CciExecutor is injected via `set_gfd_executor()` once the GFD
connects to the switch.  Proxy commands are forwarded directly to that executor
via asyncio.  This avoids the need for a separate TCP hop.

CXL 4.0 §7.7.14 references
---------------------------
  5800h  Identify GAE          — §7.7.14.1
  5801h  Get PID Interrupt Vec — §7.7.14.2  (optional, not implemented here)
  5802h  Get PID Access Vecs  — §7.7.14.3
  5803h  Get FAST/IDT Caps    — §7.7.14.4  (optional, returns UNSUPPORTED)
  5809h  Proxy GFD Mgmt Cmd   — §7.7.14.10
  580Ah  Get Proxy Thread Sts  — §7.7.14.11
  580Bh  Cancel Proxy Thread  — §7.7.14.12
"""

import asyncio
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from opencis.cxl.component.cci_executor import CciExecutor, CciRequest, CciResponse
from opencis.cxl.cci.common import CCI_RETURN_CODE
from opencis.util.logger import logger

# Imported lazily to avoid circular imports in unit tests
# DspCciTunnel is optional — used only when the real switch transport is available.
_DspCciTunnel = None


def _get_tunnel_class():
    global _DspCciTunnel  # pylint: disable=global-statement
    if _DspCciTunnel is None:
        from opencis.cxl.component.dsp_cci_tunnel import DspCciTunnel  # pylint: disable=import-outside-toplevel
        _DspCciTunnel = DspCciTunnel
    return _DspCciTunnel


# ---------------------------------------------------------------------------
# GAE vPPB Info entry
# ---------------------------------------------------------------------------


@dataclass
class GaeVppbInfo:
    """
    One entry describing a vPPB that is connected to the GAE.

    For a simple-device GFD this list is empty (no G-FAM vPPBs).
    """
    vppb_id: int = 0
    global_memory_support: bool = False   # G-FAM capable
    pid: int = 0xFFF                      # PID_UNASSIGNED until FM assigns


# ---------------------------------------------------------------------------
# Proxy thread registry entry
# ---------------------------------------------------------------------------


@dataclass
class ProxyThreadEntry:
    """Runtime record for one active proxy thread."""
    thread_id: int
    gfd_opcode: int
    task: Optional[asyncio.Task] = field(default=None, repr=False)
    response: Optional[CciResponse] = field(default=None)
    completed: bool = False
    return_code: int = int(CCI_RETURN_CODE.SUCCESS)


# ---------------------------------------------------------------------------
# GaeManager
# ---------------------------------------------------------------------------


class GaeManager:
    """
    Central state owner for the GAE on one PBR switch.

    Parameters
    ----------
    vppbs:
        Initial vPPB list.  Empty for a simple-device GFD.
    label:
        Optional log prefix.
    """

    def __init__(
        self,
        vppbs: Optional[List[GaeVppbInfo]] = None,
        label: Optional[str] = None,
    ):
        self._label = label or "GaeManager"
        self._vppbs: List[GaeVppbInfo] = vppbs or []
        # GFD binding — one of these two is set, tunnel takes priority
        self._gfd_tunnel = None              # DspCciTunnel (production path)
        self._gfd_executor: Optional[CciExecutor] = None  # in-process (tests)
        # Active proxy threads indexed by thread_id
        self._proxy_threads: Dict[int, ProxyThreadEntry] = {}
        self._next_thread_id: int = 1

    # ------------------------------------------------------------------
    # GFD binding — TWO modes:
    #   1. Tunnel mode (production): via DspCciTunnel over the switch cci_fifo
    #   2. Executor mode (unit tests): direct in-process CciExecutor call
    # ------------------------------------------------------------------

    def set_gfd_tunnel(self, tunnel) -> None:
        """
        Bind a DspCciTunnel so proxy commands are forwarded over the real
        switch DSP cci_fifo.  This is the production (spec-correct) path.

        Call this from MctpCciExecutor after the DspCciTunnel is started.
        """
        self._gfd_tunnel = tunnel
        self._gfd_executor = None   # tunnel takes precedence
        logger.debug(f"[{self._label}] GFD DSP CCI tunnel bound (port {getattr(tunnel, '_port_index', '?')})")

    def set_gfd_executor(self, executor: CciExecutor) -> None:
        """
        Bind the GFD's CciExecutor directly (in-process fallback for tests).
        Only used when no DspCciTunnel has been configured.
        """
        self._gfd_executor = executor
        logger.debug(f"[{self._label}] GFD executor bound (in-process mode)")

    def get_gfd_executor(self) -> Optional[CciExecutor]:
        return self._gfd_executor

    # ------------------------------------------------------------------
    # vPPB list access (for Identify GAE / Get PID Access Vectors)
    # ------------------------------------------------------------------

    def get_vppb_count(self) -> int:
        return len(self._vppbs)

    def get_vppbs(self) -> List[GaeVppbInfo]:
        return list(self._vppbs)

    # ------------------------------------------------------------------
    # Proxy thread management (for 5809h / 580Ah / 580Bh)
    # ------------------------------------------------------------------

    def _alloc_thread_id(self) -> int:
        tid = self._next_thread_id
        self._next_thread_id += 1
        return tid

    async def start_proxy(
        self,
        gfd_opcode: int,
        gfd_request_payload: bytes,
    ) -> int:
        """
        Spawn an async proxy thread to forward a CCI command to the GFD.

        Uses DspCciTunnel (production) if bound, else falls back to direct
        CciExecutor call (unit-test mode).

        Returns the assigned thread_id (used by Get/Cancel Proxy Thread).
        """
        has_tunnel = self._gfd_tunnel is not None
        has_executor = self._gfd_executor is not None

        if not has_tunnel and not has_executor:
            logger.error(f"[{self._label}] start_proxy: no GFD tunnel or executor bound")
            return 0

        tid = self._alloc_thread_id()
        entry = ProxyThreadEntry(thread_id=tid, gfd_opcode=gfd_opcode)
        self._proxy_threads[tid] = entry

        async def _run() -> None:
            req = CciRequest(opcode=gfd_opcode, payload=gfd_request_payload)
            try:
                if has_tunnel:
                    # Spec-correct path: go through switch cci_fifo
                    resp = await self._gfd_tunnel.send_and_wait(req)
                else:
                    # Fallback: direct in-process call (unit tests)
                    resp = await self._gfd_executor.execute_command(req)
                entry.response = resp
                entry.return_code = int(resp.return_code)
            except Exception as exc:
                logger.error(f"[{self._label}] proxy thread {tid} error: {exc}")
                entry.return_code = int(CCI_RETURN_CODE.INTERNAL_ERROR)
            finally:
                entry.completed = True

        entry.task = asyncio.create_task(_run())
        mode = "tunnel" if has_tunnel else "executor"
        logger.debug(
            f"[{self._label}] started proxy thread {tid} "
            f"for GFD opcode {gfd_opcode:#06x} via {mode}"
        )
        return tid

    def get_proxy_status(self, thread_id: int) -> Optional[ProxyThreadEntry]:
        """Return current status of a proxy thread, or None if unknown."""
        return self._proxy_threads.get(thread_id)

    def cancel_proxy(self, thread_id: int) -> CCI_RETURN_CODE:
        """Cancel an active proxy thread.  Returns INVALID_INPUT if not found."""
        entry = self._proxy_threads.get(thread_id)
        if entry is None:
            logger.error(f"[{self._label}] cancel_proxy: thread {thread_id} not found")
            return CCI_RETURN_CODE.INVALID_INPUT
        if entry.completed:
            # Already done — treat as success (idempotent)
            logger.debug(
                f"[{self._label}] cancel_proxy: thread {thread_id} already completed"
            )
            return CCI_RETURN_CODE.SUCCESS
        if entry.task and not entry.task.done():
            entry.task.cancel()
            logger.debug(f"[{self._label}] cancel_proxy: thread {thread_id} cancelled")
        del self._proxy_threads[thread_id]
        return CCI_RETURN_CODE.SUCCESS

    def cleanup_completed_threads(self) -> None:
        """Prune completed proxy threads from the registry."""
        done = [tid for tid, e in self._proxy_threads.items() if e.completed]
        for tid in done:
            del self._proxy_threads[tid]
