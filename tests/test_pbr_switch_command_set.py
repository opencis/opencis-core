"""
Unit tests for PBR Switch Command Set (Section 7.7.13, CXL Spec Rev 4.0)

Commands tested:
  5700h - Identify PBR Switch
  5704h - Configure PID Assignment
  5705h - Get PID Binding
  5706h - Configure PID Binding (background)
  5708h - Get DRT
  5709h - Set DRT
"""

import asyncio
import logging
import pytest

logger = logging.getLogger(__name__)

from opencis.cxl.cci.common import CCI_FM_API_COMMAND_OPCODE, CCI_RETURN_CODE
from opencis.cxl.component.cci_executor import CciRequest, CciResponse
from opencis.cxl.component.pbr_switch_manager import (
    DrtEntry,
    DrtEntryType,
    DrtTable,
    HmatInfo,
    PbrSwitchInfo,
    PbrSwitchManager,
    PID_UNASSIGNED,
    PidBindingOperation,
    PidTarget,
    PidTargetType,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_manager(num_drts: int = 2, targets=None) -> PbrSwitchManager:
    default_targets = [
        PidTarget(target_id=0, target_type=PidTargetType.FABRIC_PORT,
                  instance_id=0, vcs_id=0, physical_port_id=0),
        PidTarget(target_id=1, target_type=PidTargetType.HOST_EDGE_PORT,
                  instance_id=0, vcs_id=0, physical_port_id=1),
        PidTarget(target_id=2, target_type=PidTargetType.DOWNSTREAM_EDGE_PORT,
                  instance_id=0, vcs_id=0, physical_port_id=2),
    ]
    return PbrSwitchManager(
        num_drts=num_drts,
        num_rgts=1,
        pid_targets=targets or default_targets,
    )


def run(coro):
    resp = asyncio.get_event_loop().run_until_complete(coro)
    if hasattr(resp, "return_code"):
        logger.debug(f"CCI Response - Return Code: {resp.return_code}")
    if hasattr(resp, "payload") and resp.payload:
        logger.debug(f"CCI Response - Raw Payload (Hex): {resp.payload.hex(' ')}")
    return resp




# ===========================================================================
# Opcode registration
# ===========================================================================

class TestOpcodeRegistration:
    def test_pbr_opcodes_exist(self):
        assert CCI_FM_API_COMMAND_OPCODE.IDENTIFY_PBR_SWITCH == 0x5700
        assert CCI_FM_API_COMMAND_OPCODE.CONFIGURE_PID_ASSIGNMENT == 0x5704
        assert CCI_FM_API_COMMAND_OPCODE.GET_PID_BINDING == 0x5705
        assert CCI_FM_API_COMMAND_OPCODE.CONFIGURE_PID_BINDING == 0x5706
        assert CCI_FM_API_COMMAND_OPCODE.GET_DRT == 0x5708
        assert CCI_FM_API_COMMAND_OPCODE.SET_DRT == 0x5709

    def test_opcode_string_lookup(self):
        from opencis.cxl.cci.common import get_opcode_string
        assert get_opcode_string(0x5700) == "IDENTIFY_PBR_SWITCH"
        assert get_opcode_string(0x5704) == "CONFIGURE_PID_ASSIGNMENT"
        assert get_opcode_string(0x5708) == "GET_DRT"
        assert get_opcode_string(0x5709) == "SET_DRT"


# ===========================================================================
# PbrSwitchManager — unit tests
# ===========================================================================

class TestPbrSwitchManager:

    # --- DRT model correctness ---

    def test_drt_initialized_as_invalid(self):
        mgr = make_manager(num_drts=1)
        assert len(mgr._drt_tables) == 1
        table = mgr._drt_tables[0]
        assert len(table.entries) == 4096
        for entry in table.entries:
            assert entry.entry_type == DrtEntryType.INVALID

    def test_drt_indexed_by_dpid(self):
        """DRT[dpid] → egress port. Index IS the DPID, not a port number."""
        mgr = make_manager()
        entries = [DrtEntry(DrtEntryType.PHYSICAL_PORT, routing_target=3)]
        rc = mgr.set_drt(drt_index=0, start_entry=0x042, entries=entries)
        assert rc == CCI_RETURN_CODE.SUCCESS
        result, _ = mgr.get_drt(0, 0x042, 1)
        assert result[0].entry_type == DrtEntryType.PHYSICAL_PORT
        assert result[0].routing_target == 3

    def test_set_drt_multiple_entries(self):
        mgr = make_manager()
        entries = [
            DrtEntry(DrtEntryType.PHYSICAL_PORT, 1),
            DrtEntry(DrtEntryType.PHYSICAL_PORT, 2),
            DrtEntry(DrtEntryType.RGT_INDEX, 0),
            DrtEntry(DrtEntryType.INVALID, 0),
        ]
        rc = mgr.set_drt(0, start_entry=0x010, entries=entries)
        assert rc == CCI_RETURN_CODE.SUCCESS
        result, rgt_idx = mgr.get_drt(0, 0x010, 4)
        assert result[0].routing_target == 1
        assert result[1].routing_target == 2
        assert result[2].entry_type == DrtEntryType.RGT_INDEX
        assert result[3].entry_type == DrtEntryType.INVALID

    def test_set_drt_out_of_range_index(self):
        mgr = make_manager()
        rc = mgr.set_drt(drt_index=99, start_entry=0, entries=[])
        assert rc == CCI_RETURN_CODE.INVALID_INPUT

    def test_set_drt_exceeds_table_size(self):
        mgr = make_manager()
        # start=4095, 2 entries → goes past 4096
        entries = [DrtEntry(DrtEntryType.PHYSICAL_PORT, 0)] * 2
        rc = mgr.set_drt(0, start_entry=4095, entries=entries)
        assert rc == CCI_RETURN_CODE.INVALID_INPUT

    def test_set_drt_reserved_entry_type_rejected(self):
        mgr = make_manager()
        bad = DrtEntry(entry_type=DrtEntryType.RESERVED, routing_target=0)
        rc = mgr.set_drt(0, start_entry=0, entries=[bad])
        assert rc == CCI_RETURN_CODE.INVALID_INPUT

    def test_get_drt_invalid_index(self):
        mgr = make_manager()
        assert mgr.get_drt(drt_index=99, start_entry=0, num_entries=1) is None

    # --- PID assignment ---

    def test_assign_pid_success(self):
        mgr = make_manager()
        rc = mgr.assign_pid(pid=0x010, target_id=0, instance_id=0)
        assert rc == CCI_RETURN_CODE.SUCCESS
        assert 0x010 in mgr._pid_assignments

    def test_assign_same_pid_same_target_idempotent(self):
        mgr = make_manager()
        assert mgr.assign_pid(0x020, 0, 0) == CCI_RETURN_CODE.SUCCESS
        assert mgr.assign_pid(0x020, 0, 0) == CCI_RETURN_CODE.SUCCESS

    def test_assign_pid_duplicate_different_target_rejected(self):
        mgr = make_manager()
        mgr.assign_pid(0x001, target_id=0, instance_id=0)
        rc = mgr.assign_pid(0x001, target_id=1, instance_id=0)
        assert rc == CCI_RETURN_CODE.INVALID_INPUT

    def test_assign_pid_invalid_target(self):
        mgr = make_manager()
        rc = mgr.assign_pid(0x005, target_id=99, instance_id=0)
        assert rc == CCI_RETURN_CODE.INVALID_INPUT

    def test_clear_pid_success(self):
        mgr = make_manager()
        mgr.assign_pid(0x007, 0, 0)
        rc = mgr.clear_pid(0x007, 0, 0)
        assert rc == CCI_RETURN_CODE.SUCCESS
        assert 0x007 not in mgr._pid_assignments

    def test_clear_pid_not_assigned_fails(self):
        mgr = make_manager()
        rc = mgr.clear_pid(0xABC, 0, 0)
        assert rc == CCI_RETURN_CODE.INVALID_INPUT

    # --- PID Binding ---

    def test_bind_and_get_binding(self):
        mgr = make_manager()
        hmat = HmatInfo(latency_entry_base_unit=1000, latency_entry=10,
                        bw_entry_base_unit=500, bw_entry=5)
        rc = mgr.configure_pid_binding(PidBindingOperation.BIND, 0, 1, 0x042, hmat)
        assert rc == CCI_RETURN_CODE.SUCCESS
        binding = mgr.get_pid_binding(0, 1)
        assert binding.pid == 0x042
        assert binding.hmat.latency_entry == 10

    def test_unbind_binding(self):
        mgr = make_manager()
        hmat = HmatInfo()
        mgr.configure_pid_binding(PidBindingOperation.BIND, 0, 0, 0x001, hmat)
        rc = mgr.configure_pid_binding(PidBindingOperation.UNBIND, 0, 0, 0x001, hmat)
        assert rc == CCI_RETURN_CODE.SUCCESS
        assert mgr.get_pid_binding(0, 0) is None

    def test_unbind_nonexistent_fails(self):
        mgr = make_manager()
        rc = mgr.configure_pid_binding(
            PidBindingOperation.UNBIND, 5, 5, 0x000, HmatInfo()
        )
        assert rc == CCI_RETURN_CODE.INVALID_INPUT

    def test_get_unbound_returns_none(self):
        mgr = make_manager()
        assert mgr.get_pid_binding(99, 99) is None


# ===========================================================================
# CCI Command — payload serialization round-trips
# ===========================================================================

class TestDrtEntrySerialisation:

    def test_roundtrip_physical_port(self):
        e = DrtEntry(DrtEntryType.PHYSICAL_PORT, routing_target=7)
        assert DrtEntry.parse(e.dump()) == e

    def test_roundtrip_rgt_index(self):
        e = DrtEntry(DrtEntryType.RGT_INDEX, routing_target=2)
        assert DrtEntry.parse(e.dump()) == e

    def test_roundtrip_invalid(self):
        e = DrtEntry(DrtEntryType.INVALID, routing_target=0)
        assert DrtEntry.parse(e.dump()) == e

    def test_entry_type_mask(self):
        """Only Bits[1:0] of byte 0 are used for entry_type."""
        raw = bytes([0b11111101, 4])   # bits[1:0] = 01 = PHYSICAL_PORT
        e = DrtEntry.parse(raw)
        assert e.entry_type == DrtEntryType.PHYSICAL_PORT
        assert e.routing_target == 4


class TestGetDrtPayloadSerialisation:

    def test_request_roundtrip(self):
        from opencis.cxl.cci.fabric_manager.pbr_switch.get_drt import GetDrtRequestPayload
        req = GetDrtRequestPayload(drt_index=1, num_entries=8, start_entry=0x100)
        req2 = GetDrtRequestPayload.parse(req.dump())
        assert req2.drt_index == 1
        assert req2.num_entries == 8
        assert req2.start_entry == 0x100

    def test_response_roundtrip(self):
        from opencis.cxl.cci.fabric_manager.pbr_switch.get_drt import GetDrtResponsePayload
        entries = [
            DrtEntry(DrtEntryType.PHYSICAL_PORT, 3),
            DrtEntry(DrtEntryType.RGT_INDEX, 0),
        ]
        resp = GetDrtResponsePayload(
            drt_index=0, num_entries=2, start_entry=0x042,
            associated_rgt_index=1, entries=entries
        )
        resp2 = GetDrtResponsePayload.parse(resp.dump())
        assert resp2.drt_index == 0
        assert resp2.start_entry == 0x042
        assert resp2.associated_rgt_index == 1
        assert len(resp2.entries) == 2
        assert resp2.entries[0].entry_type == DrtEntryType.PHYSICAL_PORT
        assert resp2.entries[0].routing_target == 3


class TestSetDrtPayloadSerialisation:

    def test_request_roundtrip(self):
        from opencis.cxl.cci.fabric_manager.pbr_switch.set_drt import SetDrtRequestPayload
        entries = [DrtEntry(DrtEntryType.PHYSICAL_PORT, 5)]
        req = SetDrtRequestPayload(drt_index=0, start_entry=0x010, entries=entries)
        req2 = SetDrtRequestPayload.parse(req.dump())
        assert req2.drt_index == 0
        assert req2.start_entry == 0x010
        assert req2.entries[0].routing_target == 5


class TestConfigurePidAssignmentSerialisation:

    def test_request_roundtrip(self):
        from opencis.cxl.cci.fabric_manager.pbr_switch.configure_pid_assignment import (
            ConfigurePidAssignmentRequestPayload, PidAssignmentEntry,
            PidAssignmentOperation,
        )
        entries = [
            PidAssignmentEntry(pid=0x042, target_id=1, instance_id=0),
            PidAssignmentEntry(pid=0x043, target_id=2, instance_id=0),
        ]
        req = ConfigurePidAssignmentRequestPayload(
            operation=PidAssignmentOperation.ASSIGN, entries=entries
        )
        req2 = ConfigurePidAssignmentRequestPayload.parse(req.dump())
        assert req2.operation == PidAssignmentOperation.ASSIGN
        assert len(req2.entries) == 2
        assert req2.entries[0].pid == 0x042
        assert req2.entries[1].pid == 0x043

    def test_pid_masked_to_12_bits(self):
        from opencis.cxl.cci.fabric_manager.pbr_switch.configure_pid_assignment import (
            PidAssignmentEntry,
        )
        e = PidAssignmentEntry(pid=0xFABC, target_id=0, instance_id=0)
        e2 = PidAssignmentEntry.parse(e.dump())
        assert e2.pid == (0xFABC & 0x0FFF)


class TestGetPidBindingSerialisation:

    def test_request_roundtrip(self):
        from opencis.cxl.cci.fabric_manager.pbr_switch.get_pid_binding import (
            GetPidBindingRequestPayload,
        )
        req = GetPidBindingRequestPayload(target_vcs=1, target_vppb=3)
        req2 = GetPidBindingRequestPayload.parse(req.dump())
        assert req2.target_vcs == 1
        assert req2.target_vppb == 3

    def test_response_roundtrip_unbound(self):
        from opencis.cxl.cci.fabric_manager.pbr_switch.get_pid_binding import (
            GetPidBindingResponsePayload,
        )
        resp = GetPidBindingResponsePayload(pid=PID_UNASSIGNED)
        resp2 = GetPidBindingResponsePayload.parse(resp.dump())
        assert resp2.pid == PID_UNASSIGNED

    def test_response_roundtrip_bound(self):
        from opencis.cxl.cci.fabric_manager.pbr_switch.get_pid_binding import (
            GetPidBindingResponsePayload,
        )
        resp = GetPidBindingResponsePayload(
            pid=0x042, latency_entry_base_unit=1000, latency_entry=10,
            bw_entry_base_unit=500, bw_entry=5
        )
        resp2 = GetPidBindingResponsePayload.parse(resp.dump())
        assert resp2.pid == 0x042
        assert resp2.latency_entry_base_unit == 1000
        assert resp2.bw_entry == 5


class TestConfigurePidBindingSerialisation:

    def test_request_roundtrip(self):
        from opencis.cxl.cci.fabric_manager.pbr_switch.configure_pid_binding import (
            ConfigurePidBindingRequestPayload,
        )
        req = ConfigurePidBindingRequestPayload(
            operation=0, target_vcs=0, target_vppb=1, pid=0x042,
            latency_entry_base_unit=999, latency_entry=7,
            bw_entry_base_unit=888, bw_entry=3,
        )
        req2 = ConfigurePidBindingRequestPayload.parse(req.dump())
        assert req2.operation == 0
        assert req2.pid == 0x042
        assert req2.latency_entry_base_unit == 999
        assert req2.bw_entry == 3


class TestIdentifyPbrSwitchSerialisation:

    def test_response_roundtrip(self):
        from opencis.cxl.cci.fabric_manager.pbr_switch.identify_pbr_switch import (
            IdentifyPbrSwitchResponsePayload,
        )
        resp = IdentifyPbrSwitchResponsePayload(
            gae_support_map=0b11, num_drts=2, num_rgts=1, routing_caps=0x03
        )
        resp2 = IdentifyPbrSwitchResponsePayload.parse(resp.dump())
        assert resp2.gae_support_map == 0b11
        assert resp2.num_drts == 2
        assert resp2.routing_caps == 0x03


# ===========================================================================
# CCI Command execution — async tests
# ===========================================================================

class TestIdentifyPbrSwitchCommand:

    def test_success(self):
        from opencis.cxl.cci.fabric_manager.pbr_switch.identify_pbr_switch import (
            IdentifyPbrSwitchCommand, IdentifyPbrSwitchResponsePayload,
        )
        mgr = make_manager(num_drts=2)
        cmd = IdentifyPbrSwitchCommand(mgr)
        req = IdentifyPbrSwitchCommand.create_cci_request()
        resp: CciResponse = run(cmd._execute(req))
        assert resp.return_code == CCI_RETURN_CODE.SUCCESS
        payload = IdentifyPbrSwitchResponsePayload.parse(resp.payload)
        assert payload.num_drts == 2

    def test_opcode(self):
        from opencis.cxl.cci.fabric_manager.pbr_switch.identify_pbr_switch import (
            IdentifyPbrSwitchCommand,
        )
        assert IdentifyPbrSwitchCommand.OPCODE == 0x5700


class TestConfigurePidAssignmentCommand:

    def test_assign_success(self):
        from opencis.cxl.cci.fabric_manager.pbr_switch.configure_pid_assignment import (
            ConfigurePidAssignmentCommand, ConfigurePidAssignmentRequestPayload,
            PidAssignmentEntry, PidAssignmentOperation,
        )
        mgr = make_manager()
        cmd = ConfigurePidAssignmentCommand(mgr)
        payload = ConfigurePidAssignmentRequestPayload(
            operation=PidAssignmentOperation.ASSIGN,
            entries=[PidAssignmentEntry(pid=0x010, target_id=0, instance_id=0)],
        )
        req = ConfigurePidAssignmentCommand.create_cci_request(payload)
        resp: CciResponse = run(cmd._execute(req))
        assert resp.return_code == CCI_RETURN_CODE.SUCCESS
        assert 0x010 in mgr._pid_assignments

    def test_duplicate_pid_different_target_fails(self):
        from opencis.cxl.cci.fabric_manager.pbr_switch.configure_pid_assignment import (
            ConfigurePidAssignmentCommand, ConfigurePidAssignmentRequestPayload,
            PidAssignmentEntry, PidAssignmentOperation,
        )
        mgr = make_manager()
        mgr.assign_pid(0x001, 0, 0)
        cmd = ConfigurePidAssignmentCommand(mgr)
        payload = ConfigurePidAssignmentRequestPayload(
            operation=PidAssignmentOperation.ASSIGN,
            entries=[PidAssignmentEntry(pid=0x001, target_id=1, instance_id=0)],
        )
        req = ConfigurePidAssignmentCommand.create_cci_request(payload)
        resp: CciResponse = run(cmd._execute(req))
        assert resp.return_code == CCI_RETURN_CODE.INVALID_INPUT

    def test_invalid_operation_rejected(self):
        from opencis.cxl.cci.fabric_manager.pbr_switch.configure_pid_assignment import (
            ConfigurePidAssignmentCommand, ConfigurePidAssignmentRequestPayload,
            PidAssignmentEntry,
        )
        mgr = make_manager()
        cmd = ConfigurePidAssignmentCommand(mgr)
        payload = ConfigurePidAssignmentRequestPayload(
            operation=0b111,  # reserved
            entries=[PidAssignmentEntry(pid=0x001, target_id=0, instance_id=0)],
        )
        req = ConfigurePidAssignmentCommand.create_cci_request(payload)
        resp: CciResponse = run(cmd._execute(req))
        assert resp.return_code == CCI_RETURN_CODE.INVALID_INPUT


class TestGetDrtCommand:

    def test_returns_entries(self):
        from opencis.cxl.cci.fabric_manager.pbr_switch.get_drt import (
            GetDrtCommand, GetDrtRequestPayload, GetDrtResponsePayload,
        )
        mgr = make_manager()
        mgr.set_drt(0, 0x005, [DrtEntry(DrtEntryType.PHYSICAL_PORT, 3)])
        cmd = GetDrtCommand(mgr)
        req = GetDrtCommand.create_cci_request(
            GetDrtRequestPayload(drt_index=0, start_entry=0x005, num_entries=1)
        )
        resp: CciResponse = run(cmd._execute(req))
        assert resp.return_code == CCI_RETURN_CODE.SUCCESS
        payload = GetDrtResponsePayload.parse(resp.payload)
        assert payload.entries[0].entry_type == DrtEntryType.PHYSICAL_PORT
        assert payload.entries[0].routing_target == 3

    def test_invalid_drt_index_returns_error(self):
        from opencis.cxl.cci.fabric_manager.pbr_switch.get_drt import (
            GetDrtCommand, GetDrtRequestPayload,
        )
        mgr = make_manager()
        cmd = GetDrtCommand(mgr)
        req = GetDrtCommand.create_cci_request(
            GetDrtRequestPayload(drt_index=99, start_entry=0, num_entries=1)
        )
        resp: CciResponse = run(cmd._execute(req))
        assert resp.return_code == CCI_RETURN_CODE.INVALID_INPUT


class TestSetDrtCommand:

    def test_programs_route(self):
        from opencis.cxl.cci.fabric_manager.pbr_switch.set_drt import (
            SetDrtCommand, SetDrtRequestPayload,
        )
        mgr = make_manager()
        cmd = SetDrtCommand(mgr)
        entries = [DrtEntry(DrtEntryType.PHYSICAL_PORT, 7)]
        req = SetDrtCommand.create_cci_request(
            SetDrtRequestPayload(drt_index=0, start_entry=0x042, entries=entries)
        )
        resp: CciResponse = run(cmd._execute(req))
        assert resp.return_code == CCI_RETURN_CODE.SUCCESS
        # Verify DRT was actually updated
        result, _ = mgr.get_drt(0, 0x042, 1)
        assert result[0].routing_target == 7

    def test_reserved_entry_type_rejected(self):
        from opencis.cxl.cci.fabric_manager.pbr_switch.set_drt import (
            SetDrtCommand, SetDrtRequestPayload,
        )
        mgr = make_manager()
        cmd = SetDrtCommand(mgr)
        entries = [DrtEntry(DrtEntryType.RESERVED, 0)]
        req = SetDrtCommand.create_cci_request(
            SetDrtRequestPayload(drt_index=0, start_entry=0, entries=entries)
        )
        resp: CciResponse = run(cmd._execute(req))
        assert resp.return_code == CCI_RETURN_CODE.INVALID_INPUT

    def test_fm_workflow_assign_then_set_drt(self):
        """Integration: PID assignment does not auto-populate DRT; FM must call set_drt."""
        from opencis.cxl.cci.fabric_manager.pbr_switch.configure_pid_assignment import (
            ConfigurePidAssignmentCommand, ConfigurePidAssignmentRequestPayload,
            PidAssignmentEntry, PidAssignmentOperation,
        )
        from opencis.cxl.cci.fabric_manager.pbr_switch.set_drt import (
            SetDrtCommand, SetDrtRequestPayload,
        )
        mgr = make_manager()

        # Step 1: Assign PID 0x042 to fabric port (target_id=0)
        assign_cmd = ConfigurePidAssignmentCommand(mgr)
        assign_req = ConfigurePidAssignmentCommand.create_cci_request(
            ConfigurePidAssignmentRequestPayload(
                operation=PidAssignmentOperation.ASSIGN,
                entries=[PidAssignmentEntry(pid=0x042, target_id=0, instance_id=0)],
            )
        )
        assign_resp = run(assign_cmd._execute(assign_req))
        assert assign_resp.return_code == CCI_RETURN_CODE.SUCCESS

        # DRT is still INVALID at this point
        result, _ = mgr.get_drt(0, 0x042, 1)
        assert result[0].entry_type == DrtEntryType.INVALID

        # Step 2: Program DRT[0][0x042] → port 3
        set_cmd = SetDrtCommand(mgr)
        set_req = SetDrtCommand.create_cci_request(
            SetDrtRequestPayload(
                drt_index=0, start_entry=0x042,
                entries=[DrtEntry(DrtEntryType.PHYSICAL_PORT, 3)],
            )
        )
        set_resp = run(set_cmd._execute(set_req))
        assert set_resp.return_code == CCI_RETURN_CODE.SUCCESS

        # Now DRT routes correctly
        result, _ = mgr.get_drt(0, 0x042, 1)
        assert result[0].entry_type == DrtEntryType.PHYSICAL_PORT
        assert result[0].routing_target == 3


class TestGetPidBindingCommand:

    def test_unbound_returns_fff(self):
        from opencis.cxl.cci.fabric_manager.pbr_switch.get_pid_binding import (
            GetPidBindingCommand, GetPidBindingRequestPayload, GetPidBindingResponsePayload,
        )
        mgr = make_manager()
        cmd = GetPidBindingCommand(mgr)
        req = GetPidBindingCommand.create_cci_request(
            GetPidBindingRequestPayload(target_vcs=0, target_vppb=0)
        )
        resp: CciResponse = run(cmd._execute(req))
        assert resp.return_code == CCI_RETURN_CODE.SUCCESS
        payload = GetPidBindingResponsePayload.parse(resp.payload)
        assert payload.pid == PID_UNASSIGNED

    def test_bound_returns_pid_and_hmat(self):
        from opencis.cxl.cci.fabric_manager.pbr_switch.get_pid_binding import (
            GetPidBindingCommand, GetPidBindingRequestPayload, GetPidBindingResponsePayload,
        )
        mgr = make_manager()
        mgr.configure_pid_binding(
            PidBindingOperation.BIND, 0, 2, 0x042,
            HmatInfo(latency_entry_base_unit=1000, latency_entry=5,
                     bw_entry_base_unit=200, bw_entry=2),
        )
        cmd = GetPidBindingCommand(mgr)
        req = GetPidBindingCommand.create_cci_request(
            GetPidBindingRequestPayload(target_vcs=0, target_vppb=2)
        )
        resp: CciResponse = run(cmd._execute(req))
        assert resp.return_code == CCI_RETURN_CODE.SUCCESS
        payload = GetPidBindingResponsePayload.parse(resp.payload)
        assert payload.pid == 0x042
        assert payload.latency_entry_base_unit == 1000
        assert payload.bw_entry == 2
