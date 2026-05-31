# CXL PBR & GFD Traceability Matrix

This traceability matrix maps the core architectural and functional requirements of the CXL 4.0 Port-Based Routing (PBR) and Generic Fabric Device (GFD) implementations to their specific validation test cases within the `opencis-core` testing suite.

## 1. Data Plane Requirements (PBR Routing)

| Requirement ID | Description | Verifying Test Case(s) | File Location | Status |
|---|---|---|---|---|
| **REQ-PBR-01** | The Switch Router must properly route ingress packets to the correct egress port based on the Dynamic Routing Table (DRT) entries. | `test_pbr_data_plane_routing` | `test_pbr_data_plane.py` | ✅ Passed |
| **REQ-PBR-02** | The switch must support Host-to-Device Memory (HDM) decoding to dynamically resolve generic memory addresses to target DPIDs. | `test_pbr_end_to_end_address_routing` | `test_pbr_data_plane.py` | ✅ Passed |
| **REQ-PBR-03** | Standard CXL.io and CXL.mem (HBR) packets must be correctly encapsulated into PBR flit headers at the ingress port boundary. | `test_hbr_to_pbr_encapsulation_and_decapsulation` | `test_pbr_packet_serialization.py` | ✅ Passed |
| **REQ-PBR-04** | PBR Flits must be decapsulated securely back into standard HBR packets at the egress port boundary. | `test_pbr_data_plane_routing` | `test_pbr_data_plane.py` | ✅ Passed |
| **REQ-PBR-05** | PBR Flit structures must correctly serialize and deserialize across the byte transport layer without corruption using `mixin.py` properties. | `test_hbr_to_pbr_encapsulation_and_decapsulation` | `test_pbr_packet_serialization.py` | ✅ Passed |

## 2. Control Plane Requirements (Fabric Manager CCI)

| Requirement ID | Description | Verifying Test Case(s) | File Location | Status |
|---|---|---|---|---|
| **REQ-CCI-01** | Fabric Manager must be able to identify the switch architecture via the standard `Identify PBR Switch` command. | `test_gfd_live_fm_identify_pbr_switch`<br>`test_success` (IdentifyPbrSwitchCommand) | `test_gfd_live_switch.py`<br>`test_pbr_switch_command_set.py` | ✅ Passed |
| **REQ-CCI-02** | FM must be able to assign, read, and clear Physical Port Identifiers (PIDs). | `test_gfd_live_fm_configure_pid_assignment`<br>`test_assign_pid_success`<br>`test_clear_pid_success` | `test_gfd_live_switch.py`<br>`test_pbr_switch_command_set.py` | ✅ Passed |
| **REQ-CCI-03** | FM must be able to logically bind PIDs to specific Virtual CXL Switch (vCS) contexts. | `test_gfd_live_fm_configure_pid_binding`<br>`test_bind_and_get_binding` | `test_gfd_live_switch.py`<br>`test_pbr_switch_command_set.py` | ✅ Passed |
| **REQ-CCI-04** | FM must be able to write (Set) and read (Get) routing instructions in the Dynamic Routing Table (DRT). | `test_gfd_live_fm_set_and_get_drt`<br>`test_set_drt_multiple_entries`<br>`test_programs_route` | `test_gfd_live_switch.py`<br>`test_pbr_switch_command_set.py` | ✅ Passed |
| **REQ-CCI-05** | Switch must reject invalid configurations (e.g. duplicate PIDs, reserved DRT modes, OOB indices). | `test_set_drt_out_of_range_index`<br>`test_set_drt_reserved_entry_type_rejected`<br>`test_assign_pid_invalid_target` | `test_pbr_switch_command_set.py` | ✅ Passed |

## 3. Endpoint Requirements (Generic Fabric Device)

| Requirement ID | Description | Verifying Test Case(s) | File Location | Status |
|---|---|---|---|---|
| **REQ-GFD-01** | The GFD must properly initialize, expose standard CXL Type 3 capabilities, and gracefully shutdown without leaking background tasks. | `test_gfd_starts_and_stops`<br>`test_gfd_bar_size` | `test_gfd_device.py` | ✅ Passed |
| **REQ-GFD-02** | The GFD must expose the mandatory baseline MMIO registers (Device ID, Status flags). | `test_gfd_registers_device_id_sentinel`<br>`test_gfd_registers_status_ready` | `test_gfd_device.py` | ✅ Passed |
| **REQ-GFD-03** | The GFD must support a standard validation register (Scratchpad) for Memory Read/Write verification. | `test_gfd_scratchpad_roundtrip`<br>`test_gfd_access_counter_increments` | `test_gfd_device.py` | ✅ Passed |
| **REQ-GFD-04** | The GFD must be attachable as a Downstream Port to a live PBR switch and successfully interact with the Fabric Manager. | `test_gfd_live_full_fm_workflow`<br>`test_gfd_cci_identify` | `test_gfd_live_switch.py`<br>`test_gfd_device.py` | ✅ Passed |
