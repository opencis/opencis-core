"""
Tests for the GAE (Global Memory Access Endpoint) CCI command set.
CXL 4.0 §7.7.14 — simple-device GFD variant.

Run with:
    python -m pytest tests/test_gae_commands.py -v
"""

import asyncio
import pytest

from opencis.cxl.cci.common import CCI_GAE_COMMAND_OPCODE, CCI_RETURN_CODE
from opencis.cxl.cci.fabric_manager.gae import (
    IdentifyGaeCommand,
    IdentifyGaeResponsePayload,
    VppbGlobalMemorySupportInfo,
    GetPidAccessVectorsCommand,
    GetPidAccessVectorsRequestPayload,
    GetPidAccessVectorsResponsePayload,
    ProxyGfdMgmtCommand,
    ProxyGfdMgmtRequestPayload,
    ProxyGfdMgmtResponsePayload,
    GetProxyThreadStatusCommand,
    GetProxyThreadStatusRequestPayload,
    GetProxyThreadStatusResponsePayload,
    CancelProxyThreadCommand,
    CancelProxyThreadRequestPayload,
)
from opencis.cxl.component.gae_manager import GaeManager, GaeVppbInfo
from opencis.cxl.component.cci_executor import CciExecutor, CciRequest, CciResponse


# ===========================================================================
# Helpers
# ===========================================================================


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def make_gae_manager(vppbs=None):
    return GaeManager(vppbs=vppbs or [], label="test")


# ===========================================================================
# Opcode constants
# ===========================================================================


class TestGaeOpcodes:
    def test_opcodes_defined(self):
        assert CCI_GAE_COMMAND_OPCODE.IDENTIFY_GAE == 0x5800
        assert CCI_GAE_COMMAND_OPCODE.GET_PID_ACCESS_VECTORS == 0x5802
        assert CCI_GAE_COMMAND_OPCODE.PROXY_GFD_MGMT_CMD == 0x5809
        assert CCI_GAE_COMMAND_OPCODE.GET_PROXY_THREAD_STATUS == 0x580A
        assert CCI_GAE_COMMAND_OPCODE.CANCEL_PROXY_THREAD == 0x580B


# ===========================================================================
# Identify GAE (5800h) — payload round-trip
# ===========================================================================


class TestIdentifyGae:
    def test_empty_response_round_trip(self):
        """Simple device: no G-FAM vPPBs → num=0, empty list."""
        resp = IdentifyGaeResponsePayload(num_vppbs_with_gm_support=0, vppb_entries=[])
        raw = resp.dump()
        assert len(raw) == 4  # just the 4-byte header
        parsed = IdentifyGaeResponsePayload.parse(raw)
        assert parsed.num_vppbs_with_gm_support == 0
        assert parsed.vppb_entries == []

    def test_with_vppbs_round_trip(self):
        entries = [
            VppbGlobalMemorySupportInfo(vppb_id=0, global_memory_support=True),
            VppbGlobalMemorySupportInfo(vppb_id=1, global_memory_support=False),
        ]
        resp = IdentifyGaeResponsePayload(num_vppbs_with_gm_support=2, vppb_entries=entries)
        raw = resp.dump()
        assert len(raw) == 4 + 2 * 4
        parsed = IdentifyGaeResponsePayload.parse(raw)
        assert parsed.num_vppbs_with_gm_support == 2
        assert parsed.vppb_entries[0].global_memory_support is True
        assert parsed.vppb_entries[1].global_memory_support is False

    def test_command_execute_simple_device(self):
        """Simple device: GAE manager with no vPPBs → count=0."""
        gae = make_gae_manager()
        cmd = IdentifyGaeCommand(gae)
        req = CciRequest(opcode=IdentifyGaeCommand.OPCODE)
        resp = run(cmd._execute(req))  # pylint: disable=protected-access
        parsed = IdentifyGaeResponsePayload.parse(resp.payload)
        assert parsed.num_vppbs_with_gm_support == 0

    def test_command_execute_with_vppbs(self):
        vppbs = [GaeVppbInfo(vppb_id=0, global_memory_support=True)]
        gae = make_gae_manager(vppbs=vppbs)
        cmd = IdentifyGaeCommand(gae)
        req = CciRequest(opcode=IdentifyGaeCommand.OPCODE)
        resp = run(cmd._execute(req))  # pylint: disable=protected-access
        parsed = IdentifyGaeResponsePayload.parse(resp.payload)
        assert parsed.num_vppbs_with_gm_support == 1
        assert parsed.vppb_entries[0].vppb_id == 0
        assert parsed.vppb_entries[0].global_memory_support is True


# ===========================================================================
# Get PID Access Vectors (5802h) — payload round-trip
# ===========================================================================


class TestGetPidAccessVectors:
    def test_request_round_trip(self):
        req = GetPidAccessVectorsRequestPayload(pid=0x042)
        raw = req.dump()
        parsed = GetPidAccessVectorsRequestPayload.parse(raw)
        assert parsed.pid == 0x042

    def test_response_round_trip(self):
        resp = GetPidAccessVectorsResponsePayload(gmv=0xDEAD, vtv=0xBEEF, pid=0x123)
        raw = resp.dump()
        parsed = GetPidAccessVectorsResponsePayload.parse(raw)
        assert parsed.gmv == 0xDEAD
        assert parsed.vtv == 0xBEEF
        assert parsed.pid == 0x123

    def test_command_execute_simple_device(self):
        """Simple device: always returns GMV=0, VTV=0."""
        gae = make_gae_manager()
        cmd = GetPidAccessVectorsCommand(gae)
        req = CciRequest(
            opcode=GetPidAccessVectorsCommand.OPCODE,
            payload=GetPidAccessVectorsRequestPayload(pid=0x042).dump(),
        )
        resp = run(cmd._execute(req))  # pylint: disable=protected-access
        parsed = GetPidAccessVectorsResponsePayload.parse(resp.payload)
        assert parsed.gmv == 0
        assert parsed.vtv == 0
        assert parsed.pid == 0x042


# ===========================================================================
# Proxy GFD Management Command (5809h)
# ===========================================================================


class TestProxyGfdMgmt:
    def test_request_round_trip(self):
        req = ProxyGfdMgmtRequestPayload(gfd_opcode=0x0001, gfd_payload=b"\xAB\xCD")
        raw = req.dump()
        parsed = ProxyGfdMgmtRequestPayload.parse(raw)
        assert parsed.gfd_opcode == 0x0001
        assert parsed.gfd_payload == b"\xAB\xCD"

    def test_response_round_trip(self):
        resp = ProxyGfdMgmtResponsePayload(thread_id=7)
        raw = resp.dump()
        parsed = ProxyGfdMgmtResponsePayload.parse(raw)
        assert parsed.thread_id == 7

    def test_command_no_executor_returns_internal_error(self):
        """Without a GFD executor bound, returns INTERNAL_ERROR."""
        gae = make_gae_manager()
        cmd = ProxyGfdMgmtCommand(gae)
        req = CciRequest(
            opcode=ProxyGfdMgmtCommand.OPCODE,
            payload=ProxyGfdMgmtRequestPayload(gfd_opcode=0x0001).dump(),
        )
        resp = run(cmd._execute(req))  # pylint: disable=protected-access
        assert resp.return_code == CCI_RETURN_CODE.INTERNAL_ERROR

    def test_command_with_executor_returns_thread_id(self):
        """With a GFD executor bound, returns a non-zero thread_id."""
        gae = make_gae_manager()

        # Create a minimal echo executor
        exec_ = CciExecutor(label="mock-gfd")

        async def mock_cmd_execute(request):
            return CciResponse(return_code=CCI_RETURN_CODE.SUCCESS)

        from opencis.cxl.component.cci_executor import CciForegroundCommand
        from opencis.cxl.cci.generic.information_and_status import IdentifyCommand, IdentifyResponsePayload
        from opencis.cxl.cci.common import CCI_GENERIC_COMMAND_OPCODE
        from opencis.pci.component.pci import EEUM_VID, SW_GFD_DID
        from opencis.cxl.cci.generic.information_and_status.identify import IdentifyComponentType

        identity = IdentifyResponsePayload(
            vendor_id=EEUM_VID,
            device_id=SW_GFD_DID,
            component_type=IdentifyComponentType.GFD,
        )
        exec_.register_command(IdentifyCommand.OPCODE, IdentifyCommand(identity))
        gae.set_gfd_executor(exec_)

        cmd = ProxyGfdMgmtCommand(gae)
        req = CciRequest(
            opcode=ProxyGfdMgmtCommand.OPCODE,
            payload=ProxyGfdMgmtRequestPayload(gfd_opcode=0x0001).dump(),
        )
        resp = run(cmd._execute(req))  # pylint: disable=protected-access
        assert resp.return_code == CCI_RETURN_CODE.SUCCESS
        parsed = ProxyGfdMgmtResponsePayload.parse(resp.payload)
        assert parsed.thread_id >= 1

    def test_invalid_payload_returns_invalid_input(self):
        gae = make_gae_manager()
        cmd = ProxyGfdMgmtCommand(gae)
        req = CciRequest(opcode=ProxyGfdMgmtCommand.OPCODE, payload=b"\x00")  # too short
        resp = run(cmd._execute(req))  # pylint: disable=protected-access
        assert resp.return_code == CCI_RETURN_CODE.INVALID_INPUT


# ===========================================================================
# Get Proxy Thread Status (580Ah)
# ===========================================================================


class TestGetProxyThreadStatus:
    def test_payload_round_trip(self):
        resp = GetProxyThreadStatusResponsePayload(
            thread_id=3,
            completed=True,
            gfd_return_code=0,
            gfd_response_payload=b"\x01\x02",
        )
        raw = resp.dump()
        parsed = GetProxyThreadStatusResponsePayload.parse(raw)
        assert parsed.thread_id == 3
        assert parsed.completed is True
        assert parsed.gfd_return_code == 0
        assert parsed.gfd_response_payload == b"\x01\x02"

    def test_unknown_thread_returns_invalid_input(self):
        gae = make_gae_manager()
        cmd = GetProxyThreadStatusCommand(gae)
        req = CciRequest(
            opcode=GetProxyThreadStatusCommand.OPCODE,
            payload=GetProxyThreadStatusRequestPayload(thread_id=999).dump(),
        )
        resp = run(cmd._execute(req))  # pylint: disable=protected-access
        assert resp.return_code == CCI_RETURN_CODE.INVALID_INPUT


# ===========================================================================
# Cancel Proxy Thread (580Bh)
# ===========================================================================


class TestCancelProxyThread:
    def test_payload_round_trip(self):
        payload = CancelProxyThreadRequestPayload(thread_id=5)
        raw = payload.dump()
        parsed = CancelProxyThreadRequestPayload.parse(raw)
        assert parsed.thread_id == 5

    def test_cancel_unknown_thread_returns_invalid_input(self):
        gae = make_gae_manager()
        cmd = CancelProxyThreadCommand(gae)
        req = CciRequest(
            opcode=CancelProxyThreadCommand.OPCODE,
            payload=CancelProxyThreadRequestPayload(thread_id=42).dump(),
        )
        resp = run(cmd._execute(req))  # pylint: disable=protected-access
        assert resp.return_code == CCI_RETURN_CODE.INVALID_INPUT


# ===========================================================================
# GaeManager integration
# ===========================================================================


class TestGaeManager:
    def test_vppb_count(self):
        gae = GaeManager(vppbs=[GaeVppbInfo(0), GaeVppbInfo(1)], label="t")
        assert gae.get_vppb_count() == 2

    def test_proxy_cancel_before_start_returns_invalid(self):
        gae = make_gae_manager()
        rc = gae.cancel_proxy(999)
        assert rc == CCI_RETURN_CODE.INVALID_INPUT

    def test_proxy_status_unknown_returns_none(self):
        gae = make_gae_manager()
        assert gae.get_proxy_status(123) is None
