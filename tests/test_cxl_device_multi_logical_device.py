"""
 Copyright (c) 2024, Eeum, Inc.

 This software is licensed under the terms of the Revised BSD License.
 See LICENSE for details.
"""

from asyncio import create_task
import asyncio
import struct
from typing import cast
import pytest

from opencis.apps.multi_logical_device import MultiLogicalDevice
from opencis.cxl.component.common import CXL_COMPONENT_TYPE
from opencis.cxl.component.cxl_packet_processor import CxlPacketProcessor
from opencis.cxl.component.packet_reader import PacketReader
from opencis.cxl.component.cxl_connection import CxlConnection
from opencis.pci.component.pci import EEUM_VID, SW_MLD_DID
from opencis.util.number_const import MB
from opencis.util.logger import logger
from opencis.util.pci import create_bdf
from opencis.cxl.transport.transaction import (
    CxlIoCfgRdPacket,
    CxlIoMemRdPacket,
    CxlIoMemWrPacket,
    CxlIoCfgWrPacket,
    CxlMemMemRdPacket,
    CxlMemMemWrPacket,
    CxlIoCompletionWithDataPacket,
    is_cxl_io_completion_status_sc,
    is_cxl_io_completion_status_ur,
)


# Test ld_id
# TODO: Test ld_id value from return (read) packets
@pytest.mark.asyncio
async def test_multi_logical_device_ld_id():
    # Test 4 LDs
    ld_count = 4
    # Test routing to LD-ID 2
    target_ld_id = 2
    ld_size = 256 * MB
    logger.info(f"[PyTest] Creating {ld_count} LDs, testing LD-ID routing to {target_ld_id}")

    # Create MLD instance
    cxl_connections = [CxlConnection() for _ in range(ld_count)]
    mld = MultiLogicalDevice(
        port_index=1,
        memory_sizes=[ld_size] * ld_count,
        memory_files=[f"mld_mem{i}.bin" for i in range(ld_count)],
        serial_numbers=["CCCCCCCCCCCCCCCC"] * ld_count,
        test_mode=True,
        cxl_connections=cxl_connections,
    )

    # Start MLD pseudo server
    async def handle_client(reader, writer):
        global mld_pseudo_server_reader, mld_pseudo_server_packet_reader, mld_pseudo_server_writer  # pylint: disable=global-variable-undefined
        mld_pseudo_server_reader = reader
        mld_pseudo_server_packet_reader = PacketReader(reader, label="test_mmio")
        mld_pseudo_server_writer = writer
        assert mld_pseudo_server_writer is not None, "mld_pseudo_server_writer is NoneType"

    server = await asyncio.start_server(handle_client, "127.0.0.1", 8000)
    # This is cleaned up via 'server.wait_closed()' below
    asyncio.create_task(server.serve_forever())
    while not server.is_serving():
        await asyncio.sleep(0.1)

    # Setup CxlPacketProcessor for MLD - connect to 127.0.0.1:8000
    mld_packet_processor_reader, mld_packet_processor_writer = await asyncio.open_connection(
        "127.0.0.1", 8000
    )
    mld_packet_processor = CxlPacketProcessor(
        mld_packet_processor_reader,
        mld_packet_processor_writer,
        cxl_connections,
        CXL_COMPONENT_TYPE.LD,
        label="ClientPortMld",
    )
    mld_packet_processor_task = create_task(mld_packet_processor.run())
    await mld_packet_processor.wait_for_ready()

    memory_base_address = 0xFE000000
    bar_size = 131072  # Empirical value

    async def configure_bar(
        target_ld_id: int, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ):
        packet_reader = PacketReader(reader, label="configure_bar")
        packet_writer = writer

        logger.info("[PyTest] Settting Bar Address")
        # NOTE: Test Config Space Type0 Write - BAR WRITE
        packet = CxlIoCfgWrPacket.create(
            create_bdf(0, 0, 0),
            0x10,
            4,
            value=memory_base_address,
            is_type0=True,
            ld_id=target_ld_id,
        )
        packet_writer.write(bytes(packet))
        await packet_writer.drain()
        packet = await packet_reader.get_packet()
        assert packet.tlp_prefix.ld_id == target_ld_id
        assert is_cxl_io_completion_status_sc(packet)

    async def test_config_space(
        target_ld_id: int, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ):
        # pylint: disable=duplicate-code
        packet_reader = PacketReader(reader, label="test_config_space")
        packet_writer = writer

        # NOTE: Test Config Space Type0 Read - VID/DID
        logger.info("[PyTest] Testing Config Space Type0 Read (VID/DID)")
        packet = CxlIoCfgRdPacket.create(
            create_bdf(0, 0, 0), 0, 4, is_type0=True, ld_id=target_ld_id
        )
        packet_writer.write(bytes(packet))
        await packet_writer.drain()
        packet = await packet_reader.get_packet()
        assert packet.tlp_prefix.ld_id == target_ld_id
        assert is_cxl_io_completion_status_sc(packet)
        cpld_packet = cast(CxlIoCompletionWithDataPacket, packet)
        assert cpld_packet.data == (EEUM_VID | (SW_MLD_DID << 16))

        # NOTE: Test Config Space Type0 Write - BAR WRITE
        logger.info("[PyTest] Testing Config Space Type0 Write (BAR)")
        packet = CxlIoCfgWrPacket.create(
            create_bdf(0, 0, 0), 0x10, 4, 0xFFFFFFFF, is_type0=True, ld_id=target_ld_id
        )
        packet_writer.write(bytes(packet))
        await packet_writer.drain()
        packet = await packet_reader.get_packet()
        assert packet.tlp_prefix.ld_id == target_ld_id
        assert is_cxl_io_completion_status_sc(packet)

        # NOTE: Test Config Space Type0 Read - BAR READ
        logger.info("[PyTest] Testing Config Space Type0 Read (BAR)")
        packet = CxlIoCfgRdPacket.create(
            create_bdf(0, 0, 0), 0x10, 4, is_type0=True, ld_id=target_ld_id
        )
        packet_writer.write(bytes(packet))
        await packet_writer.drain()
        packet = await packet_reader.get_packet()
        assert packet.tlp_prefix.ld_id == target_ld_id
        assert is_cxl_io_completion_status_sc(packet)
        cpld_packet = cast(CxlIoCompletionWithDataPacket, packet)
        size = 0xFFFFFFFF - cpld_packet.data + 1
        assert size == bar_size

        # NOTE: Test Config Space Type1 Read - VID/DID: Expect UR
        logger.info("[PyTest] Testing Config Space Type1 Read - Expect UR")
        packet = CxlIoCfgRdPacket.create(
            create_bdf(0, 0, 0), 0, 4, is_type0=False, ld_id=target_ld_id
        )
        packet_writer.write(bytes(packet))
        await packet_writer.drain()
        packet = await packet_reader.get_packet()
        assert packet.tlp_prefix.ld_id == target_ld_id
        assert is_cxl_io_completion_status_ur(packet)

        # NOTE: Test Config Space Type1 Write - BAR WRITE: Expect UR
        logger.info("[PyTest] Testing Config Space Type1 Write - Expect UR")
        packet = CxlIoCfgWrPacket.create(
            create_bdf(0, 0, 0), 0x10, 4, 0xFFFFFFFF, is_type0=False, ld_id=target_ld_id
        )
        packet_writer.write(bytes(packet))
        await packet_writer.drain()
        packet = await packet_reader.get_packet()
        assert packet.tlp_prefix.ld_id == target_ld_id
        assert is_cxl_io_completion_status_ur(packet)

    async def setup_hdm_decoder(
        ld_count: int, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ):
        # pylint: disable=duplicate-code
        packet_reader = PacketReader(reader, label="setup_hdm_decoder")
        packet_writer = writer

        register_offset = memory_base_address + 0x1014
        decoder_index = 0
        hpa_base = 0x0
        hpa_size = ld_size
        dpa_skip = 0
        interleaving_granularity = 0
        interleaving_way = 0

        for ld_id in range(ld_count):
            # NOTE: Test Config Space Type0 Write - BAR WRITE
            packet = CxlIoCfgWrPacket.create(
                create_bdf(0, 0, 0),
                0x10,
                4,
                value=register_offset,
                is_type0=True,
                ld_id=ld_id,
            )
            packet_writer.write(bytes(packet))
            await packet_writer.drain()
            packet = await packet_reader.get_packet()
            assert is_cxl_io_completion_status_sc(packet)
            assert packet.tlp_prefix.ld_id == ld_id

            # Use HPA = DPA
            logger.info(f"[PyTest] Setting up HDM Decoder for {ld_id}")

            dpa_skip_low_offset = 0x20 * decoder_index + 0x24 + register_offset
            dpa_skip_high_offset = 0x20 * decoder_index + 0x28 + register_offset
            dpa_skip_low = dpa_skip & 0xFFFFFFFF
            dpa_skip_high = (dpa_skip >> 32) & 0xFFFFFFFF

            packet = CxlIoMemWrPacket.create(dpa_skip_low_offset, 4, dpa_skip_low, ld_id=ld_id)
            writer.write(bytes(packet))
            await writer.drain()

            packet = CxlIoMemWrPacket.create(dpa_skip_high_offset, 4, dpa_skip_high, ld_id=ld_id)
            writer.write(bytes(packet))
            await writer.drain()

            decoder_base_low_offset = 0x20 * decoder_index + 0x10 + register_offset
            decoder_base_high_offset = 0x20 * decoder_index + 0x14 + register_offset
            decoder_size_low_offset = 0x20 * decoder_index + 0x18 + register_offset
            decoder_size_high_offset = 0x20 * decoder_index + 0x1C + register_offset
            decoder_control_register_offset = 0x20 * decoder_index + 0x20 + register_offset

            commit = 1

            decoder_base_low = hpa_base & 0xFFFFFFFF
            decoder_base_high = (hpa_base >> 32) & 0xFFFFFFFF
            decoder_size_low = hpa_size & 0xFFFFFFFF
            decoder_size_high = (hpa_size >> 32) & 0xFFFFFFFF

            decoder_control = (
                interleaving_granularity & 0xF | (interleaving_way & 0xF) << 4 | commit << 9
            )

            packet = CxlIoMemWrPacket.create(
                decoder_base_low_offset, 4, decoder_base_low, ld_id=ld_id
            )
            writer.write(bytes(packet))
            await writer.drain()

            packet = CxlIoMemWrPacket.create(
                decoder_base_high_offset, 4, decoder_base_high, ld_id=ld_id
            )
            writer.write(bytes(packet))
            await writer.drain()

            packet = CxlIoMemWrPacket.create(
                decoder_size_low_offset, 4, decoder_size_low, ld_id=ld_id
            )
            writer.write(bytes(packet))
            await writer.drain()

            packet = CxlIoMemWrPacket.create(
                decoder_size_high_offset, 4, decoder_size_high, ld_id=ld_id
            )
            writer.write(bytes(packet))
            await writer.drain()

            packet = CxlIoMemWrPacket.create(
                decoder_control_register_offset, 4, decoder_control, ld_id=ld_id
            )
            writer.write(bytes(packet))
            await writer.drain()

            register_offset += 0x200000

        logger.info("[PyTest] HDM Decoder setup complete")

    async def test_mmio(
        target_ld_id: int, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ):
        packet_reader = PacketReader(reader, label="test_mmio")
        packet_writer = writer

        logger.info("[PyTest] Accessing MMIO register")

        # NOTE: Write 0xDEADBEEF
        data = 0xDEADBEEF
        packet = CxlIoMemWrPacket.create(memory_base_address, 4, data=data, ld_id=target_ld_id)
        packet_writer.write(bytes(packet))
        await packet_writer.drain()

        # NOTE: Confirm 0xDEADBEEF is written
        packet = CxlIoMemRdPacket.create(memory_base_address, 4, ld_id=target_ld_id)
        packet_writer.write(bytes(packet))
        await packet_writer.drain()
        packet = await packet_reader.get_packet()
        assert is_cxl_io_completion_status_sc(packet)
        assert packet.tlp_prefix.ld_id == target_ld_id
        cpld_packet = cast(CxlIoCompletionWithDataPacket, packet)
        logger.info(f"[PyTest] Received CXL.io packet: {cpld_packet}")
        assert cpld_packet.data == data

        # NOTE: Write OOB (Upper Boundary), Expect No Error
        packet = CxlIoMemWrPacket.create(
            memory_base_address + bar_size, 4, data=data, ld_id=target_ld_id
        )
        packet_writer.write(bytes(packet))
        await packet_writer.drain()

        # NOTE: Write OOB (Lower Boundary), Expect No Error
        packet = CxlIoMemWrPacket.create(memory_base_address - 4, 4, data=data, ld_id=target_ld_id)
        packet_writer.write(bytes(packet))
        await packet_writer.drain()

        # NOTE: Read OOB (Upper Boundary), Expect 0
        packet = CxlIoMemRdPacket.create(memory_base_address + bar_size, 4, ld_id=target_ld_id)
        packet_writer.write(bytes(packet))
        await packet_writer.drain()
        packet = await packet_reader.get_packet()
        assert is_cxl_io_completion_status_sc(packet)
        assert packet.tlp_prefix.ld_id == target_ld_id
        cpld_packet = cast(CxlIoCompletionWithDataPacket, packet)
        assert cpld_packet.data == 0

        # NOTE: Read OOB (Lower Boundary), Expect 0
        packet = CxlIoMemRdPacket.create(memory_base_address - 4, 4, ld_id=target_ld_id)
        packet_writer.write(bytes(packet))
        await packet_writer.drain()
        packet = await packet_reader.get_packet()
        assert is_cxl_io_completion_status_sc(packet)
        assert packet.tlp_prefix.ld_id == target_ld_id
        cpld_packet = cast(CxlIoCompletionWithDataPacket, packet)
        assert cpld_packet.data == 0

    async def send_packets(
        target_ld_id: int, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ):
        packet_reader = PacketReader(reader, label="send_packets")
        packet_writer = writer

        target_address = 0x80
        target_data = 0xDEADBEEF

        logger.info("[PyTest] Sending CXL.mem request packets from client")
        packet = CxlMemMemWrPacket.create(target_address, target_data, ld_id=target_ld_id)
        packet_writer.write(bytes(packet))
        await packet_writer.drain()
        packet = await packet_reader.get_packet()
        assert packet.s2mndr_header.ld_id == target_ld_id

        packet = CxlMemMemRdPacket.create(target_address, ld_id=target_ld_id)
        packet_writer.write(bytes(packet))
        await packet_writer.drain()

        logger.info("[PyTest] Checking CXL.mem request packets received from server")
        packet = await packet_reader.get_packet()
        assert packet.s2mdrs_header.ld_id == target_ld_id
        mem_packet = cast(CxlMemMemRdPacket, packet)
        logger.info(f"[PyTest] Received CXL.mem packet: {hex(mem_packet.data)}")
        assert mem_packet.data == target_data

        # Check MLD bin file
        logger.info("[PyTest] Checking MLD bin file")
        with open(f"mld_mem{target_ld_id}.bin", "rb") as f:
            f.seek(target_address)
            data = f.read(4)
            value = struct.unpack("<I", data)[0]
            assert value == target_data

    # Start MLD
    mld_task = create_task(mld.run())

    # Start the tests
    await mld.wait_for_ready()
    # Test MLD LD-ID handling
    await setup_hdm_decoder(ld_count, mld_pseudo_server_reader, mld_pseudo_server_writer)
    await configure_bar(target_ld_id, mld_pseudo_server_reader, mld_pseudo_server_writer)
    await test_config_space(target_ld_id, mld_pseudo_server_reader, mld_pseudo_server_writer)
    await test_mmio(target_ld_id, mld_pseudo_server_reader, mld_pseudo_server_writer)
    await send_packets(target_ld_id, mld_pseudo_server_reader, mld_pseudo_server_writer)

    # Stop all devices
    await mld_packet_processor.stop()
    await mld_packet_processor_task
    await mld.stop()
    await mld_task

    # Stop pseudo server
    server.close()
    await server.wait_closed()
