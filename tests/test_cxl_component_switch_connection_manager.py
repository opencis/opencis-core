"""
 Copyright (c) 2024, Eeum, Inc.

 This software is licensed under the terms of the Revised BSD License.
 See LICENSE for details.
"""

from asyncio import gather, create_task
import pytest

from opencis.util.logger import logger
from opencis.cxl.component.switch_connection_manager import (
    SwitchConnectionManager,
    CxlConnection,
)
from opencis.cxl.component.switch_connection_client import (
    SwitchConnectionClient,
    INJECTED_ERRORS,
)
from opencis.cxl.component.cxl_component import (
    PortConfig,
    PORT_TYPE,
)
from opencis.cxl.component.common import CXL_COMPONENT_TYPE
from opencis.util.pci import create_bdf
from opencis.cxl.transport.transaction import (
    CxlIoCfgRdPacket,
    CxlIoCfgWrPacket,
    CxlIoMemRdPacket,
    CxlIoMemWrPacket,
    CxlIoCompletionWithDataPacket,
    CxlMemMemRdPacket,
    CxlMemMemWrPacket,
    CxlMemMemDataPacket,
    CxlMemBIRspPacket,
    CxlMemBISnpPacket,
    CxlMemCmpPacket,
    CXL_IO_CPL_STATUS,
    CXL_MEM_M2SBIRSP_OPCODE,
    CXL_MEM_S2MBISNP_OPCODE,
)


BASE_TEST_PORT = 9100


def test_switch_connection_manager_check_ports():
    port_configs = [
        PortConfig(PORT_TYPE.USP),
        PortConfig(PORT_TYPE.USP),
        PortConfig(PORT_TYPE.DSP),
        PortConfig(PORT_TYPE.DSP),
    ]
    port = BASE_TEST_PORT + pytest.PORT.TEST_1
    manager = SwitchConnectionManager(port_configs, port=port)
    for port in range(len(port_configs)):
        connection = manager.get_cxl_connection(port)
        assert isinstance(connection, CxlConnection)
    with pytest.raises(Exception):
        manager.get_cxl_connection(len(port_configs))


@pytest.mark.asyncio
async def test_switch_connection_manager_run_and_stop():
    port_configs = [
        PortConfig(PORT_TYPE.USP),
        PortConfig(PORT_TYPE.USP),
        PortConfig(PORT_TYPE.DSP),
        PortConfig(PORT_TYPE.DSP),
    ]
    port = BASE_TEST_PORT + pytest.PORT.TEST_2
    manager = SwitchConnectionManager(port_configs, port=port)

    async def wait_and_stop():
        await manager.wait_for_ready()
        await manager.stop()

    tasks = [create_task(wait_and_stop()), create_task(manager.run())]
    await gather(*tasks)


@pytest.mark.asyncio
async def test_switch_connection_manager_run_and_run():
    port_configs = [
        PortConfig(PORT_TYPE.USP),
        PortConfig(PORT_TYPE.USP),
        PortConfig(PORT_TYPE.DSP),
        PortConfig(PORT_TYPE.DSP),
    ]
    port = BASE_TEST_PORT + pytest.PORT.TEST_3
    manager = SwitchConnectionManager(port_configs, port=port)

    async def wait_and_run():
        await manager.wait_for_ready()
        with pytest.raises(Exception, match="Cannot run when it is not stopped"):
            await manager.run()
        await manager.stop()

    tasks = [create_task(manager.run()), create_task(wait_and_run())]
    await gather(*tasks)


@pytest.mark.asyncio
async def test_switch_connection_manager_stop_before_run():
    port_configs = [
        PortConfig(PORT_TYPE.USP),
        PortConfig(PORT_TYPE.USP),
        PortConfig(PORT_TYPE.DSP),
        PortConfig(PORT_TYPE.DSP),
    ]
    port = BASE_TEST_PORT + pytest.PORT.TEST_4
    manager = SwitchConnectionManager(port_configs, port=port)

    with pytest.raises(Exception, match="Cannot stop when it is not running"):
        await manager.stop()


@pytest.mark.asyncio
async def test_switch_connection_manager_handle_connection():
    port_configs = [
        PortConfig(PORT_TYPE.USP),
        PortConfig(PORT_TYPE.USP),
        PortConfig(PORT_TYPE.DSP),
        PortConfig(PORT_TYPE.DSP),
    ]
    port = BASE_TEST_PORT + pytest.PORT.TEST_5
    manager = SwitchConnectionManager(port_configs, port=port)
    client = SwitchConnectionClient(
        port_index=0, component_type=CXL_COMPONENT_TYPE.R, retry=False, port=port
    )

    async def start():
        logger.info("[PyTest] Starting SwitchConnectionManager")
        await manager.run()

    async def wait_and_connect():
        await manager.wait_for_ready()
        logger.info("[PyTest] SwitchConnectionManager is ready")
        logger.info("[PyTest] Starting SwitchConnectionClient")
        await client.run()

    async def stop():
        await client.wait_for_ready()
        logger.info("[PyTest] SwitchConnectionClient is ready")
        logger.info("[PyTest] Stopping SwitchConnectionManager")
        await manager.stop()
        logger.info("[PyTest] Stopping SwitchConnectionClient")
        await client.stop()

    tasks = [
        create_task(start()),
        create_task(wait_and_connect()),
        create_task(stop()),
    ]
    await gather(*tasks)


@pytest.mark.asyncio
async def test_switch_connection_manager_handle_connection_oob():
    port_configs = [
        PortConfig(PORT_TYPE.USP),
        PortConfig(PORT_TYPE.USP),
        PortConfig(PORT_TYPE.DSP),
        PortConfig(PORT_TYPE.DSP),
    ]
    port = BASE_TEST_PORT + pytest.PORT.TEST_6
    manager = SwitchConnectionManager(port_configs, port=port)
    client = SwitchConnectionClient(
        port_index=4, component_type=CXL_COMPONENT_TYPE.R, retry=False, port=port
    )

    async def start():
        logger.info("[PyTest] Starting SwitchConnectionManager")
        await manager.run()

    async def wait_and_connect():
        await manager.wait_for_ready()
        logger.info("[PyTest] SwitchConnectionManager is ready")
        logger.info("[PyTest] Starting SwitchConnectionClient")
        with pytest.raises(Exception, match="Connection rejected"):
            await client.run()
        await manager.stop()

    tasks = [
        create_task(start()),
        create_task(wait_and_connect()),
    ]

    await gather(*tasks)


@pytest.mark.asyncio
async def test_switch_connection_manager_handle_connection_after_connection():
    # pylint: disable=protected-access
    port_configs = [
        PortConfig(PORT_TYPE.USP),
        PortConfig(PORT_TYPE.USP),
        PortConfig(PORT_TYPE.DSP),
        PortConfig(PORT_TYPE.DSP),
    ]
    port = BASE_TEST_PORT + pytest.PORT.TEST_7
    manager = SwitchConnectionManager(port_configs, port=port)
    client = SwitchConnectionClient(
        port_index=0, component_type=CXL_COMPONENT_TYPE.R, retry=False, port=port
    )

    async def start():
        logger.info("[PyTest] Starting SwitchConnectionManager")
        await manager.run()

    async def wait_and_connect():
        await manager.wait_for_ready()
        logger.info("[PyTest] SwitchConnectionManager is ready")
        logger.info("[PyTest] Starting SwitchConnectionClient")
        await client.run()

    async def stop():
        await client.wait_for_ready()
        logger.info("[PyTest] SwitchConnectionClient is ready")
        with pytest.raises(Exception, match="Connection rejected"):
            await client._connect()
        logger.info("[PyTest] Stopping SwitchConnectionManager")
        await manager.stop()
        logger.info("[PyTest] Stopping SwitchConnectionClient")
        await client.stop()

    tasks = [
        create_task(start()),
        create_task(wait_and_connect()),
        create_task(stop()),
    ]
    await gather(*tasks)


@pytest.mark.asyncio
async def test_switch_connection_manager_handle_connection_errors():
    # pylint: disable=function-redefined
    port_configs = [
        PortConfig(PORT_TYPE.USP),
        PortConfig(PORT_TYPE.USP),
        PortConfig(PORT_TYPE.DSP),
        PortConfig(PORT_TYPE.DSP),
    ]
    port = BASE_TEST_PORT + pytest.PORT.TEST_8
    manager = SwitchConnectionManager(port_configs, port=port)
    client = SwitchConnectionClient(
        port_index=0, component_type=CXL_COMPONENT_TYPE.R, retry=False, port=port
    )

    async def start():
        logger.info("[PyTest] Starting SwitchConnectionManager")
        await manager.run()

    async def wait_and_connect():
        await manager.wait_for_ready()
        logger.info("[PyTest] SwitchConnectionManager is ready")
        logger.info("[PyTest] Starting SwitchConnectionClient")
        await client.run()

    async def wait_and_connect():
        await manager.wait_for_ready()
        with pytest.raises(Exception, match="Connection rejected"):
            client.inject_error(INJECTED_ERRORS.NON_SIDEBAND)
            await client.run()
        with pytest.raises(Exception, match="Connection rejected"):
            client.inject_error(INJECTED_ERRORS.NON_CONNNECTION_REQUEST)
            await client.run()
        await manager.stop()

    tasks = [create_task(start()), create_task(wait_and_connect())]
    await gather(*tasks)


@pytest.mark.asyncio
async def test_switch_connection_manager_handle_cfg_packet():
    port_configs = [
        PortConfig(PORT_TYPE.USP),
        PortConfig(PORT_TYPE.USP),
        PortConfig(PORT_TYPE.DSP),
        PortConfig(PORT_TYPE.DSP),
    ]
    port = BASE_TEST_PORT + pytest.PORT.TEST_9
    manager = SwitchConnectionManager(port_configs, port=port)
    client = SwitchConnectionClient(
        port_index=0, component_type=CXL_COMPONENT_TYPE.R, retry=False, port=port
    )

    async def start():
        logger.info("[PyTest] Starting SwitchConnectionManager")
        await manager.run()

    async def wait_and_connect():
        await manager.wait_for_ready()
        logger.info("[PyTest] SwitchConnectionManager is ready")
        logger.info("[PyTest] Starting SwitchConnectionClient")
        await client.run()

    async def send_packets_and_stop():
        await client.wait_for_ready()
        logger.info("[PyTest] SwitchConnectionClient is ready")
        logger.info("[PyTest] Sending config space request packets from client")
        client_connection = client.get_cxl_connection()
        packet = CxlIoCfgWrPacket.create(create_bdf(0, 0, 0), 0x10, 4, 0xDEADBEEF)
        await client_connection.cfg_fifo.host_to_target.put(packet)
        packet = CxlIoCfgRdPacket.create(create_bdf(0, 0, 0), 0x10, 4)
        await client_connection.cfg_fifo.host_to_target.put(packet)

        logger.info("[PyTest] Checking config space request packets received from server")
        server_connection = manager.get_cxl_connection(0)
        await server_connection.cfg_fifo.host_to_target.get()
        await server_connection.cfg_fifo.host_to_target.get()

        logger.info("[PyTest] Stopping SwitchConnectionManager")
        await manager.stop()
        logger.info("[PyTest] Stopping SwitchConnectionClient")
        await client.stop()

    tasks = [
        create_task(start()),
        create_task(wait_and_connect()),
        create_task(send_packets_and_stop()),
    ]
    await gather(*tasks)


@pytest.mark.asyncio
async def test_switch_connection_manager_handle_mmio_packet():
    port_configs = [
        PortConfig(PORT_TYPE.USP),
        PortConfig(PORT_TYPE.USP),
        PortConfig(PORT_TYPE.DSP),
        PortConfig(PORT_TYPE.DSP),
    ]
    port = BASE_TEST_PORT + pytest.PORT.TEST_10
    manager = SwitchConnectionManager(port_configs, port=port)
    client = SwitchConnectionClient(
        port_index=0, component_type=CXL_COMPONENT_TYPE.R, retry=False, port=port
    )

    async def start():
        logger.info("[PyTest] Starting SwitchConnectionManager")
        await manager.run()

    async def wait_and_connect():
        await manager.wait_for_ready()
        logger.info("[PyTest] SwitchConnectionManager is ready")
        logger.info("[PyTest] Starting SwitchConnectionClient")
        await client.run()

    async def send_packets_and_stop():
        await client.wait_for_ready()
        logger.info("[PyTest] SwitchConnectionClient is ready")
        logger.info("[PyTest] Sending MMIO request packets from client")
        client_connection = client.get_cxl_connection()
        packet = CxlIoMemWrPacket.create(0, 4, 0)
        await client_connection.mmio_fifo.host_to_target.put(packet)
        packet = CxlIoMemRdPacket.create(0, 4)
        await client_connection.mmio_fifo.host_to_target.put(packet)

        logger.info("[PyTest] Checking MMIO request packets received from server")
        server_connection = manager.get_cxl_connection(0)
        await server_connection.mmio_fifo.host_to_target.get()

        logger.info("[PyTest] Stopping SwitchConnectionManager")
        await manager.stop()
        logger.info("[PyTest] Stopping SwitchConnectionClient")
        await client.stop()

    tasks = [
        create_task(start()),
        create_task(wait_and_connect()),
        create_task(send_packets_and_stop()),
    ]
    await gather(*tasks)


@pytest.mark.asyncio
async def test_switch_connection_manager_handle_cxl_mem_packet_m2s():
    port_configs = [
        PortConfig(PORT_TYPE.USP),
        PortConfig(PORT_TYPE.USP),
        PortConfig(PORT_TYPE.DSP),
        PortConfig(PORT_TYPE.DSP),
    ]
    port = BASE_TEST_PORT + pytest.PORT.TEST_11
    manager = SwitchConnectionManager(port_configs, port=port)
    client = SwitchConnectionClient(
        port_index=0, component_type=CXL_COMPONENT_TYPE.R, retry=False, port=port
    )

    async def start():
        logger.info("[PyTest] Starting SwitchConnectionManager")
        await manager.run()

    async def wait_and_connect():
        await manager.wait_for_ready()
        logger.info("[PyTest] SwitchConnectionManager is ready")
        logger.info("[PyTest] Starting SwitchConnectionClient")
        await client.run()

    async def send_packets_and_stop():
        await client.wait_for_ready()
        logger.info("[PyTest] SwitchConnectionClient is ready")
        logger.info("[PyTest] Sending CXL.mem request packets from client")
        client_connection = client.get_cxl_connection()
        packet = CxlMemMemWrPacket.create(0x80, 0xDEADBEEF)
        await client_connection.cxl_mem_fifo.host_to_target.put(packet)
        packet = CxlMemMemRdPacket.create(0x80)
        await client_connection.cxl_mem_fifo.host_to_target.put(packet)
        packet = CxlMemBIRspPacket.create(CXL_MEM_M2SBIRSP_OPCODE.BIRSP_E, 0, 0)
        await client_connection.cxl_mem_fifo.host_to_target.put(packet)

        logger.info("[PyTest] Checking CXL.mem request packets received from server")
        server_connection = manager.get_cxl_connection(0)
        await server_connection.cxl_mem_fifo.host_to_target.get()

        logger.info("[PyTest] Stopping SwitchConnectionManager")
        await manager.stop()
        logger.info("[PyTest] Stopping SwitchConnectionClient")
        await client.stop()

    tasks = [
        create_task(start()),
        create_task(wait_and_connect()),
        create_task(send_packets_and_stop()),
    ]
    await gather(*tasks)


@pytest.mark.asyncio
async def test_switch_connection_manager_handle_cfg_completion():
    port_configs = [
        PortConfig(PORT_TYPE.USP),
        PortConfig(PORT_TYPE.USP),
        PortConfig(PORT_TYPE.DSP),
        PortConfig(PORT_TYPE.DSP),
    ]
    port = BASE_TEST_PORT + pytest.PORT.TEST_12
    manager = SwitchConnectionManager(port_configs, port=port)
    client = SwitchConnectionClient(
        port_index=0, component_type=CXL_COMPONENT_TYPE.R, retry=False, port=port
    )

    async def start():
        logger.info("[PyTest] Starting SwitchConnectionManager")
        await manager.run()

    async def wait_and_connect():
        await manager.wait_for_ready()
        logger.info("[PyTest] SwitchConnectionManager is ready")
        logger.info("[PyTest] Starting SwitchConnectionClient")
        await client.run()

    async def send_packets_and_stop():
        await client.wait_for_ready()
        logger.info("[PyTest] SwitchConnectionClient is ready")
        logger.info("[PyTest] Sending config space completion packets from server")
        server_connection = manager.get_cxl_connection(0)
        client_connection = client.get_cxl_connection()
        req_id = 0x10
        tag = 0xA5
        req1 = CxlIoCfgWrPacket.create(0, 0x10, 4, 0xDEADBEEF, req_id=req_id, tag=tag)
        await client_connection.cfg_fifo.host_to_target.put(req1)

        cpl_id = 0x20
        tag = 0xA6
        req2 = CxlIoCfgRdPacket.create(0, 0x10, 4, req_id=req_id, tag=tag)
        await client_connection.cfg_fifo.host_to_target.put(req2)
        cpl2 = CxlIoCompletionWithDataPacket.create(
            req_id=req_id, tag=tag, status=CXL_IO_CPL_STATUS.SC, data=0xDEADBEEF, cpl_id=cpl_id
        )
        await server_connection.cfg_fifo.target_to_host.put(cpl2)

        logger.info("[PyTest] Checking config space completion packets received from client")
        rcvd_packets = []
        rcvd_packets.append(await client_connection.cfg_fifo.host_to_target.get())
        rcvd_packets.append(await client_connection.cfg_fifo.host_to_target.get())
        rcvd_packets.append(await server_connection.cfg_fifo.target_to_host.get())

        assert bytes(rcvd_packets[0]) == bytes(req1)
        assert bytes(rcvd_packets[1]) == bytes(req2)
        assert bytes(rcvd_packets[2]) == bytes(cpl2)

        logger.info("[PyTest] Stopping SwitchConnectionManager")
        await manager.stop()
        logger.info("[PyTest] Stopping SwitchConnectionClient")
        await client.stop()

    tasks = [
        create_task(start()),
        create_task(wait_and_connect()),
        create_task(send_packets_and_stop()),
    ]
    await gather(*tasks)


@pytest.mark.asyncio
async def test_switch_connection_manager_handle_mmio_completion():
    port_configs = [
        PortConfig(PORT_TYPE.USP),
        PortConfig(PORT_TYPE.USP),
        PortConfig(PORT_TYPE.DSP),
        PortConfig(PORT_TYPE.DSP),
    ]
    port = BASE_TEST_PORT + pytest.PORT.TEST_13
    manager = SwitchConnectionManager(port_configs, port=port)
    client = SwitchConnectionClient(
        port_index=0, component_type=CXL_COMPONENT_TYPE.R, retry=False, port=port
    )

    async def start():
        logger.info("[PyTest] Starting SwitchConnectionManager")
        await manager.run()

    async def wait_and_connect():
        await manager.wait_for_ready()
        logger.info("[PyTest] SwitchConnectionManager is ready")
        logger.info("[PyTest] Starting SwitchConnectionClient")
        await client.run()

    async def send_packets_and_stop():
        await client.wait_for_ready()
        logger.info("[PyTest] SwitchConnectionClient is ready")
        logger.info("[PyTest] Sending MMIO completion packets from server")
        server_connection = manager.get_cxl_connection(0)
        client_connection = client.get_cxl_connection()

        req_id = 0x10
        tag = 0x1
        req1 = CxlIoMemWrPacket.create(0x10, 4, 0xDEADBEEF, req_id=req_id, tag=tag)
        await client_connection.mmio_fifo.host_to_target.put(req1)

        cpl_id = 0x20
        tag = 0x2
        req2 = CxlIoMemRdPacket.create(0x10, 4, req_id=req_id, tag=tag)
        await client_connection.mmio_fifo.host_to_target.put(req2)
        cpl2 = CxlIoCompletionWithDataPacket.create(
            req_id=req_id, tag=tag, data=0xA5A5, cpl_id=cpl_id
        )
        await server_connection.mmio_fifo.target_to_host.put(cpl2)

        logger.info("[PyTest] Checking MMIO completion packets received from client")
        rcvd_packets = []
        rcvd_packets.append(await client_connection.mmio_fifo.host_to_target.get())  # wr
        rcvd_packets.append(await client_connection.mmio_fifo.host_to_target.get())  # rd
        rcvd_packets.append(await server_connection.mmio_fifo.target_to_host.get())  # cpld

        assert bytes(rcvd_packets[0]) == bytes(req1)
        assert bytes(rcvd_packets[1]) == bytes(req2)
        assert bytes(rcvd_packets[2]) == bytes(cpl2)

        logger.info("[PyTest] Stopping SwitchConnectionManager")
        await manager.stop()
        logger.info("[PyTest] Stopping SwitchConnectionClient")
        await client.stop()

    tasks = [
        create_task(start()),
        create_task(wait_and_connect()),
        create_task(send_packets_and_stop()),
    ]
    await gather(*tasks)


@pytest.mark.asyncio
async def test_switch_connection_manager_handle_cxl_mem_s2m():
    port_configs = [
        PortConfig(PORT_TYPE.USP),
        PortConfig(PORT_TYPE.USP),
        PortConfig(PORT_TYPE.DSP),
        PortConfig(PORT_TYPE.DSP),
    ]
    port = BASE_TEST_PORT + pytest.PORT.TEST_14
    manager = SwitchConnectionManager(port_configs, port=port)
    client = SwitchConnectionClient(
        port_index=0, component_type=CXL_COMPONENT_TYPE.R, retry=False, port=port
    )

    async def start():
        logger.info("[PyTest] Starting SwitchConnectionManager")
        await manager.run()

    async def wait_and_connect():
        await manager.wait_for_ready()
        logger.info("[PyTest] SwitchConnectionManager is ready")
        logger.info("[PyTest] Starting SwitchConnectionClient")
        await client.run()

    async def send_packets_and_stop():
        await client.wait_for_ready()
        logger.info("[PyTest] SwitchConnectionClient is ready")
        logger.info("[PyTest] Sending CXL.mem completion packets from server")
        server_connection = manager.get_cxl_connection(0)
        sent_packet1 = CxlMemMemDataPacket.create(0xDEADBEEF)
        await server_connection.cxl_mem_fifo.target_to_host.put(sent_packet1)
        sent_packet2 = CxlMemCmpPacket.create()
        await server_connection.cxl_mem_fifo.target_to_host.put(sent_packet2)
        sent_packet3 = CxlMemBISnpPacket.create(0x0, CXL_MEM_S2MBISNP_OPCODE.BISNP_DATA)
        await server_connection.cxl_mem_fifo.target_to_host.put(sent_packet3)

        logger.info("[PyTest] Checking CXL.mem completion packets received from client")
        client_connection = client.get_cxl_connection()
        received_packet1 = await client_connection.cxl_mem_fifo.target_to_host.get()
        assert bytes(received_packet1) == bytes(sent_packet1)
        received_packet2 = await client_connection.cxl_mem_fifo.target_to_host.get()
        assert bytes(received_packet2) == bytes(sent_packet2)
        received_packet3 = await client_connection.cxl_mem_fifo.target_to_host.get()
        assert bytes(received_packet3) == bytes(sent_packet3)

        logger.info("[PyTest] Stopping SwitchConnectionManager")
        await manager.stop()
        logger.info("[PyTest] Stopping SwitchConnectionClient")
        await client.stop()

    tasks = [
        create_task(start()),
        create_task(wait_and_connect()),
        create_task(send_packets_and_stop()),
    ]
    await gather(*tasks)
