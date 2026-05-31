import pytest

from opencis.cxl.transport.packet_constants import SYSTEM_PAYLOAD_TYPE
from opencis.cxl.transport.pbr_packets import PbrBasePacket
from opencis.cxl.transport.cxl_io_packets import CxlIoMemRdPacket

def test_hbr_to_pbr_encapsulation_and_decapsulation():
    """
    Tests the fundamental serialization and deserialization of PBR flits.
    Ensures that an HBR packet can be encapsulated into a PBR packet,
    serialized to bytes, and fully recovered.
    """
    # 1. Create a standard HBR Packet
    # We use CxlIoMemRdPacket as an example of a typical CXL.io TLP
    original_hbr = CxlIoMemRdPacket.create(addr=0x1A2B3000, length=128)
    # Assign some dummy values to verify they survive the round trip
    original_hbr.mreq_header.req_id = 0x1234
    original_hbr.mreq_header.tag = 0x56

    # 2. Encapsulate into a PBR Packet
    source_dpid = 0x012
    dest_dpid = 0x345
    pbr_packet = PbrBasePacket.encapsulate(
        spid=source_dpid, 
        dpid=dest_dpid, 
        inner_packet=original_hbr
    )

    # Verify PBR encapsulation headers
    assert pbr_packet.is_pbr()
    assert pbr_packet.system_header.payload_type == SYSTEM_PAYLOAD_TYPE.PBR
    assert pbr_packet.pbr_header.spid == source_dpid
    assert pbr_packet.pbr_header.dpid == dest_dpid

    # 3. Simulate transmitting over a socket (convert to raw bytes)
    raw_pbr_bytes = bytes(pbr_packet)
    assert len(raw_pbr_bytes) > 0

    # 4. Simulate receiving from a socket (parse from raw bytes)
    received_pbr = PbrBasePacket(raw_pbr_bytes)
    
    # Verify the PBR headers survived the byte serialization
    assert received_pbr.system_header.payload_type == SYSTEM_PAYLOAD_TYPE.PBR
    assert received_pbr.pbr_header.spid == source_dpid
    assert received_pbr.pbr_header.dpid == dest_dpid

    # 5. Extract the inner HBR payload and re-hydrate
    raw_hbr_bytes = received_pbr.get_data()
    recovered_hbr = CxlIoMemRdPacket(raw_hbr_bytes)

    # 6. Verify the recovered HBR packet matches the original exactly
    assert recovered_hbr.is_cxl_io()
    assert getattr(recovered_hbr, "get_address")() == 0x1A2B3000
    assert recovered_hbr.mreq_header.req_id == 0x1234
    assert recovered_hbr.mreq_header.tag == 0x56
