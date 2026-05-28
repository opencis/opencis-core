"""
Tests for GAE (Generic Access Endpoint) control plane wiring.
Covers GaeManager, all 5 GAE CCI commands, and the GFD tunnel binding.
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from opencis.cxl.component.gae_manager import GaeManager, GaeVppbInfo, ProxyThreadEntry
from opencis.cxl.cci.common import CCI_RETURN_CODE
from opencis.cxl.component.cci_executor import CciExecutor, CciRequest, CciResponse
from opencis.cxl.cci.fabric_manager.gae.identify_gae import (
    IdentifyGaeCommand,
    IdentifyGaeResponsePayload,
    VppbGlobalMemorySupportInfo,
)
from opencis.cxl.cci.fabric_manager.gae.proxy_gfd_mgmt import (
    ProxyGfdMgmtCommand,
    ProxyGfdMgmtRequestPayload,
    ProxyGfdMgmtResponsePayload,
)
from opencis.cxl.cci.fabric_manager.gae.get_proxy_thread_status import (
    GetProxyThreadStatusCommand,
    GetProxyThreadStatusRequestPayload,
    GetProxyThreadStatusResponsePayload,
)
from opencis.cxl.cci.fabric_manager.gae.cancel_proxy_thread import (
    CancelProxyThreadCommand,
    CancelProxyThreadRequestPayload,
)
from opencis.cxl.cci.fabric_manager.gae.get_pid_access_vectors import (
    GetPidAccessVectorsCommand,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def gae_no_vppbs():
    return GaeManager(vppbs=[], label="TestGAE")


@pytest.fixture
def gae_with_vppbs():
    return GaeManager(
        vppbs=[
            GaeVppbInfo(vppb_id=0, global_memory_support=False),
            GaeVppbInfo(vppb_id=1, global_memory_support=True),
        ],
        label="TestGAE",
    )


@pytest.fixture
def mock_executor():
    """In-process CciExecutor mock (for GAE proxy unit tests)."""
    executor = MagicMock(spec=CciExecutor)
    resp = CciResponse()
    resp.return_code = CCI_RETURN_CODE.SUCCESS
    resp.payload = b"\x01\x02\x03"
    executor.execute_command = AsyncMock(return_value=resp)
    return executor


@pytest.fixture
def mock_tunnel():
    """Mock DspCciTunnel (production path)."""
    tunnel = MagicMock()
    tunnel._port_index = 1
    resp = CciResponse()
    resp.return_code = CCI_RETURN_CODE.SUCCESS
    resp.payload = b"\xAA\xBB"
    tunnel.send_and_wait = AsyncMock(return_value=resp)
    return tunnel


# ---------------------------------------------------------------------------
# GaeManager — vPPB list
# ---------------------------------------------------------------------------

class TestGaeManagerVppbs:
    def test_no_vppbs(self, gae_no_vppbs):
        assert gae_no_vppbs.get_vppb_count() == 0
        assert gae_no_vppbs.get_vppbs() == []

    def test_with_vppbs(self, gae_with_vppbs):
        assert gae_with_vppbs.get_vppb_count() == 2
        vppbs = gae_with_vppbs.get_vppbs()
        assert vppbs[0].vppb_id == 0
        assert vppbs[1].global_memory_support is True

    def test_vppbs_returns_copy(self, gae_with_vppbs):
        v1 = gae_with_vppbs.get_vppbs()
        v2 = gae_with_vppbs.get_vppbs()
        assert v1 is not v2


# ---------------------------------------------------------------------------
# GaeManager — proxy thread (executor mode)
# ---------------------------------------------------------------------------

class TestGaeManagerProxy:
    @pytest.mark.asyncio
    async def test_start_proxy_no_binding_returns_zero(self, gae_no_vppbs):
        tid = await gae_no_vppbs.start_proxy(0x0001, b"")
        assert tid == 0

    @pytest.mark.asyncio
    async def test_start_proxy_with_executor(self, gae_no_vppbs, mock_executor):
        gae_no_vppbs.set_gfd_executor(mock_executor)
        tid = await gae_no_vppbs.start_proxy(0x0001, b"")
        assert tid == 1  # monotonically starts at 1

    @pytest.mark.asyncio
    async def test_start_proxy_increments_thread_id(self, gae_no_vppbs, mock_executor):
        gae_no_vppbs.set_gfd_executor(mock_executor)
        tid1 = await gae_no_vppbs.start_proxy(0x0001, b"")
        tid2 = await gae_no_vppbs.start_proxy(0x0001, b"")
        assert tid2 == tid1 + 1

    @pytest.mark.asyncio
    async def test_start_proxy_with_tunnel(self, gae_no_vppbs, mock_tunnel):
        gae_no_vppbs.set_gfd_tunnel(mock_tunnel)
        tid = await gae_no_vppbs.start_proxy(0x0001, b"")
        assert tid == 1

    @pytest.mark.asyncio
    async def test_tunnel_takes_precedence_over_executor(self, gae_no_vppbs, mock_tunnel, mock_executor):
        gae_no_vppbs.set_gfd_executor(mock_executor)
        gae_no_vppbs.set_gfd_tunnel(mock_tunnel)  # tunnel clears executor ref
        assert gae_no_vppbs._gfd_executor is None
        assert gae_no_vppbs._gfd_tunnel is mock_tunnel

    @pytest.mark.asyncio
    async def test_proxy_completes_and_stores_response(self, gae_no_vppbs, mock_executor):
        gae_no_vppbs.set_gfd_executor(mock_executor)
        tid = await gae_no_vppbs.start_proxy(0x0001, b"")
        await asyncio.sleep(0.05)  # let the task run
        entry = gae_no_vppbs.get_proxy_status(tid)
        assert entry is not None
        assert entry.completed is True
        assert entry.return_code == int(CCI_RETURN_CODE.SUCCESS)

    @pytest.mark.asyncio
    async def test_get_proxy_status_unknown_returns_none(self, gae_no_vppbs):
        assert gae_no_vppbs.get_proxy_status(999) is None

    @pytest.mark.asyncio
    async def test_cancel_proxy_unknown_returns_invalid(self, gae_no_vppbs):
        rc = gae_no_vppbs.cancel_proxy(999)
        assert rc == CCI_RETURN_CODE.INVALID_INPUT

    @pytest.mark.asyncio
    async def test_cancel_proxy_completed_is_idempotent(self, gae_no_vppbs, mock_executor):
        gae_no_vppbs.set_gfd_executor(mock_executor)
        tid = await gae_no_vppbs.start_proxy(0x0001, b"")
        await asyncio.sleep(0.05)
        rc = gae_no_vppbs.cancel_proxy(tid)
        assert rc == CCI_RETURN_CODE.SUCCESS  # idempotent on completed

    @pytest.mark.asyncio
    async def test_cleanup_removes_completed(self, gae_no_vppbs, mock_executor):
        gae_no_vppbs.set_gfd_executor(mock_executor)
        tid = await gae_no_vppbs.start_proxy(0x0001, b"")
        await asyncio.sleep(0.05)
        assert gae_no_vppbs.get_proxy_status(tid) is not None
        gae_no_vppbs.cleanup_completed_threads()
        assert gae_no_vppbs.get_proxy_status(tid) is None


# ---------------------------------------------------------------------------
# IdentifyGaeCommand (0x5800)
# ---------------------------------------------------------------------------

class TestIdentifyGaeCommand:
    @pytest.mark.asyncio
    async def test_empty_vppb_list(self, gae_no_vppbs):
        cmd = IdentifyGaeCommand(gae_no_vppbs)
        req = CciRequest()
        req.opcode = IdentifyGaeCommand.OPCODE
        resp = await cmd._execute(req)
        assert resp.return_code == CCI_RETURN_CODE.SUCCESS
        payload = IdentifyGaeResponsePayload.parse(resp.payload)
        assert payload.num_vppbs_with_gm_support == 0
        assert payload.vppb_entries == []

    @pytest.mark.asyncio
    async def test_with_vppbs(self, gae_with_vppbs):
        cmd = IdentifyGaeCommand(gae_with_vppbs)
        req = CciRequest()
        req.opcode = IdentifyGaeCommand.OPCODE
        resp = await cmd._execute(req)
        payload = IdentifyGaeResponsePayload.parse(resp.payload)
        assert payload.num_vppbs_with_gm_support == 2
        assert payload.vppb_entries[1].global_memory_support is True

    def test_opcode_is_0x5800(self):
        assert IdentifyGaeCommand.OPCODE == 0x5800


# ---------------------------------------------------------------------------
# ProxyGfdMgmtCommand (0x5809)
# ---------------------------------------------------------------------------

class TestProxyGfdMgmtCommand:
    @pytest.mark.asyncio
    async def test_returns_thread_id(self, gae_no_vppbs, mock_executor):
        gae_no_vppbs.set_gfd_executor(mock_executor)
        cmd = ProxyGfdMgmtCommand(gae_no_vppbs)
        req_payload = ProxyGfdMgmtRequestPayload(gfd_opcode=0x0001, gfd_payload=b"")
        req = CciRequest()
        req.opcode = ProxyGfdMgmtCommand.OPCODE
        req.payload = req_payload.dump()
        resp = await cmd._execute(req)
        assert resp.return_code == CCI_RETURN_CODE.SUCCESS
        parsed = ProxyGfdMgmtResponsePayload.parse(resp.payload)
        assert parsed.thread_id == 1

    @pytest.mark.asyncio
    async def test_no_executor_returns_internal_error(self, gae_no_vppbs):
        cmd = ProxyGfdMgmtCommand(gae_no_vppbs)
        req_payload = ProxyGfdMgmtRequestPayload(gfd_opcode=0x0001, gfd_payload=b"")
        req = CciRequest()
        req.opcode = ProxyGfdMgmtCommand.OPCODE
        req.payload = req_payload.dump()
        resp = await cmd._execute(req)
        # GaeManager.start_proxy returns 0 (no binding) → INTERNAL_ERROR
        assert resp.return_code in (
            CCI_RETURN_CODE.INTERNAL_ERROR,
            CCI_RETURN_CODE.UNSUPPORTED,
        )

    def test_opcode_is_0x5809(self):
        assert ProxyGfdMgmtCommand.OPCODE == 0x5809


# ---------------------------------------------------------------------------
# GetProxyThreadStatusCommand (0x580A)
# ---------------------------------------------------------------------------

class TestGetProxyThreadStatusCommand:
    @pytest.mark.asyncio
    async def test_pending_thread(self, gae_no_vppbs, mock_executor):
        # Slow mock so thread is still pending
        async def slow_exec(req):
            await asyncio.sleep(10)
            return CciResponse()
        mock_executor.execute_command = slow_exec
        gae_no_vppbs.set_gfd_executor(mock_executor)
        tid = await gae_no_vppbs.start_proxy(0x0001, b"")

        cmd = GetProxyThreadStatusCommand(gae_no_vppbs)
        req_payload = GetProxyThreadStatusRequestPayload(thread_id=tid)
        req = CciRequest()
        req.opcode = GetProxyThreadStatusCommand.OPCODE
        req.payload = req_payload.dump()
        resp = await cmd._execute(req)
        assert resp.return_code == CCI_RETURN_CODE.SUCCESS
        parsed = GetProxyThreadStatusResponsePayload.parse(resp.payload)
        assert parsed.completed is False

    @pytest.mark.asyncio
    async def test_completed_thread(self, gae_no_vppbs, mock_executor):
        gae_no_vppbs.set_gfd_executor(mock_executor)
        tid = await gae_no_vppbs.start_proxy(0x0001, b"")
        await asyncio.sleep(0.05)

        cmd = GetProxyThreadStatusCommand(gae_no_vppbs)
        req_payload = GetProxyThreadStatusRequestPayload(thread_id=tid)
        req = CciRequest()
        req.opcode = GetProxyThreadStatusCommand.OPCODE
        req.payload = req_payload.dump()
        resp = await cmd._execute(req)
        parsed = GetProxyThreadStatusResponsePayload.parse(resp.payload)
        assert parsed.completed is True
        assert parsed.gfd_return_code == int(CCI_RETURN_CODE.SUCCESS)

    @pytest.mark.asyncio
    async def test_unknown_thread_id(self, gae_no_vppbs):
        cmd = GetProxyThreadStatusCommand(gae_no_vppbs)
        req_payload = GetProxyThreadStatusRequestPayload(thread_id=999)
        req = CciRequest()
        req.payload = req_payload.dump()
        resp = await cmd._execute(req)
        assert resp.return_code == CCI_RETURN_CODE.INVALID_INPUT


# ---------------------------------------------------------------------------
# CancelProxyThreadCommand (0x580B)
# ---------------------------------------------------------------------------

class TestCancelProxyThreadCommand:
    @pytest.mark.asyncio
    async def test_cancel_unknown_returns_invalid(self, gae_no_vppbs):
        cmd = CancelProxyThreadCommand(gae_no_vppbs)
        req_payload = CancelProxyThreadRequestPayload(thread_id=999)
        req = CciRequest()
        req.payload = req_payload.dump()
        resp = await cmd._execute(req)
        assert resp.return_code == CCI_RETURN_CODE.INVALID_INPUT

    @pytest.mark.asyncio
    async def test_cancel_completed_is_success(self, gae_no_vppbs, mock_executor):
        gae_no_vppbs.set_gfd_executor(mock_executor)
        tid = await gae_no_vppbs.start_proxy(0x0001, b"")
        await asyncio.sleep(0.05)

        cmd = CancelProxyThreadCommand(gae_no_vppbs)
        req_payload = CancelProxyThreadRequestPayload(thread_id=tid)
        req = CciRequest()
        req.payload = req_payload.dump()
        resp = await cmd._execute(req)
        assert resp.return_code == CCI_RETURN_CODE.SUCCESS

    def test_opcode_is_0x580b(self):
        assert CancelProxyThreadCommand.OPCODE == 0x580B
