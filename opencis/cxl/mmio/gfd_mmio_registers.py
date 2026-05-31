"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.

GFD MMIO Register Block
-----------------------
A 4 KB BAR-0 register space exposed by the Generic Fabric Device.

Layout  (all little-endian, byte-addressable):
  0x000  [8B]  DEVICE_ID_REG      — HW_INIT  GFD sentinel (0x6FD0_0001)
  0x008  [8B]  SCRATCHPAD_0       — R/W  General-purpose 64-bit scratchpad
  0x010  [8B]  SCRATCHPAD_1       — R/W  General-purpose 64-bit scratchpad
  0x018  [8B]  SCRATCHPAD_2       — R/W  General-purpose 64-bit scratchpad
  0x020  [8B]  SCRATCHPAD_3       — R/W  General-purpose 64-bit scratchpad
  0x028  [4B]  STATUS_REG         — HW_INIT  Operational status flags
  0x02C  [4B]  CONTROL_REG        — R/W  Control bits (bit 0 = reset request)
  0x030  [8B]  MMIO_ACCESS_COUNT  — R/W  Running count of MMIO accesses served
                                         (written by firmware, read by host)
  0x038–0xFFF  RESERVED / zero-filled

Notes on field attributes:
  - HW_INIT: Field is written once by firmware at boot (hardware initialised).
    The bitmask allows the initial write; after that the host sees it as RO.
  - R/W (mmio_access_count): firmware increments it freely via write_bytes();
    the host reads it as a monotonic counter (no hardware-enforced RO needed
    because the MmioManager only calls _process_mmio_packet which goes through
    the bitmask anyway).
"""

from opencis.util.unaligned_bit_structure import (
    BitMaskedBitStructure,
    BitField,
    FIELD_ATTR,
    ShareableByteArray,
)

GFD_BAR_SIZE = 0x1000  # 4 KB

# GFD device-identification sentinel written into BAR-0 byte 0-7.
# Chosen so that FM / debug tools can identify this BAR at a glance.
GFD_DEVICE_ID_SENTINEL = 0x6FD00001

GFD_MMIO_REGS_DEF = [
    # ─ Static identification (HW_INIT → writable once by firmware) ───────────
    BitField("device_id_reg",      0,   63,  FIELD_ATTR.HW_INIT,
             default=GFD_DEVICE_ID_SENTINEL),        # 0x000
    # ─ Scratchpad registers (R/W by host) ────────────────────────────────────
    BitField("scratchpad_0",      64,  127,  FIELD_ATTR.RW),   # 0x008
    BitField("scratchpad_1",     128,  191,  FIELD_ATTR.RW),   # 0x010
    BitField("scratchpad_2",     192,  255,  FIELD_ATTR.RW),   # 0x018
    BitField("scratchpad_3",     256,  319,  FIELD_ATTR.RW),   # 0x020
    # ─ Status (HW_INIT = 0x1 on boot) ───────────────────────────────────────
    BitField("status_reg",       320,  351,  FIELD_ATTR.HW_INIT,
             default=0x1),                             # 0x028: bit-0 = device ready
    # ─ Control (R/W, reset-bit at bit 0) ─────────────────────────────────────
    BitField("control_reg",      352,  383,  FIELD_ATTR.RW),   # 0x02C
    # ─ Telemetry (R/W so firmware can increment it freely) ───────────────────
    BitField("mmio_access_count", 384, 447,  FIELD_ATTR.RW),   # 0x030
    # ─ Reserved padding to 4 KB ──────────────────────────────────────────────
    BitField("reserved",         448, (GFD_BAR_SIZE * 8) - 1, FIELD_ATTR.RESERVED),
]


class GfdMmioRegisters(BitMaskedBitStructure):
    """BAR-0 register block for the GFD.

    Defaults are seeded directly through BitField.default so the
    BitMaskedBitStructure initialiser applies them before the bitmask is
    constructed—no manual write_bytes() call needed.
    """

    _fields = GFD_MMIO_REGS_DEF

    def __init__(self, data: ShareableByteArray = None):
        if data is None:
            data = ShareableByteArray(GFD_BAR_SIZE)
        super().__init__(data)
        # BitField.default is applied by UnalignedBitStructure._add_bit_field()
        # via _data.write_bits(field.start, width, field.default).
        # No extra initialisation required here.

    # ── Byte offsets (matching the bit-field layout) ──────────────────────────
    _SCRATCHPAD_OFFSETS = [0x08, 0x10, 0x18, 0x20]
    _ACCESS_COUNT_OFFSET = 0x30

    def get_scratchpad(self, index: int) -> int:
        """Read one of the four 64-bit scratchpad registers (index 0–3)."""
        if index not in range(4):
            raise ValueError(f"Scratchpad index {index} out of range [0, 3]")
        off = self._SCRATCHPAD_OFFSETS[index]
        return self.read_bytes(off, off + 7)

    def set_scratchpad(self, index: int, value: int):
        """Write one of the four 64-bit scratchpad registers (index 0–3)."""
        if index not in range(4):
            raise ValueError(f"Scratchpad index {index} out of range [0, 3]")
        off = self._SCRATCHPAD_OFFSETS[index]
        self.write_bytes(off, off + 7, value & 0xFFFF_FFFF_FFFF_FFFF)

    def increment_access_count(self):
        """Atomically increment the MMIO access counter (firmware side)."""
        off = self._ACCESS_COUNT_OFFSET
        count = self.read_bytes(off, off + 7)
        self.write_bytes(off, off + 7, (count + 1) & 0xFFFF_FFFF_FFFF_FFFF)
