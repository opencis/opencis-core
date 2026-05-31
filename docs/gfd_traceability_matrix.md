# GFD / PBR — Requirements Traceability Matrix

**Project:** opencis-core CXL 4.0 PBR Simulator  
**Spec Reference:** CXL Specification Rev 4.0 Version 1.0, §7.7.13  
**Date:** May 2026  
**Status:** All requirements implemented ✅  
**Total Test Cases:** 25 across 6 test files

---

## 1. Requirement Traceability Table

| Req ID | Spec § | Requirement | Implementation Class / Method | Test Case(s) | # Tests | Status |
|--------|--------|-------------|-------------------------------|--------------|:-------:|--------|
| GFD-REQ-001 | §7.7.13.1 | Identify PBR Switch MUST return `num_drts ≥ 1` | `PbrSwitchManager.get_identify_info()` → `IdentifyPbrSwitchCommand._execute()` | `test_gfd_live_fm_identify_pbr_switch`, `test_gfd_live_full_fm_workflow` | **2** | ✅ Implemented |
| GFD-REQ-002 | §7.7.13.1 | `num_drts` in Identify response MUST reflect actual DRT table count (not cached metadata) | `PbrSwitchManager.get_identify_info()` — derives from `len(self._drt_tables)` | `test_gfd_live_fm_identify_pbr_switch` | **1** | ✅ Fixed & Implemented |
| GFD-REQ-003 | §7.7.13.5 | Configure PID Assignment MUST validate `target_id` against registered `_pid_targets` | `PbrSwitchManager.assign_pid()` — scans `_pid_targets` list | `test_gfd_live_fm_configure_pid_assignment`, `test_gfd_live_full_fm_workflow` | **2** | ✅ Implemented |
| GFD-REQ-004 | §7.7.13.5 | Duplicate PID assigned to a **different** target MUST return `INVALID_INPUT` | `PbrSwitchManager.assign_pid()` — `_pid_assignments` conflict check | `test_gfd_live_fm_configure_pid_assignment` | **1** | ✅ Implemented |
| GFD-REQ-005 | §7.7.13.5 | Idempotent PID re-assignment to the **same** target MUST return `SUCCESS` | `PbrSwitchManager.assign_pid()` — idempotent early-exit path | `test_gfd_live_fm_configure_pid_assignment` | **1** | ✅ Implemented |
| GFD-REQ-006 | §7.7.13.5 | Clear PID MUST succeed only if PID was previously assigned | `PbrSwitchManager.clear_pid()` — checks `_pid_assignments` dict | `test_gfd_live_full_fm_workflow`, `test_pbr_switch_command_set.py` | **2** | ✅ Implemented |
| GFD-REQ-007 | §7.7.13.6 | Get PID Binding MUST accept `(target_vcs, target_vppb)` as lookup key | `GetPidBindingRequestPayload(target_vcs, target_vppb)` | `test_gfd_live_fm_get_pid_binding`, `test_gfd_live_full_fm_workflow` | **2** | ✅ Implemented |
| GFD-REQ-008 | §7.7.13.6 | Get PID Binding MUST return `0xFFF` (`PID_UNASSIGNED`) for an unbound slot | `PbrSwitchManager.get_pid_binding()` → `None` → `pid=PID_UNASSIGNED` | `test_gfd_live_fm_get_pid_binding`, `test_gfd_live_full_fm_workflow` | **2** | ✅ Implemented |
| GFD-REQ-009 | §7.7.13.7 | Configure PID Binding IS a CCI **background** command | `ConfigurePidBindingCommand(CciBackgroundCommand)` — class hierarchy | `test_gfd_live_fm_configure_pid_binding`, `test_gfd_live_full_fm_workflow` | **2** | ✅ Implemented |
| GFD-REQ-010 | §7.7.13.7 | Background command MUST report progress via callback (10 → 50 → 100%) | `ConfigurePidBindingCommand._execute()` — `await callback(10/50/100)` | `test_gfd_live_fm_configure_pid_binding` | **1** | ✅ Implemented |
| GFD-REQ-011 | §7.7.13.7 | Unbind MUST return `INVALID_INPUT` if `(vcs_id, vppb_id)` slot was never bound | `PbrSwitchManager.configure_pid_binding()` UNBIND path | `test_pbr_switch_command_set.py` (2 tests) | **2** | ✅ Implemented |
| GFD-REQ-012 | §7.7.13.9 | DRT `entry_type = RESERVED (0b11)` MUST be rejected with `INVALID_INPUT` | `PbrSwitchManager.set_drt()` — RESERVED type check loop | `test_gfd_live_fm_set_and_get_drt` | **1** | ✅ Implemented |
| GFD-REQ-013 | §7.7.13.9 | DRT out-of-range `drt_index` MUST return `INVALID_INPUT` | `PbrSwitchManager.set_drt()` and `get_drt()` — bounds check | `test_gfd_live_fm_set_and_get_drt` | **1** | ✅ Implemented |
| GFD-REQ-014 | §7.7.13.9 | DRT `PHYSICAL_PORT` entry MUST route packet to the specified egress port | `PbrSwitchRouter._route_packet()` — DRT index lookup → port dispatch | `test_pbr_qemu_e2e_dsp_ingress`, `test_pbr_data_plane.py` (3 tests) | **4** | ✅ Implemented |
| GFD-REQ-015 | §7.7.13.8 | Get DRT MUST read back exactly the entries programmed by Set DRT | `PbrSwitchManager.get_drt()` reads same `_drt_tables[i].entries` as `set_drt()` | `test_gfd_live_fm_set_and_get_drt`, `test_gfd_live_full_fm_workflow` | **2** | ✅ Implemented |
| GFD-REQ-016 | §7.6.2 | CCI commands MUST be transported over TCP (MCTP-over-TCP) | `MctpConnectionManager` + `MctpConnectionClient` + `MctpPacketProcessor` | All 6 tests in `test_gfd_live_switch.py` | **6** | ✅ Implemented |
| GFD-REQ-017 | §7.6.2 | CCI executor MUST dispatch opcodes to registered command handlers only | `MctpCciExecutor.register_cci_commands()` + opcode → handler dispatch map | `test_mctp_fm_port.py` (7 tests) | **7** | ✅ Implemented |
| GFD-REQ-018 | §7.7.7 | PBR router MUST encapsulate TLPs with SPID/DPID PBR header on ingress | `PbrSwitchRouter._encapsulate_pbr()` | `test_pbr_data_plane.py`, `test_pbr_packet_serialization.py` | **4** | ✅ Implemented |
| GFD-REQ-019 | §7.7.7 | HDM decoder MUST resolve host memory address to a DPID | `PbrHdmDecoderManager.resolve_address()` | `test_pbr_qemu_e2e_usp_ingress`, `test_pbr_qemu_e2e_bidirectional` | **2** | ✅ Implemented |
| GFD-REQ-020 | §7.7.7 | Bidirectional routing (Host→GFD **and** GFD→Host) MUST be supported | `PbrSwitchRouter` — USP ingress path + DSP ingress path | `test_pbr_qemu_e2e_bidirectional`, `test_pbr_qemu_e2e_usp_ingress` | **2** | ✅ Implemented |
| GFD-REQ-021 | §7.7.13.1 | GAE Support Map MUST be an 8-byte little-endian bitmask (bit pos = VCS ID) | `IdentifyPbrSwitchResponsePayload.gae_support_map` — 8 bytes LE wire format | `test_gfd_live_fm_identify_pbr_switch` | **1** | ✅ Implemented |
| GFD-REQ-022 | §7.7.13.1 | Dynamic Routing Mode capabilities MUST be reported in byte `0x0B` of response | `PbrSwitchInfo.routing_caps_byte()` — bitmask construction | `test_gfd_live_fm_identify_pbr_switch` | **1** | ✅ Implemented |
| GFD-REQ-023 | §8.2 | GFD MUST respond to CXL CCI Identify Device command | `CxlGfdDevice` — BAR-0 register layout + CCI mailbox handler | `test_gfd_cci_identify`, `test_gfd_starts_and_stops` | **2** | ✅ Implemented |
| GFD-REQ-024 | §8.2 | GFD BAR-0 MUST have a valid MMIO size (≥ 256 bytes) | `CxlGfdDevice._BAR0_SIZE` — enforced in device init | `test_gfd_bar_size` | **1** | ✅ Implemented |
| GFD-REQ-025 | §8.2 | GFD status register MUST report `READY` after initialization completes | `GfdMmioBlock.status = READY` set inside `_run()` | `test_gfd_registers_status_ready`, `test_gfd_starts_and_stops` | **2** | ✅ Implemented |

> **Column guide:** `# Tests` = number of distinct test functions that exercise this requirement (counting cross-file coverage; a test covering multiple requirements is counted once per requirement row).

---

## 2. Test-to-Requirement Reverse Lookup

| Test File | Test Function | # Req Covered | Requirements Covered |
|-----------|---------------|:-------------:|---------------------|
| `test_gfd_live_switch.py` | `test_gfd_live_fm_identify_pbr_switch` | 4 | GFD-REQ-001, GFD-REQ-002, GFD-REQ-021, GFD-REQ-022 |
| `test_gfd_live_switch.py` | `test_gfd_live_fm_configure_pid_assignment` | 3 | GFD-REQ-003, GFD-REQ-004, GFD-REQ-005 |
| `test_gfd_live_switch.py` | `test_gfd_live_fm_get_pid_binding` | 2 | GFD-REQ-007, GFD-REQ-008 |
| `test_gfd_live_switch.py` | `test_gfd_live_fm_configure_pid_binding` | 2 | GFD-REQ-009, GFD-REQ-010 |
| `test_gfd_live_switch.py` | `test_gfd_live_fm_set_and_get_drt` | 3 | GFD-REQ-012, GFD-REQ-013, GFD-REQ-015 |
| `test_gfd_live_switch.py` | `test_gfd_live_full_fm_workflow` | 10 | GFD-REQ-001, GFD-REQ-003, GFD-REQ-006–REQ-009, GFD-REQ-015 |
| `test_pbr_qemu_e2e.py` | `test_pbr_qemu_e2e_dsp_ingress` | 2 | GFD-REQ-014, GFD-REQ-018 |
| `test_pbr_qemu_e2e.py` | `test_pbr_qemu_e2e_usp_ingress` | 2 | GFD-REQ-019, GFD-REQ-020 |
| `test_pbr_qemu_e2e.py` | `test_pbr_qemu_e2e_bidirectional` | 2 | GFD-REQ-019, GFD-REQ-020 |
| `test_gfd_device.py` | `test_gfd_starts_and_stops` | 2 | GFD-REQ-023, GFD-REQ-025 |
| `test_gfd_device.py` | `test_gfd_bar_size` | 1 | GFD-REQ-024 |
| `test_gfd_device.py` | `test_gfd_registers_device_id_sentinel` | 1 | GFD-REQ-023 |
| `test_gfd_device.py` | `test_gfd_registers_status_ready` | 1 | GFD-REQ-025 |
| `test_gfd_device.py` | `test_gfd_scratchpad_roundtrip` | 1 | GFD-REQ-023 |
| `test_gfd_device.py` | `test_gfd_access_counter_increments` | 1 | GFD-REQ-023 |
| `test_gfd_device.py` | `test_gfd_cci_identify` | 1 | GFD-REQ-023 |
| `test_mctp_fm_port.py` | 7 tests | 1 | GFD-REQ-017 |
| `test_pbr_data_plane.py` | 3 tests | 2 | GFD-REQ-014, GFD-REQ-018 |
| `test_pbr_packet_serialization.py` | 2 tests | 1 | GFD-REQ-018 |
| `test_pbr_switch_command_set.py` | ~17 tests | 3 | GFD-REQ-006, GFD-REQ-011, GFD-REQ-016 |

---

## 3. Coverage Summary

| Category | Requirements | Test Functions | Implemented | Tested | Req Coverage |
|----------|:------------:|:--------------:|:-----------:|:------:|:------------:|
| Identify PBR Switch | 4 | 5 | 4 | 4 | **100%** |
| PID Assignment | 4 | 6 | 4 | 4 | **100%** |
| PID Binding | 3 | 5 | 3 | 3 | **100%** |
| DRT Programming | 4 | 6 | 4 | 4 | **100%** |
| MCTP Transport | 2 | 13 | 2 | 2 | **100%** |
| Data Plane Routing | 3 | 8 | 3 | 3 | **100%** |
| GFD Device | 3 | 7 | 3 | 3 | **100%** |
| **TOTAL** | **25** | **~50** | **25** | **25** | **100%** |

> `Test Functions` counts individual pytest functions across all files exercising that category (with overlap — a test covering two categories is counted in both rows).

---

## 4. Per-File Test Count

| Test File | # Test Functions | Category |
|-----------|:----------------:|----------|
| `test_gfd_live_switch.py` | 6 | GFD commissioning via live MCTP/TCP |
| `test_gfd_device.py` | 7 | GFD device MMIO, registers, CCI |
| `test_pbr_switch_command_set.py` | ~17 | PBR CCI command set unit tests |
| `test_pbr_qemu_e2e.py` | 3 | Data plane E2E routing |
| `test_pbr_data_plane.py` | 3 | PBR router unit tests |
| `test_pbr_packet_serialization.py` | 2 | PBR packet wire format |
| `test_mctp_fm_port.py` | 7 | FM MCTP CCI port (port 8300) |
| `test_gae_commands.py` | ~5 | GAE CCI commands |
| `test_fabric_crawl_out.py` | ~3 | Fabric crawl-out sequence |
| **TOTAL** | **≥ 53** | |
