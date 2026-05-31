"""
tests/test_pbr_qemu_e2e.py
==========================
End-to-end PBR switch data-plane test — no QEMU, no running switch needed.

Port topology semantics used in this test:
  - port_fifos[0]  → USP port  (host writes to host_to_target; router watches it)
  - port_fifos[1]  → DSP port  (GFD writes to target_to_host; router watches it)

When port_types=None (default), all ports are treated as DSP:
  - router watches target_to_host on each port
  - router writes to host_to_target of the egress port

For QEMU:
  - USP (port_types[0]=True): router watches host_to_target → routes to DSP's target_to_host
  - DSP (port_types[1]=False): router watches target_to_host → routes to USP's host_to_target
"""

import asyncio
import pytest

from opencis.cxl.component.pbr_switch_manager import (
    PbrSwitchManager,
    DrtEntry,
    DrtEntryType,
)
from opencis.cxl.component.pbr_switch_router import PbrSwitchRouter
from opencis.cxl.component.hdm_decoder import (
    PbrHdmDecoderManager,
    HdmDecoderCapabilities,
    HDM_DECODER_COUNT,
    DecoderInfo,
    INTERLEAVE_GRANULARITY,
    INTERLEAVE_WAYS,
)
from opencis.pci.component.fifo_pair import FifoPair
from opencis.cxl.transport.cxl_mem_packets import CxlMemMemRdPacket
from opencis.cxl.transport.pbr_packets import PbrBasePacket
from opencis.util.logger import logger


@pytest.fixture(autouse=True)
def _set_log_level():
    logger.set_stdout_levels(loglevel="DEBUG")
    yield


def _make_pbr_hdm_manager() -> PbrHdmDecoderManager:
    """Create a PbrHdmDecoderManager covering HPA 0x0–0x0FFFFFFF → DPID 0x010."""
    caps: HdmDecoderCapabilities = {
        "decoder_count": HDM_DECODER_COUNT.DECODER_1,
        "target_count": 1,
        "a11to8_interleave_capable": 0,
        "a14to12_interleave_capable": 0,
        "poison_on_decoder_error_capability": 0,
        "three_six_twelve_way_interleave_capable": 0,
        "sixteen_way_interleave_capable": 0,
        "uio_capable": 0,
        "uio_capable_decoder_count": 0,
        "mem_data_nxm_capable": 0,
        "bi_capable": False,
    }
    mgr = PbrHdmDecoderManager(caps, label="TestHdmMgr")
    info = DecoderInfo(
        base=0x0,
        size=0x10000000,  # 256 MB
        ig=INTERLEAVE_GRANULARITY.SIZE_256B,
        iw=INTERLEAVE_WAYS.WAY_1,
        target_ports=[0x010],  # used as target_dpids by PbrHdmDecoder
    )
    mgr.commit(0, info)
    return mgr


@pytest.mark.asyncio
async def test_pbr_qemu_e2e_dsp_ingress():
    """
    DSP device sends CXL.mem read → router routes via DRT → packet on USP egress.

    Setup:
      port 0 = DSP (GFD) — default, port_types not specified → router watches target_to_host
      port 1 = DSP (USP-substitute for this test) — DPID 0x010 → port 1

    Inject on port_fifos[0].target_to_host (device→switch direction).
    Expect packet on port_fifos[1].host_to_target (router output, host direction).

    Verifies: Gap 1 (router running), Gap 3 (HDM decoder), Gap 4 (DSP direction).
    """
    pbr_manager = PbrSwitchManager()
    # DPID 0x010 → port 1
    pbr_manager.set_drt(0, 0x010, [DrtEntry(DrtEntryType.PHYSICAL_PORT, routing_target=1)])

    hdm_manager = _make_pbr_hdm_manager()
    port_fifos = [FifoPair(), FifoPair()]

    # Default: all ports treated as DSP (target_to_host ingress)
    router = PbrSwitchRouter(
        switch_id=0,
        pbr_switch_manager=pbr_manager,
        port_fifos=port_fifos,
        hdm_decoder_manager=hdm_manager,
    )

    router_task = asyncio.create_task(router.run())
    await router.wait_for_ready()

    try:
        # HBR CXL.mem read: addr=0x1000 is in HDM range → DPID=0x010 → port 1
        mem_req = CxlMemMemRdPacket.create(0x1000)
        await port_fifos[0].target_to_host.put(mem_req)

        # Router encaps to PBR → DRT → decaps → delivers to port 1 host_to_target
        packet = await asyncio.wait_for(port_fifos[1].host_to_target.get(), timeout=2.0)

        assert packet is not None, "No packet arrived at egress port"
        assert not packet.is_pbr(), "Egress packet must be decapsulated (HBR)"
        assert packet.is_cxl_mem(), "Egress packet must be CXL.mem"

    finally:
        await router.stop()
        await router_task


@pytest.mark.asyncio
async def test_pbr_qemu_e2e_usp_ingress():
    """
    USP host sends PBR-wrapped CXL.mem → router DRT lookup → decaps → DSP egress.

    Setup:
      port 0 = USP  (port_types[0]=True) — router watches host_to_target
      port 1 = DSP  (port_types[1]=False) — DPID 0x010 → port 1

    Inject PBR packet on port_fifos[0].host_to_target (host→switch direction).
    Expect decapsulated packet on port_fifos[1].target_to_host (toward device).

    Verifies: Gap 4 (h2t USP direction).
    """
    pbr_manager = PbrSwitchManager()
    pbr_manager.set_drt(0, 0x010, [DrtEntry(DrtEntryType.PHYSICAL_PORT, routing_target=1)])

    hdm_manager = _make_pbr_hdm_manager()
    port_fifos = [FifoPair(), FifoPair()]

    router = PbrSwitchRouter(
        switch_id=0,
        pbr_switch_manager=pbr_manager,
        port_fifos=port_fifos,
        hdm_decoder_manager=hdm_manager,
        port_types=[True, False],  # port 0 = USP, port 1 = DSP
    )

    router_task = asyncio.create_task(router.run())
    await router.wait_for_ready()

    try:
        # Host sends PBR-wrapped packet destined for DPID 0x010 (GFD on port 1)
        inner = CxlMemMemRdPacket.create(0x1000)
        pbr_pkt = PbrBasePacket.encapsulate(spid=0x020, dpid=0x010, inner_packet=inner)

        # USP ingress: host writes to host_to_target on port 0
        await port_fifos[0].host_to_target.put(pbr_pkt)

        # Router routes DPID 0x010 → port 1, decaps, writes to port 1 host_to_target
        # (device reads from host_to_target; both ingress paths write to h2t at egress)
        packet = await asyncio.wait_for(port_fifos[1].host_to_target.get(), timeout=2.0)

        assert packet is not None, "No packet arrived at GFD port"
        assert not packet.is_pbr(), "Egress packet must be decapsulated"
        assert packet.is_cxl_mem(), "Egress packet must be CXL.mem"

    finally:
        await router.stop()
        await router_task


@pytest.mark.asyncio
async def test_pbr_qemu_e2e_bidirectional():
    """
    Full round-trip with port_types:
      Forward:  USP host → GFD  (h2t on port 0, HBR → PBR → port 1 t2h)
      Backward: GFD → USP host  (t2h on port 1, PBR → port 0 h2t)
    """
    pbr_manager = PbrSwitchManager()
    # Host traffic → GFD (DPID 0x010 → port 1)
    pbr_manager.set_drt(0, 0x010, [DrtEntry(DrtEntryType.PHYSICAL_PORT, routing_target=1)])
    # GFD reply → host (DPID 0x020 → port 0)
    pbr_manager.set_drt(0, 0x020, [DrtEntry(DrtEntryType.PHYSICAL_PORT, routing_target=0)])

    hdm_manager = _make_pbr_hdm_manager()
    port_fifos = [FifoPair(), FifoPair()]

    router = PbrSwitchRouter(
        switch_id=0,
        pbr_switch_manager=pbr_manager,
        port_fifos=port_fifos,
        hdm_decoder_manager=hdm_manager,
        port_types=[True, False],  # port 0 = USP, port 1 = DSP (GFD)
    )

    router_task = asyncio.create_task(router.run())
    await router.wait_for_ready()

    try:
        # 1. USP host sends HBR CXL.mem read on port 0 h2t (addr in HDM range → DPID 0x010)
        req = CxlMemMemRdPacket.create(0x1000)
        await port_fifos[0].host_to_target.put(req)

        fwd = await asyncio.wait_for(port_fifos[1].host_to_target.get(), timeout=2.0)
        assert fwd is not None and fwd.is_cxl_mem(), "Forward path failed"

        # 2. GFD replies with PBR packet (DPID 0x020 → port 0) on port 1 t2h
        reply_inner = CxlMemMemRdPacket.create(0x1000)
        reply_pbr = PbrBasePacket.encapsulate(spid=0x010, dpid=0x020, inner_packet=reply_inner)
        await port_fifos[1].target_to_host.put(reply_pbr)

        back = await asyncio.wait_for(port_fifos[0].host_to_target.get(), timeout=2.0)
        assert back is not None and back.is_cxl_mem(), "Return path failed"

    finally:
        await router.stop()
        await router_task
