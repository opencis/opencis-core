"""
Tests for Fabric Crawl Out (5701h) and DspCciTunnel.
CXL 4.0 §7.7.13.2

Run with:
    python -m pytest tests/test_fabric_crawl_out.py -v
"""

import asyncio
import pytest

from opencis.cxl.cci.common import CCI_FM_API_COMMAND_OPCODE, CCI_RETURN_CODE
from opencis.cxl.cci.fabric_manager.gae.fabric_crawl_out import (
    EmbeddedCciCommand,
    EmbeddedCciResponse,
    FabricCrawlOutCommand,
    FabricCrawlOutRequestPayload,
    FabricCrawlOutResponsePayload,
    DspTunnelRegistry,
)
from opencis.cxl.component.dsp_cci_tunnel import DspCciTunnel
from opencis.cxl.component.cci_executor import CciRequest, CciResponse
from opencis.pci.component.fifo_pair import FifoPair
from opencis.cxl.transport.cci_packets import CciMessagePacket
from opencis.cxl.transport.packet_constants import CCI_MCTP_MESSAGE_CATEGORY


# ===========================================================================
# Helpers
# ===========================================================================


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def make_fifo_pair() -> FifoPair:
    return FifoPair()


# ===========================================================================
# Opcode constant check
# ===========================================================================


class TestFabricCrawlOutOpcode:
    def test_opcode_value(self):
        assert CCI_FM_API_COMMAND_OPCODE.FABRIC_CRAWL_OUT == 0x5701
        assert FabricCrawlOutCommand.OPCODE == 0x5701


# ===========================================================================
# EmbeddedCciCommand encode/decode
# ===========================================================================


class TestEmbeddedCciCommand:
    def test_round_trip_no_payload(self):
        cmd = EmbeddedCciCommand(opcode=0x0001, payload=b"")
        raw = cmd.dump()
        parsed = EmbeddedCciCommand.parse(raw)
        assert parsed.opcode == 0x0001
        assert parsed.payload == b""

    def test_round_trip_with_payload(self):
        cmd = EmbeddedCciCommand(opcode=0x0400, payload=b"\x00\x00")
        raw = cmd.dump()
        parsed = EmbeddedCciCommand.parse(raw)
        assert parsed.opcode == 0x0400
        assert parsed.payload == b"\x00\x00"

    def test_to_cci_request(self):
        cmd = EmbeddedCciCommand(opcode=0x0001, payload=b"\xAB")
        req = cmd.to_cci_request()
        assert req.opcode == 0x0001
        assert req.payload == b"\xAB"


# ===========================================================================
# EmbeddedCciResponse encode/decode
# ===========================================================================


class TestEmbeddedCciResponse:
    def test_round_trip(self):
        resp = EmbeddedCciResponse(return_code=0, payload=b"\x01\x02\x03")
        raw = resp.dump()
        parsed = EmbeddedCciResponse.parse(raw)
        assert parsed.return_code == 0
        assert parsed.payload == b"\x01\x02\x03"

    def test_from_cci_response(self):
        cci_resp = CciResponse(return_code=CCI_RETURN_CODE.SUCCESS, payload=b"\xFF")
        emb = EmbeddedCciResponse.from_cci_response(cci_resp)
        assert emb.return_code == int(CCI_RETURN_CODE.SUCCESS)
        assert emb.payload == b"\xFF"


# ===========================================================================
# FabricCrawlOutRequestPayload encode/decode
# ===========================================================================


class TestFabricCrawlOutRequestPayload:
    def test_round_trip(self):
        emb_cmd = EmbeddedCciCommand(opcode=0x0001, payload=b"\xAA\xBB")
        req = FabricCrawlOutRequestPayload(target_port=3, embedded_cmd=emb_cmd)
        raw = req.dump()
        parsed = FabricCrawlOutRequestPayload.parse(raw)
        assert parsed.target_port == 3
        assert parsed.embedded_cmd.opcode == 0x0001
        assert parsed.embedded_cmd.payload == b"\xAA\xBB"

    def test_create_cci_request_helper(self):
        req = FabricCrawlOutCommand.create_cci_request(
            target_port=2, gfd_opcode=0x0001, gfd_payload=b"\x00"
        )
        assert req.opcode == 0x5701
        parsed_payload = FabricCrawlOutRequestPayload.parse(req.payload)
        assert parsed_payload.target_port == 2
        assert parsed_payload.embedded_cmd.opcode == 0x0001


# ===========================================================================
# FabricCrawlOutResponsePayload encode/decode
# ===========================================================================


class TestFabricCrawlOutResponsePayload:
    def test_round_trip(self):
        emb_resp = EmbeddedCciResponse(return_code=0, payload=b"\x11\x22")
        resp = FabricCrawlOutResponsePayload(embedded_resp=emb_resp)
        raw = resp.dump()
        parsed = FabricCrawlOutResponsePayload.parse(raw)
        assert parsed.embedded_resp.return_code == 0
        assert parsed.embedded_resp.payload == b"\x11\x22"

    def test_parse_response_payload_helper(self):
        emb = EmbeddedCciResponse(return_code=0, payload=b"\xDE\xAD")
        raw = FabricCrawlOutResponsePayload(embedded_resp=emb).dump()
        parsed = FabricCrawlOutCommand.parse_response_payload(raw)
        assert parsed.embedded_resp.payload == b"\xDE\xAD"


# ===========================================================================
# DspTunnelRegistry
# ===========================================================================


class TestDspTunnelRegistry:
    def test_register_and_get(self):
        reg = DspTunnelRegistry()
        fp = make_fifo_pair()
        tunnel = DspCciTunnel(cci_fifo=fp, port_index=1)
        reg.register(1, tunnel)
        assert reg.get(1) is tunnel
        assert reg.get(99) is None

    def test_port_indices(self):
        reg = DspTunnelRegistry()
        fp = make_fifo_pair()
        reg.register(0, DspCciTunnel(cci_fifo=fp, port_index=0))
        reg.register(2, DspCciTunnel(cci_fifo=fp, port_index=2))
        assert sorted(reg.port_indices()) == [0, 2]


# ===========================================================================
# FabricCrawlOutCommand — invalid port
# ===========================================================================


class TestFabricCrawlOutCommand:
    def test_unknown_port_returns_invalid_input(self):
        reg = DspTunnelRegistry()   # no tunnels registered
        cmd = FabricCrawlOutCommand(reg)
        req = FabricCrawlOutCommand.create_cci_request(
            target_port=5, gfd_opcode=0x0001
        )
        cci_req = CciRequest(opcode=0x5701, payload=req.payload)
        resp = run(cmd._execute(cci_req))  # pylint: disable=protected-access
        assert resp.return_code == CCI_RETURN_CODE.INVALID_INPUT

    def test_short_payload_returns_invalid_input(self):
        reg = DspTunnelRegistry()
        cmd = FabricCrawlOutCommand(reg)
        cci_req = CciRequest(opcode=0x5701, payload=b"\x00")  # too short
        resp = run(cmd._execute(cci_req))  # pylint: disable=protected-access
        assert resp.return_code == CCI_RETURN_CODE.INVALID_INPUT


# ===========================================================================
# DspCciTunnel integration — simulate GFD responding on the fifo
# ===========================================================================


class TestDspCciTunnelIntegration:
    """
    End-to-end test that simulates the switch-GFD cci_fifo transport:

      1. DspCciTunnel.send_and_wait() puts a CciMessagePacket on host_to_target.
      2. A simulated GFD coroutine reads from host_to_target and puts a
         response CciMessagePacket on target_to_host.
      3. DspCciTunnel._drain_responses() picks it up and resolves the future.
      4. send_and_wait() returns the CciResponse.
    """

    def test_tunnel_round_trip(self):
        async def _run():
            fp = make_fifo_pair()
            tunnel = DspCciTunnel(cci_fifo=fp, port_index=0, timeout_s=2.0)
            tunnel.start()

            # Simulate GFD: read request from host_to_target, echo response
            async def gfd_sim():
                req_msg = await fp.host_to_target.get()
                tag = req_msg.cci_msg_header.message_tag
                resp_msg = CciMessagePacket.create(
                    data=b"\xCA\xFE",
                    message_category=CCI_MCTP_MESSAGE_CATEGORY.RESPONSE,
                    opcode=req_msg.cci_msg_header.command_opcode,
                    message_tag=tag,
                    return_code=int(CCI_RETURN_CODE.SUCCESS),
                )
                await fp.target_to_host.put(resp_msg)

            gfd_task = asyncio.create_task(gfd_sim())

            req = CciRequest(opcode=0x0001, payload=b"")
            resp = await tunnel.send_and_wait(req)

            await gfd_task
            await tunnel.stop()
            return resp

        resp = run(_run())
        assert resp.return_code == CCI_RETURN_CODE.SUCCESS
        assert resp.payload == b"\xCA\xFE"

    def test_tunnel_timeout(self):
        async def _run():
            fp = make_fifo_pair()
            tunnel = DspCciTunnel(cci_fifo=fp, port_index=0, timeout_s=0.1)
            tunnel.start()
            # Nobody reads from host_to_target → timeout
            req = CciRequest(opcode=0x0001, payload=b"")
            resp = await tunnel.send_and_wait(req)
            await tunnel.stop()
            return resp

        resp = run(_run())
        assert resp.return_code == CCI_RETURN_CODE.RETRY_REQUIRED

    def test_fabric_crawl_out_command_full_path(self):
        """
        Full end-to-end: FabricCrawlOutCommand → DspCciTunnel → simulated GFD.
        """
        async def _run():
            fp = make_fifo_pair()
            tunnel = DspCciTunnel(cci_fifo=fp, port_index=1, timeout_s=2.0)
            tunnel.start()

            reg = DspTunnelRegistry()
            reg.register(1, tunnel)
            cmd = FabricCrawlOutCommand(reg)

            # Simulated GFD
            async def gfd_sim():
                req_msg = await fp.host_to_target.get()
                tag = req_msg.cci_msg_header.message_tag
                resp_msg = CciMessagePacket.create(
                    data=b"\xBE\xEF",
                    message_category=CCI_MCTP_MESSAGE_CATEGORY.RESPONSE,
                    opcode=req_msg.cci_msg_header.command_opcode,
                    message_tag=tag,
                    return_code=int(CCI_RETURN_CODE.SUCCESS),
                )
                await fp.target_to_host.put(resp_msg)

            gfd_task = asyncio.create_task(gfd_sim())

            cci_req = FabricCrawlOutCommand.create_cci_request(
                target_port=1, gfd_opcode=0x0001, gfd_payload=b""
            )
            resp = await cmd._execute(cci_req)  # pylint: disable=protected-access

            await gfd_task
            await tunnel.stop()
            return resp

        resp = run(_run())
        assert resp.return_code == CCI_RETURN_CODE.SUCCESS
        parsed = FabricCrawlOutCommand.parse_response_payload(resp.payload)
        assert parsed.embedded_resp.return_code == int(CCI_RETURN_CODE.SUCCESS)
        assert parsed.embedded_resp.payload == b"\xBE\xEF"
