import sys
from opencis.util.logger import logger
from opencis.cxl.transport.cxl_io_packets import CxlIoMemRdPacket
from opencis.cxl.transport.pbr_packets import PbrBasePacket
from opencis.cxl.transport.packet_constants import SYSTEM_PAYLOAD_TYPE

def hex_dump(raw_bytes: bytes) -> str:
    return " ".join([f"{b:02X}" for b in raw_bytes])

def main():
    # 1. Enable console logging
    logger.set_stdout_levels(loglevel="DEBUG")
    logger.info("Starting HBR -> PBR Encapsulation Demo...")

    # 2. Create the standard HBR (CXL.io) Packet
    logger.info("Step 1: Generating standard HBR Packet...")
    hbr_packet = CxlIoMemRdPacket.create(addr=0x1234000, length=64)
    hbr_packet.mreq_header.req_id = 0xAAAA
    hbr_packet.mreq_header.tag = 0x55

    # Show the HBR bytes
    raw_hbr_bytes = bytes(hbr_packet)
    logger.debug(f"HBR Byte Stream ({len(raw_hbr_bytes)} bytes): {hex_dump(raw_hbr_bytes)}")

    # 3. Encapsulate into PBR Flit
    logger.info("\nStep 2: Encapsulating into PBR Flit...")
    source_dpid = 0x011
    dest_dpid = 0x222
    logger.info(f"Adding PBR Routing Header -> SPID: {hex(source_dpid)}, DPID: {hex(dest_dpid)}")
    
    pbr_flit = PbrBasePacket.encapsulate(
        spid=source_dpid, 
        dpid=dest_dpid, 
        inner_packet=hbr_packet
    )

    # Show the PBR flit properties
    logger.debug("PBR Flit Internal State:")
    print(pbr_flit.get_pretty_string())

    # Show the full encapsulated bytes
    raw_pbr_bytes = bytes(pbr_flit)
    logger.info("\nStep 3: Final PBR Wire Format (Ready for Transport Socket)")
    logger.debug(f"PBR Byte Stream ({len(raw_pbr_bytes)} bytes): {hex_dump(raw_pbr_bytes)}")
    
    # 4. Prove Decapsulation works perfectly
    logger.info("\nStep 4: Simulating switch receiving packet and Decapsulating...")
    received_flit = PbrBasePacket(raw_pbr_bytes)
    
    extracted_hbr_bytes = received_flit.get_data()
    logger.info(f"Extracted payload matches original HBR bytes: {extracted_hbr_bytes == raw_hbr_bytes}")
    
    recovered_hbr = CxlIoMemRdPacket(extracted_hbr_bytes)
    logger.info(f"Recovered HBR Address: {hex(getattr(recovered_hbr, 'get_address')())}")
    logger.info(f"Recovered HBR Req ID:  {hex(recovered_hbr.mreq_header.req_id)}")
    
    logger.info("\nDemo complete! HBR -> PBR encapsulation works correctly.")

if __name__ == "__main__":
    main()
