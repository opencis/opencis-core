import pytest
import asyncio

from opencis.cxl.component.pbr_switch_manager import PbrSwitchManager, DrtEntry, DrtEntryType
from opencis.cxl.component.pbr_switch_router import PbrSwitchRouter
from opencis.pci.component.fifo_pair import FifoPair
from opencis.cxl.component.hdm_decoder import (
    PbrHdmDecoderManager, HdmDecoderCapabilities, HDM_DECODER_COUNT,
    DecoderInfo, INTERLEAVE_GRANULARITY, INTERLEAVE_WAYS,
)
from opencis.cxl.transport.cxl_io_packets import CxlIoMemRdPacket
from opencis.cxl.transport.pbr_packets import PbrBasePacket
from opencis.cxl.transport.packet_constants import SYSTEM_PAYLOAD_TYPE
from opencis.util.logger import logger



@pytest.mark.asyncio
async def test_pbr_data_plane_routing():
    # 1. Setup Manager and Router
    pbr_manager = PbrSwitchManager()
    
    # Configure DRT: DPID 0x123 routes to Egress Port 2
    drt_entry = DrtEntry(entry_type=DrtEntryType.PHYSICAL_PORT, routing_target=2)
    pbr_manager.set_drt(0, 0x123, [drt_entry])
    
    # Create 3 fake ports
    port_fifos = [FifoPair() for _ in range(3)]
    
    router = PbrSwitchRouter(switch_id=0, pbr_switch_manager=pbr_manager, port_fifos=port_fifos)
    
    # Run the router in the background
    router_task = asyncio.create_task(router.run())
    await router.wait_for_ready()
    
    try:
        # 2. Simulate Ingress Encapsulation (HBR -> PBR)
        # Create a standard HBR memory read packet
        hbr_packet = CxlIoMemRdPacket.create(addr=0x1000, length=64)
        
        # Encapsulate it in a PBR Routing Header
        spid = 0x011
        dpid = 0x123
        pbr_packet = PbrBasePacket.encapsulate(spid=spid, dpid=dpid, inner_packet=hbr_packet)
        
        assert pbr_packet.system_header.payload_type == SYSTEM_PAYLOAD_TYPE.PBR
        assert pbr_packet.pbr_header.spid == 0x011
        assert pbr_packet.pbr_header.dpid == 0x123
        
        # 3. Inject PBR packet into Ingress Port 0
        # The router listens on target_to_host for incoming packets (from downstream endpoints)
        await port_fifos[0].target_to_host.put(pbr_packet)
        
        # 4. Verify Egress Decapsulation on Port 2
        # Router should look up DPID 0x123 -> Port 2
        # It should decapsulate the PBR header and forward the HBR packet to Port 2's host_to_target
        egress_packet = await asyncio.wait_for(port_fifos[2].host_to_target.get(), timeout=1.0)
        
        assert egress_packet is not None
        assert not egress_packet.is_pbr(), "Egress packet should be decapsulated (HBR)"
        assert egress_packet.is_cxl_io(), "Egress packet should be the original CXL.io packet"
        assert egress_packet.get_type() == "CxlIoMemRdPacket"
        
    finally:
        await router.stop()
        await router_task

@pytest.mark.asyncio
async def test_pbr_end_to_end_address_routing():
    # 1. Setup Managers
    pbr_manager = PbrSwitchManager()
    
    # Configure DRT: DPID 0x123 routes to Egress Port 2
    drt_entry = DrtEntry(entry_type=DrtEntryType.PHYSICAL_PORT, routing_target=2)
    pbr_manager.set_drt(0, 0x123, [drt_entry])
    
    # Configure HDM Decoder Manager
    capabilities = HdmDecoderCapabilities(
        decoder_count=HDM_DECODER_COUNT.DECODER_1,
        target_count=1,
        a11to8_interleave_capable=0,
        a14to12_interleave_capable=0,
        poison_on_decoder_error_capability=0,
        three_six_twelve_way_interleave_capable=0,
        sixteen_way_interleave_capable=0,
        uio_capable=0,
        uio_capable_decoder_count=0,
        mem_data_nxm_capable=0,
        bi_capable=False
    )
    hdm_manager = PbrHdmDecoderManager(capabilities)
    
    # Commit a decoder that maps 0x1000 - 0x2000 to DPID 0x123
    decoder_info = DecoderInfo(
        base=0x1000,
        size=0x1000,
        ig=INTERLEAVE_GRANULARITY.SIZE_256B,
        iw=INTERLEAVE_WAYS.WAY_1,
        target_ports=[0x123]  # This is used as target_dpids internally
    )
    hdm_manager.commit(0, decoder_info)
    
    port_fifos = [FifoPair() for _ in range(3)]
    
    router = PbrSwitchRouter(
        switch_id=0, 
        pbr_switch_manager=pbr_manager, 
        port_fifos=port_fifos,
        hdm_decoder_manager=hdm_manager
    )
    
    router_task = asyncio.create_task(router.run())
    await router.wait_for_ready()
    
    try:
        # 2. Inject raw HBR packet into Port 0
        hbr_packet = CxlIoMemRdPacket.create(addr=0x1500, length=64)
        
        # We put it in target_to_host. The router will process it, recognize it's HBR,
        # extract address (0x1500), map to DPID 0x123, encapsulate to PBR, route via DRT to Port 2,
        # and decapsulate it to host_to_target of Port 2.
        await port_fifos[0].target_to_host.put(hbr_packet)
        
        # 3. Verify it emerges successfully on Port 2
        egress_packet = await asyncio.wait_for(port_fifos[2].host_to_target.get(), timeout=1.0)
        
        assert egress_packet is not None
        assert not egress_packet.is_pbr(), "Egress packet should be HBR"
        assert egress_packet.is_cxl_io()
        assert egress_packet.get_type() == "CxlIoMemRdPacket"
        assert getattr(egress_packet, "get_address")() == 0x1500
        
    finally:
        await router.stop()
        await router_task
