"""
 Copyright (c) 2024, Eeum, Inc.

 This software is licensed under the terms of the Revised BSD License.
 See LICENSE for details.
"""

import asyncio
from scapy.all import PcapReader

from opencis.util.logger import logger
from opencis.util.component import LabeledComponent


class PacketTraceRunner(LabeledComponent):
    def __init__(
        self,
        pcap_file: str,
        switch_host: str,
        switch_port: int,
        trace_switch_port: int,
        trace_device_port: int,
        label: str = None,
    ):
        super().__init__(label)
        self._pcap_file = pcap_file
        self._switch_port = switch_port
        self._switch_host = switch_host
        self._trace_switch_port = trace_switch_port
        self._trace_device_port = trace_device_port

    async def run(self):
        try:
            reader, writer = await asyncio.open_connection(self._switch_host, self._switch_port)
        except Exception as e:
            raise RuntimeError("Failed to connect to switch") from e

        local_ip, local_port = writer.get_extra_info("sockname")
        logger.info(self._create_message(f"Local address: {local_ip}, Local port: {local_port}"))

        with PcapReader(self._pcap_file) as pr:
            for n, packet in enumerate(pr):
                if packet.haslayer("TCP") and packet["TCP"].flags == 0x18:
                    tcp = packet.getlayer("TCP")
                    data_bytes = bytes(tcp.payload)
                    data = int.from_bytes(data_bytes)
                    if (
                        tcp.sport == self._trace_device_port
                        and tcp.dport == self._trace_switch_port
                    ):
                        logger.info(self._create_message(f"({n + 1}) Tx: 0x{data:x}"))
                        writer.write(data_bytes)
                        await writer.drain()
                    elif (
                        tcp.sport == self._trace_switch_port
                        and tcp.dport == self._trace_device_port
                    ):
                        try:
                            recv_data_bytes = await asyncio.wait_for(
                                reader.read(len(data_bytes)), timeout=5
                            )
                        except TimeoutError as e:
                            raise ValueError(f"Timed out waiting for Packet {n+1}") from e

                        recv_data = int.from_bytes(recv_data_bytes, "big")
                        logger.info(self._create_message(f"({n + 1}) Rx: 0x{recv_data:x}"))
                        if recv_data != data:
                            logger.error(self._create_message("Packet Trace Mismatch detected."))
                            raise ValueError(
                                f"Packet {n + 1}\n  Expected (in BE): 0x{data:x}\n"
                                f"  Received (in BE): 0x{recv_data:x}"
                            )
        writer.close()
        logger.info("The packet trace run finished successfully!")
