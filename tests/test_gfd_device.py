"""
tests/test_gfd_device.py
========================
Unit tests for the Generic Fabric Device (GFD).

Tests verify:
  1.  GFD instantiation and lifecycle (start / stop).
  2.  BAR-0 size is GFD_BAR_SIZE (4 KB).
  3.  device_id_reg sentinel at BAR-0 offset 0.
  4.  status_reg bit-0 set to 1 on startup.
  5.  Scratchpad register read-write round-trip.
  6.  Access counter increments monotonically.
  7.  CCI Identify returns IdentifyComponentType.GFD (0x04).

All tests are in-process (test_mode=True) — no TCP required.
"""

import asyncio
import pytest

from opencis.cxl.component.cxl_connection import CxlConnection
from opencis.apps.generic_fabric_device import GenericFabricDevice
from opencis.cxl.mmio.gfd_mmio_registers import GfdMmioRegisters, GFD_BAR_SIZE
from opencis.cxl.component.cci_executor import CciRequest
from opencis.cxl.cci.common import CCI_GENERIC_COMMAND_OPCODE
from opencis.cxl.cci.generic.information_and_status.identify import (
    IdentifyResponsePayload,
    IdentifyComponentType,
)
from opencis.util.logger import logger


@pytest.fixture(autouse=True)
def _set_log_level():
    logger.set_stdout_levels(loglevel="WARNING")
    yield


def _make_gfd(port_index: int = 1, serial: str = "0000000000000001") -> GenericFabricDevice:
    """Create a GFD in test-mode (no TCP) with a fresh CxlConnection."""
    conn = CxlConnection()
    return GenericFabricDevice(
        port_index=port_index,
        serial_number=serial,
        test_mode=True,
        cxl_connection=conn,
    )


# ── 1. Lifecycle ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_gfd_starts_and_stops():
    """GFD must reach 'running' state and stop cleanly."""
    from opencis.util.component import COMPONENT_STATUS
    gfd = _make_gfd()
    task = asyncio.create_task(gfd.run())
    await gfd.wait_for_ready()
    # Use the internal _status attribute since RunnableComponent has no is_running()
    assert gfd._status == COMPONENT_STATUS.RUNNING
    await gfd.stop()
    await asyncio.wait_for(task, timeout=5.0)


# ── 2. BAR-0 register defaults ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_gfd_bar_size():
    """BAR-0 must be exactly GFD_BAR_SIZE bytes."""
    gfd = _make_gfd()
    task = asyncio.create_task(gfd.run())
    await gfd.wait_for_ready()
    try:
        assert gfd.get_gfd_device().get_bar_size() == GFD_BAR_SIZE
    finally:
        await gfd.stop()
        await asyncio.wait_for(task, timeout=5.0)


@pytest.mark.asyncio
async def test_gfd_registers_device_id_sentinel():
    """device_id_reg (BAR-0 offset 0x00) must carry the 0x6FD00001 sentinel."""
    gfd = _make_gfd()
    task = asyncio.create_task(gfd.run())
    await gfd.wait_for_ready()
    try:
        regs: GfdMmioRegisters = gfd.get_gfd_device().get_registers()
        device_id = regs.read_bytes(0, 7)
        assert device_id == 0x6FD00001, (
            f"Expected 0x6FD00001 at BAR-0 offset 0, got 0x{device_id:016X}"
        )
    finally:
        await gfd.stop()
        await asyncio.wait_for(task, timeout=5.0)


@pytest.mark.asyncio
async def test_gfd_registers_status_ready():
    """status_reg bit-0 must be 1 on startup (device ready)."""
    gfd = _make_gfd()
    task = asyncio.create_task(gfd.run())
    await gfd.wait_for_ready()
    try:
        regs: GfdMmioRegisters = gfd.get_gfd_device().get_registers()
        status = regs.read_bytes(0x28, 0x2B)   # status_reg @ byte 40 (0x28)
        assert status & 0x1 == 1, f"status_reg bit-0 not set: 0x{status:08X}"
    finally:
        await gfd.stop()
        await asyncio.wait_for(task, timeout=5.0)


# ── 3. Scratchpad read-write round-trip ───────────────────────────────────────

@pytest.mark.asyncio
async def test_gfd_scratchpad_roundtrip():
    """All four scratchpad registers must support read-after-write."""
    gfd = _make_gfd()
    task = asyncio.create_task(gfd.run())
    await gfd.wait_for_ready()
    try:
        regs: GfdMmioRegisters = gfd.get_gfd_device().get_registers()
        values = [0xDEADBEEFCAFEBABE, 0x0102030405060708, 0xFFFF000000000001, 0x0]
        for idx, val in enumerate(values):
            regs.set_scratchpad(idx, val)
            read_back = regs.get_scratchpad(idx)
            assert read_back == val, (
                f"Scratchpad {idx}: wrote 0x{val:016X}, read 0x{read_back:016X}"
            )
    finally:
        await gfd.stop()
        await asyncio.wait_for(task, timeout=5.0)


@pytest.mark.asyncio
async def test_gfd_access_counter_increments():
    """increment_access_count() must monotonically increase the access counter."""
    gfd = _make_gfd()
    task = asyncio.create_task(gfd.run())
    await gfd.wait_for_ready()
    try:
        regs: GfdMmioRegisters = gfd.get_gfd_device().get_registers()
        for expected in range(1, 6):
            regs.increment_access_count()
            count = regs.read_bytes(0x30, 0x37)
            assert count == expected, f"Expected count {expected}, got {count}"
    finally:
        await gfd.stop()
        await asyncio.wait_for(task, timeout=5.0)


# ── 4. CCI Identify ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_gfd_cci_identify():
    """CCI Identify command must return IdentifyComponentType.GFD (0x04)."""
    gfd = _make_gfd(serial="0000AABB00000001")
    task = asyncio.create_task(gfd.run())
    await gfd.wait_for_ready()
    try:
        dev = gfd.get_gfd_device()
        executor = dev._cci_executor
        request = CciRequest(opcode=CCI_GENERIC_COMMAND_OPCODE.IDENTIFY)
        response = await executor.execute_command(request)
        assert response.return_code.value == 0, (
            f"Identify failed: {response.return_code}"
        )
        payload = IdentifyResponsePayload.parse(response.payload)
        assert payload.component_type == IdentifyComponentType.GFD, (
            f"Expected GFD(0x04), got {payload.component_type}"
        )
    finally:
        await gfd.stop()
        await asyncio.wait_for(task, timeout=5.0)
