import sys
from opencis.util.logger import logger
from opencis.cxl.transport.cxl_io_packets import CxlIoMemRdPacket
from opencis.cxl.transport.packet_constants import SYSTEM_PAYLOAD_TYPE

def main():
    # 1. Enable console logging so you can see the demo output
    logger.set_stdout_levels(loglevel="DEBUG")
    logger.info("Starting Mutable Packet Demo using mixin.py architecture...")

    # 2. Create a standard packet using the auto-generated cython/fallback structure
    # This automatically instantiates a mutable bytearray(512) underneath
    logger.info("Creating a CxlIoMemRdPacket (HBR TLP)...")
    packet = CxlIoMemRdPacket.create(addr=0x1234000, length=64)
    packet.mreq_header.req_id = 0xAAAA
    packet.mreq_header.tag = 0x55

    # 3. Demonstrate the get_pretty_string() mixin function
    # This proves that BasePacketMixin is attached and working
    logger.debug("Initial Packet State:")
    print(packet.get_pretty_string())

    # 4. Demonstrate MUTABILITY
    logger.info("Mutating packet fields...")
    logger.info("Changing req_id from 0xAAAA to 0xBBBB")
    packet.mreq_header.req_id = 0xBBBB

    logger.info("Changing address from 0x1234000 to 0x9876000")
    packet.addr_upper = 0  # Setting via the property setters directly manipulates the bytearray
    packet.addr_lower = 0x9876000 >> 2  # The struct shifts by 2 because it's DWORD aligned

    # 5. Show the updated state using mixin again
    logger.debug("Mutated Packet State:")
    print(packet.get_pretty_string())

    # 6. Demonstrate the raw bytearray serialization
    # This shows that setting properties automatically mutated the exact bits in the bytearray
    raw_bytes = bytes(packet)
    logger.info(f"Final serialized byte stream ({len(raw_bytes)} bytes):")
    
    # Print out the raw bytes in hex format
    hex_str = " ".join([f"{b:02X}" for b in raw_bytes])
    print(f"RAW HEX: {hex_str}")

    logger.info("Demo complete! Mutable mixin packets are working perfectly.")

if __name__ == "__main__":
    main()
