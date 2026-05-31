"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Dict, List, Optional, Tuple

from opencis.cxl.cci.common import CCI_RETURN_CODE
from opencis.util.logger import logger


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PID_MAX = 0xFFF  # 12-bit PID space
PID_UNASSIGNED = 0xFFF  # sentinel for "no PID assigned"
DRT_TABLE_SIZE = 4096  # one entry per possible DPID value (2^12)


# ---------------------------------------------------------------------------
# DRT enumerations and structures
# ---------------------------------------------------------------------------


class DrtEntryType(IntEnum):
    """Entry Type field in a DRT entry (Table 7-133, CXL Spec Rev 4.0 §7.7.13.9)."""
    INVALID = 0b00        # no routing — drop or error
    PHYSICAL_PORT = 0b01  # route to a physical port number
    RGT_INDEX = 0b10      # route via a Routing Group Table entry (multicast)
    RESERVED = 0b11


@dataclass
class DrtEntry:
    """
    One row in a DPID Routing Table (DRT).

    The DRT is indexed by **DPID** (Destination PID from the PBR TLP Header).
    This entry is NOT a port↔vPPB map — it maps a DPID to an egress physical
    port (or RGT index for group/multicast routing).

    Wire format (Table 7-133):
        Byte 0: Bits[1:0] = entry_type, Bits[7:2] = Reserved
        Byte 1: routing_target (port number or RGT index)
    """
    entry_type: DrtEntryType = DrtEntryType.INVALID
    routing_target: int = 0  # physical port number OR RGT entry index

    def dump(self) -> bytes:
        data = bytearray(2)
        data[0] = int(self.entry_type) & 0x03
        data[1] = self.routing_target & 0xFF
        return bytes(data)

    @classmethod
    def parse(cls, data: bytes, offset: int = 0) -> "DrtEntry":
        if len(data) < offset + 2:
            raise ValueError("DrtEntry requires at least 2 bytes")
        entry_type_val = data[offset] & 0x03
        try:
            entry_type = DrtEntryType(entry_type_val)
        except ValueError:
            entry_type = DrtEntryType.RESERVED
        routing_target = data[offset + 1]
        return cls(entry_type=entry_type, routing_target=routing_target)


@dataclass
class DrtTable:
    """
    One DPID Routing Table (DRT) within a PBR switch.

    A switch may expose multiple DRT tables (reported via Identify PBR Switch).
    Each active port references one DRT table. The DRT is a flat array of
    DRT_TABLE_SIZE (4096) entries, where the array index IS the DPID to route.

    Example: entries[0x042] = DrtEntry(PHYSICAL_PORT, 3)
      → TLPs with DPID=0x042 are routed out physical port 3.
    """
    associated_rgt_index: int = 0
    entries: List[DrtEntry] = field(
        default_factory=lambda: [DrtEntry() for _ in range(DRT_TABLE_SIZE)]
    )


# ---------------------------------------------------------------------------
# PID target structures (used by Identify / Get PID Target List)
# ---------------------------------------------------------------------------


class PidTargetType(IntEnum):
    FABRIC_PORT = 0b000
    HOST_EDGE_PORT = 0b001       # USP or GAE
    DOWNSTREAM_EDGE_PORT = 0b010


@dataclass
class PidTarget:
    """One entry in the PID target list (Table 7-122)."""
    target_id: int
    target_type: PidTargetType
    instance_id: int
    vcs_id: int      # valid only for HOST_EDGE_PORT
    physical_port_id: int
    pid: int = PID_UNASSIGNED  # current assignment; FFFh if unassigned


@dataclass
class PidAssignment:
    """Runtime record linking a PID to a target."""
    pid: int
    target_id: int
    instance_id: int


# ---------------------------------------------------------------------------
# PID Binding structures (used by Get/Configure PID Binding)
# ---------------------------------------------------------------------------


class PidBindingOperation(IntEnum):
    BIND = 0b000
    UNBIND = 0b001


@dataclass
class HmatInfo:
    """Latency / BW values from ACPI HMAT System Locality structure."""
    latency_entry_base_unit: int = 0   # 8 bytes
    latency_entry: int = 0             # 2 bytes
    bw_entry_base_unit: int = 0        # 8 bytes
    bw_entry: int = 0                  # 2 bytes


@dataclass
class PidBinding:
    """State for one (vcs_id, vppb_id) binding entry."""
    pid: int = PID_UNASSIGNED
    hmat: HmatInfo = field(default_factory=HmatInfo)


# ---------------------------------------------------------------------------
# Identify PBR Switch info
# ---------------------------------------------------------------------------


@dataclass
class PbrSwitchInfo:
    """Data returned by Identify PBR Switch (Table 7-114)."""
    gae_support_map: int = 0        # 8-byte bitmask, bit = VCS ID
    num_drts: int = 1               # must be > 0
    num_rgts: int = 0
    # Dynamic routing mode capability bits (byte Bh)
    random_supported: bool = False
    congestion_avoidance_supported: bool = False
    advanced_ca_supported: bool = False
    vendor_routing_mode1_supported: bool = False
    vendor_routing_mode2_supported: bool = False

    def routing_caps_byte(self) -> int:
        val = 0
        if self.random_supported:
            val |= 0x01
        if self.congestion_avoidance_supported:
            val |= 0x02
        if self.advanced_ca_supported:
            val |= 0x04
        if self.vendor_routing_mode1_supported:
            val |= 0x40
        if self.vendor_routing_mode2_supported:
            val |= 0x80
        return val


# ---------------------------------------------------------------------------
# PbrSwitchManager — central state owner
# ---------------------------------------------------------------------------


class PbrSwitchManager:
    """
    Manages the runtime state of a PBR switch:
      - PID assignments (PID → PidTarget)
      - DRT tables   (DPID → {entry_type, egress_port_or_rgt})
      - PID bindings (vcs_id, vppb_id) → PidBinding with HMAT info

    This class is injected into each PBR CCI command handler, following the
    same pattern as PhysicalPortManager / VirtualSwitchManager.

    DRT model
    ---------
    The DRT is a flat 4096-entry array indexed by DPID (12-bit PID value).
    It is NOT a port↔vPPB map.  When a TLP arrives with DPID=X the switch
    looks up DRT[active_drt_index].entries[X] to decide the egress port.

    The FM must call Set DRT (5709h) AFTER calling Configure PID Assignment
    (5704h); assigning a PID does NOT auto-populate the DRT.
    """

    def __init__(
        self,
        num_drts: int = 1,
        num_rgts: int = 0,
        pid_targets: Optional[List[PidTarget]] = None,
        label: Optional[str] = None,
    ):
        self._label = label or "PbrSwitchManager"
        self._switch_info = PbrSwitchInfo(num_drts=num_drts, num_rgts=num_rgts)
        # DRT tables — all entries initialised as INVALID (no routing until FM programs them)
        self._drt_tables: List[DrtTable] = [DrtTable() for _ in range(num_drts)]
        # PID targets this switch exposes for assignment
        self._pid_targets: List[PidTarget] = pid_targets or []
        # PID → PidTarget (only populated targets)
        self._pid_assignments: Dict[int, PidAssignment] = {}
        # (vcs_id, vppb_id) → PidBinding
        self._pid_bindings: Dict[Tuple[int, int], PidBinding] = {}

    # ------------------------------------------------------------------
    # Identify
    # ------------------------------------------------------------------

    def get_identify_info(self) -> PbrSwitchInfo:
        """
        Return switch capability info.

        num_drts is derived from the *actual* DRT table list so the response
        is always consistent with the real state — even if _switch_info was
        constructed or mutated independently.
        """
        self._switch_info.num_drts = len(self._drt_tables)
        return self._switch_info

    # ------------------------------------------------------------------
    # PID Target List
    # ------------------------------------------------------------------

    def get_pid_target_count(self) -> int:
        return len(self._pid_targets)

    def get_pid_target_list(self, start_index: int, num_targets: int) -> List[PidTarget]:
        return self._pid_targets[start_index: start_index + num_targets]

    # ------------------------------------------------------------------
    # PID Assignment
    # ------------------------------------------------------------------

    def assign_pid(self, pid: int, target_id: int, instance_id: int) -> CCI_RETURN_CODE:
        """
        Assign a PID to a specific target.

        Spec (§7.7.13.5): Returns INVALID_INPUT if the target is invalid
        or the PID is already assigned to another target.

        Note: Does NOT update DRT. FM must call set_drt() separately.
        """
        if pid > PID_MAX:
            logger.error(f"[{self._label}] assign_pid: PID {pid:#05x} out of range")
            return CCI_RETURN_CODE.INVALID_INPUT

        # Validate target_id only when an explicit pid_targets list was configured.
        # When the list is empty (open mode — FM manages targets externally), skip
        # validation and allow any target_id.
        if self._pid_targets:
            matching = [t for t in self._pid_targets if t.target_id == target_id]
            if not matching:
                logger.error(f"[{self._label}] assign_pid: target_id {target_id} not found")
                return CCI_RETURN_CODE.INVALID_INPUT

        # PID already assigned to a *different* target?
        if pid in self._pid_assignments:
            existing = self._pid_assignments[pid]
            if existing.target_id != target_id:
                logger.error(
                    f"[{self._label}] assign_pid: PID {pid:#05x} already assigned "
                    f"to target {existing.target_id}"
                )
                return CCI_RETURN_CODE.INVALID_INPUT

        self._pid_assignments[pid] = PidAssignment(pid, target_id, instance_id)
        # Update the in-memory target entry's current PID field
        for t in self._pid_targets:
            if t.target_id == target_id and t.instance_id == instance_id:
                t.pid = pid
                break
        logger.debug(f"[{self._label}] assign_pid: PID {pid:#05x} → target {target_id}")
        return CCI_RETURN_CODE.SUCCESS

    def clear_pid(self, pid: int, target_id: int, instance_id: int) -> CCI_RETURN_CODE:
        """
        Remove a PID assignment.

        Spec (§7.7.13.5): Returns INVALID_INPUT if the PID is not currently
        assigned (clearing an unassigned PID is not a valid operation).
        """
        if pid not in self._pid_assignments:
            logger.error(
                f"[{self._label}] clear_pid: PID {pid:#05x} not in assignment map"
            )
            return CCI_RETURN_CODE.INVALID_INPUT

        del self._pid_assignments[pid]
        for t in self._pid_targets:
            if t.pid == pid:
                t.pid = PID_UNASSIGNED
        logger.debug(f"[{self._label}] clear_pid: PID {pid:#05x} cleared")
        return CCI_RETURN_CODE.SUCCESS

    # ------------------------------------------------------------------
    # DRT — DPID Routing Tables
    # ------------------------------------------------------------------

    def get_drt(
        self, drt_index: int, start_entry: int, num_entries: int
    ) -> Optional[Tuple[List[DrtEntry], int]]:
        """
        Read entries from a DRT.

        Returns (entries_slice, associated_rgt_index) or None on invalid input.
        The caller (GetDrtCommand) handles the INVALID_INPUT response.

        DRT is indexed by DPID: entries[dpid] → {entry_type, routing_target}.
        """
        if drt_index < 0 or drt_index >= len(self._drt_tables):
            logger.error(f"[{self._label}] get_drt: drt_index {drt_index} out of range")
            return None
        table = self._drt_tables[drt_index]
        end = start_entry + num_entries
        if start_entry < 0 or end > DRT_TABLE_SIZE:
            logger.error(
                f"[{self._label}] get_drt: range [{start_entry},{end}) out of bounds"
            )
            return None
        return (table.entries[start_entry:end], table.associated_rgt_index)

    def set_drt(
        self, drt_index: int, start_entry: int, entries: List[DrtEntry]
    ) -> CCI_RETURN_CODE:
        """
        Write entries into a DRT starting at start_entry.

        DRT model:
          - DRT is a flat array of 4096 entries indexed by DPID.
          - entry.entry_type = PHYSICAL_PORT → entry.routing_target = egress port number
          - entry.entry_type = RGT_INDEX    → entry.routing_target = RGT entry index
          - entry.entry_type = INVALID      → no routing (drop)
          - entry.entry_type = RESERVED     → invalid input
        """
        if drt_index < 0 or drt_index >= len(self._drt_tables):
            logger.error(f"[{self._label}] set_drt: drt_index {drt_index} out of range")
            return CCI_RETURN_CODE.INVALID_INPUT

        end = start_entry + len(entries)
        if start_entry < 0 or end > DRT_TABLE_SIZE:
            logger.error(
                f"[{self._label}] set_drt: write range [{start_entry},{end}) exceeds "
                f"DRT_TABLE_SIZE={DRT_TABLE_SIZE}"
            )
            return CCI_RETURN_CODE.INVALID_INPUT

        # Validate no RESERVED entry types
        for i, entry in enumerate(entries):
            if entry.entry_type == DrtEntryType.RESERVED:
                logger.error(
                    f"[{self._label}] set_drt: entry[{start_entry + i}] has "
                    f"reserved entry_type=11b"
                )
                return CCI_RETURN_CODE.INVALID_INPUT

        table = self._drt_tables[drt_index]
        for i, entry in enumerate(entries):
            table.entries[start_entry + i] = entry
        logger.debug(
            f"[{self._label}] set_drt: wrote {len(entries)} entries to "
            f"DRT[{drt_index}] starting at DPID {start_entry:#05x}"
        )
        return CCI_RETURN_CODE.SUCCESS

    # ------------------------------------------------------------------
    # PID Bindings (edge-switch fabric stitching)
    # ------------------------------------------------------------------

    def get_pid_binding(self, vcs_id: int, vppb_id: int) -> Optional[PidBinding]:
        return self._pid_bindings.get((vcs_id, vppb_id))

    def configure_pid_binding(
        self,
        operation: PidBindingOperation,
        vcs_id: int,
        vppb_id: int,
        pid: int,
        hmat: HmatInfo,
    ) -> CCI_RETURN_CODE:
        """Bind or unbind a PID to a VCS vPPB for fabric edge stitching."""
        if operation == PidBindingOperation.BIND:
            self._pid_bindings[(vcs_id, vppb_id)] = PidBinding(pid=pid, hmat=hmat)
            logger.debug(
                f"[{self._label}] configure_pid_binding: bound PID {pid:#05x} "
                f"to VCS {vcs_id} vPPB {vppb_id}"
            )
        elif operation == PidBindingOperation.UNBIND:
            if (vcs_id, vppb_id) not in self._pid_bindings:
                logger.error(
                    f"[{self._label}] configure_pid_binding: "
                    f"VCS {vcs_id} vPPB {vppb_id} not bound"
                )
                return CCI_RETURN_CODE.INVALID_INPUT
            del self._pid_bindings[(vcs_id, vppb_id)]
            logger.debug(
                f"[{self._label}] configure_pid_binding: unbound "
                f"VCS {vcs_id} vPPB {vppb_id}"
            )
        else:
            return CCI_RETURN_CODE.INVALID_INPUT
        return CCI_RETURN_CODE.SUCCESS
