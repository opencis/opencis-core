#!/usr/bin/env python3

import pyshark, time
from pyshark.packet.packet import Packet


# Path to your Lua script
# lua_script_path = 'my_script.lua'

# Path to your pcap file
pcap_file_path = "/Users/zhxq/Downloads/50000-t1n2f1u-cache8-32.pcap"

# Define custom parameters to load the Lua script
# custom_params = {'-X': f'lua_script:{lua_script_path}'}

# Open the pcap file with custom parameters
# cap = pyshark.FileCapture(input_file=pcap_file_path, custom_parameters=custom_params)
cap = pyshark.FileCapture(
    input_file=pcap_file_path, display_filter="opencis.cache", include_raw=True, use_json=True
)


processor = pyshark.InMemCapture()

start_time = time.perf_counter()
processed_count = 0
packet: Packet
for packet in cap:
    if processed_count % 10000 == 0:
        print(f"{processed_count} packets processed...")
    packet_num: int = packet.number
    src_port: int = packet.tcp.srcport.hex_value
    dst_port: int = packet.tcp.dstport.hex_value
    raw_packet = packet.get_raw_packet()

    new_packet = processor.parse_packet(raw_packet)
    print(new_packet.opencis)

    raw_packet_len = packet.length
    assert len(raw_packet) == raw_packet_len
    processed_count += 1
    # raw_data = packet.tcp.data


print("")
# Close the capture
cap.close()
end_time = time.perf_counter()
elapsed_time = end_time - start_time
print(f"Elapsed time: {elapsed_time:.6f} seconds")
print(f"Average: {(processed_count / elapsed_time):.6f} packets/s")
