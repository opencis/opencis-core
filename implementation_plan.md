# Implementation Plan: Porting PBR to `v0.5-dev`

Because the `v0.5-dev` branch introduces a massive architectural overhaul to the packet serialization framework (migrating from Python `UnalignedBitStructure` to C-extensions generated via `generate_packet_structs.py`), a simple Git cherry-pick from `main` fails with heavy merge conflicts and broken imports.

To properly implement CXL 4.0 Port-Based Routing on `v0.5-dev`, we must port the logic to fit the new architecture.

## Proposed Changes

### 1. Transport Layer Modernization (`opencis/cxl/transport/`)
Instead of defining `PbrBasePacket` manually via bit structures, we will inject it into the code generator.
* **`packet_constants.py`**: Add `PBR = 5` to `SYSTEM_PAYLOAD_TYPE`.
* **`fields.py`**: Add the 32-bit `PbrHeader`:
  ```python
  PbrHeader = [
      ("spid", 0, 12),
      ("dpid", 12, 12),
      ("reserved", 24, 8),
  ]
  ```
* **`packets.py`**: Add `PbrBasePacket` definition mapping `SystemHeader` and `PbrHeader`.
* **Code Generation**: Re-run `python opencis/cxl/transport/generate_packet_structs.py` to compile the C-extension structs for the PBR wrappers.
* **`mixin.py`**: Add `is_pbr()` to `BasePacketMixin`.

### 2. Control Plane & Edge Translation
These components remain structurally identical but need their packet imports updated.
* **`PbrSwitchManager`**: Port the DRT and PID Binding management exactly as it was on `main`.
* **`PbrHdmDecoderManager`**: Port the DPID translation logic to `opencis/cxl/component/hdm_decoder.py`.
* **CCI Commands**: Port the PBR-specific fabric management commands (`identify_pbr_switch.py`, etc.).

### 3. Data Plane Router (`pbr_switch_router.py`)
The asynchronous routing engine will be ported over.
* **Encapsulation Logic Update**: Since `v0.5-dev` packets are C-structs, the encapsulation logic will change slightly. We will instantiate `PbrBasePacket.create(payload_type=5, spid=x, dpid=y)`, extract its bytes (`get_bytes()`), append the `inner_packet` bytes, and then recreate it as a raw byte stream so the C-extension parses it correctly.

### 4. Testing
* Bring over `test_pbr_data_plane.py` and `test_pbr_switch_command_set.py`.
* Ensure they pass natively under the `v0.5-dev` execution environment.

## User Review Required
Does this adaptation to the `v0.5-dev` C-extension packet generator align with your expectations for the branch? If approved, I will proceed with generating the new C-structs and migrating the routing engine!
