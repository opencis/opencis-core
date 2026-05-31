# CXL 4.0 Port-Based Routing (PBR) — Design & Implementation Guide

> **opencis-core · v0.5-dev · May 2026**

---

## 1. What is PBR?

Port-Based Routing (PBR) is a CXL 4.0 fabric routing mechanism defined in §7.7.13 of the CXL Specification Rev 4.0 v1.0.

Unlike the virtual-switch model (HBR — Host-Based Routing), where a host OS drives PCIe enumeration, PBR allows the **Fabric Manager (FM)** to assign numeric Port IDs (PIDs) to physical ports and program a **DPID Routing Table (DRT)** that the switch hardware uses to route TLPs by their destination PID.

### Key Concepts

| Term | Meaning |
|------|---------|
| **PID** | Port ID — a 12-bit identifier assigned by the FM to a physical port |
| **SPID** | Source PID — the PID of the ingress port |
| **DPID** | Destination PID — the PID the packet is routed *to* |
| **DRT** | DPID Routing Table — maps DPID → egress physical port or RGT index |
| **PBR TLP Header (PTH)** | 6-byte header prepended to a TLP: `[SystemHeader 2B][PbrHeader 4B]` |
| **HBR** | Host-Based Routing — standard PCIe TLP without PBR header |
| **Ingress Edge Port** | First PBR switch port that receives HBR traffic; encapsulates to PBR |
| **Egress Edge Port** | Last PBR switch port before a non-PBR host; strips PBR header |

---

## 2. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                    QEMU Host / FM CLI                           │
│                    (Socket.IO client)                           │
└──────────────────────────┬──────────────────────────────────────┘
                           │ Socket.IO  pbr:setDrt / pbr:identify …
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│           FabricManagerSocketIoServer                           │
│    socketio_server.py  ·  Port 8200                             │
│                                                                 │
│  _pbr_identify()        _pbr_configure_pid()                    │
│  _pbr_get_pid_binding() _pbr_configure_pid_binding()            │
│  _pbr_get_drt()         _pbr_set_drt()                          │
└──────────────────────────┬──────────────────────────────────────┘
                           │ calls MctpCciApiClient methods
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│            MctpCciApiClient                                     │
│    mctp_cci_api_client.py                                       │
│                                                                 │
│  identify_pbr_switch()     configure_pid_assignment()           │
│  get_pid_binding()         configure_pid_binding()              │
│  get_drt()                 set_drt()                            │
└──────────────────────────┬──────────────────────────────────────┘
                           │ CCI packets over TCP (port 8100)
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│           MctpCciExecutor  (inside CxlSwitch)                   │
│    mctp_cci_executor.py                                         │
│                                                                 │
│  Dispatches by opcode to registered CciCommand handlers         │
└──────────────────────────┬──────────────────────────────────────┘
                           │
          ┌────────────────┼──────────────────┐
          │                │                  │
          ▼                ▼                  ▼
  IdentifyPbrSwitch  SetDrtCommand    ConfigurePidAssignment
  Command            (5709h)          Command (5704h)
  (5700h)                             … etc.
          │                │
          └────────────────┤
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│              PbrSwitchManager                                   │
│    pbr_switch_manager.py                                        │
│                                                                 │
│  PID table:  pid → (target_id, instance_id)                     │
│  DRT:        drt[drt_index][dpid] → DrtEntry                    │
│  Bindings:   pid → bound_pid / hmat_entry_index                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. Data Plane — Packet Flow

### 3.1 HBR Ingress → PBR Encapsulation

```
CXL Device / QEMU                   PbrSwitchRouter
─────────────────                   ───────────────
HBR TLP (CxlIoMemRdPacket)
  system_header.payload_type = CXL_IO (1)
  cxl_io_header.addr = 0x1500
         │
         │  put to port_fifos[0].target_to_host
         ▼
    _route_packet(ingress_port=0, packet)
         │
         │  is_pbr() == False  →  HBR path
         │
         │  PbrHdmDecoderManager.lookup_dpid(addr=0x1500)
         │       returns DPID = 0x123
         │
         │  PbrBasePacket.encapsulate(spid=0, dpid=0x123,
         │                            inner_packet=hbr_pkt)
         │       → PBR TLP:
         │         [SystemHeader: payload_type=5]
         │         [PbrHeader:   spid=0, dpid=0x123]
         │         [HBR payload bytes...]
         │
         │  recurse: _route_packet(0, pbr_packet)
         │
         │  is_pbr() == True  →  PBR path
         │  pbr_manager.get_drt(0, dpid=0x123)
         │       returns DrtEntry(PHYSICAL_PORT, target=2)
         │
         └──► port_fifos[2].host_to_target.put(inner_packet)
                   (inner_packet = original hbr_pkt, zero-copy)
```

### 3.2 PBR Decapsulation at Egress

```
Upstream PBR Switch                 PbrSwitchRouter
───────────────────                 ───────────────
PBR TLP
  system_header.payload_type = PBR (5)
  pbr_header.dpid = 0x123
         │
         │  put to port_fifos[N].target_to_host
         ▼
    _route_packet(ingress_port=N, pbr_packet)
         │
         │  is_pbr() == True
         │  pbr_manager.get_drt(0, dpid=0x123)
         │       returns DrtEntry(PHYSICAL_PORT, target=2)
         │
         │  inner = pbr_packet._inner_packet   (stash from encapsulate)
         │     or   BasePacket(pbr_packet_payload_bytes)  (wire path)
         │
         └──► port_fifos[2].host_to_target.put(inner_packet)
```

---

## 4. Transport Layer Changes

### 4.1 New Fields (`fields.py`)

```python
PbrHeader = [
    ("spid",     0,  12),   # bits 0–11   Source PID
    ("dpid",     12, 12),   # bits 12–23  Destination PID
    ("reserved", 24, 8),    # bits 24–31  Reserved
]
```

### 4.2 New Packet (`packets.py` + `packet_constants.py`)

```
SYSTEM_PAYLOAD_TYPE.PBR = 5

PbrBasePacket wire layout (6 bytes header):
  ┌──────────────────────┬────────────────────────────┐
  │ SystemHeader  [2 B]  │ PbrHeader  [4 B]           │
  │ payload_type = 5     │ spid[11:0] | dpid[11:0]    │
  └──────────────────────┴────────────────────────────┘
  [inner TLP bytes ...]
```

### 4.3 Pure-Python Fallback (`packet_structs.py`)

Because MSVC is not available in this environment, the Cython `packet_structs.pyx` extension cannot be compiled. The generator script `generate_py_fallback.py` produces `packet_structs.py` — a complete pure-Python drop-in.

**Critical fix**: field bit-offsets must account for the struct's byte offset in the shared buffer:
```python
# Wrong (previous):
return _read_bits(self._parent_buf, {start}, {width})

# Correct (fixed):
return _read_bits(self._parent_buf, self._p * 8 + {start}, {width})
```

When the Cython `.pyd` extension is compiled, Python will automatically prefer it over the `.py` fallback.

---

## 5. PBR HDM Decoder (`hdm_decoder.py`)

Resolves a Host Physical Address (HPA) to a DPID at ingress:

```python
@dataclass
class PbrHdmDecoder:
    index: int
    base: int        # HPA base
    size: int        # region size in bytes
    ig: int          # interleave granularity
    iw: int          # interleave ways
    target_dpids: List[int]

    def get_dpid(self, hpa: int) -> Optional[int]:
        if self.base <= hpa < self.base + self.size:
            return self.target_dpids[0]
        return None

class PbrHdmDecoderManager:
    def lookup_dpid(self, hpa: int) -> Optional[int]: ...
    def commit(self, index, base, size, ig, iw, target_dpids): ...
```

---

## 6. PBR Switch Manager (`pbr_switch_manager.py`)

Central control-plane state store. **Stateless across restarts** (FM re-programs on reconnect).

```python
class PbrSwitchManager:
    # PID → (target_id, instance_id)
    _pid_table: Dict[int, Tuple[int, int]]

    # DRT: drt_index → {dpid: DrtEntry}
    _drt: Dict[int, Dict[int, DrtEntry]]

    # Bindings: pid → (bound_pid, hmat_entry_index)
    _bindings: Dict[int, Tuple[int, int]]

    def assign_pid(pid, target_id, instance_id) -> CCI_RETURN_CODE
    def clear_pid(pid, target_id, instance_id) -> CCI_RETURN_CODE
    def set_drt(drt_index, start_entry, entries) -> CCI_RETURN_CODE
    def get_drt(drt_index, start_entry, num_entries) -> Optional[Tuple[List, int]]
    def bind_pid(pid, target_pid, hmat_entry_index) -> CCI_RETURN_CODE
    def get_binding(pid) -> Optional[Tuple[int, int]]
    def get_identify_info() -> SwitchIdentifyInfo
```

---

## 7. CCI Commands — Opcodes & Payloads

| Command | Opcode | Request | Response |
|---------|--------|---------|----------|
| Identify PBR Switch | `0x5700` | None | `{gae_support_map, num_drts, num_rgts, routing_caps}` |
| Configure PID Assignment | `0x5704` | `{operation, entries[{pid, target_id, instance_id}]}` | None |
| Get PID Binding | `0x5705` | `{pid}` | `{pid, bound_pid, hmat_entry_index}` |
| Configure PID Binding | `0x5706` | `{pid, target_pid, hmat_entry_index}` | None |
| Get DRT | `0x5708` | `{drt_index, start_entry, num_entries}` | `{drt_index, start_entry, assoc_rgt, entries[{entry_type, routing_target}]}` |
| Set DRT | `0x5709` | `{drt_index, start_entry, entries[{entry_type, routing_target}]}` | None |

> **FM Workflow**:
> 1. `Identify PBR Switch (5700h)` — discover capabilities
> 2. `Configure PID Assignment (5704h)` — assign PIDs to physical ports
> 3. `Set DRT (5709h)` — program DPID → egress port routing
> 4. *(Optional)* `Configure PID Binding (5706h)` — bind PIDs for host-visible topology
> 5. Traffic flows automatically through `PbrSwitchRouter`

---

## 8. FM Integration — Socket.IO API

The `FabricManagerSocketIoServer` exposes these new events (same JSON over Socket.IO as all other FM commands):

### `pbr:identify`
```json
// Request: (no payload)
// Response:
{ "error": "", "result": { "gaeSupportMap": 0, "numDrts": 1, "numRgts": 0, "routingCaps": 0 } }
```

### `pbr:configurePid`
```json
// Request:
{ "operation": 0, "entries": [{ "pid": 291, "targetId": 2, "instanceId": 0 }] }
// Response:
{ "error": "", "result": "SUCCESS" }
```

### `pbr:getPidBinding`
```json
// Request:
{ "pid": 291 }
// Response:
{ "error": "", "result": { "pid": 291, "boundPid": 4095, "hmatEntryIndex": 0 } }
```

### `pbr:configurePidBinding`
```json
// Request:
{ "pid": 291, "targetPid": 1110, "hmatEntryIndex": 0 }
// Response:
{ "error": "", "result": "SUCCESS" }
```

### `pbr:getDrt`
```json
// Request:
{ "drtIndex": 0, "startEntry": 291, "numEntries": 1 }
// Response:
{ "error": "", "result": { "drtIndex": 0, "startEntry": 291, "associatedRgtIndex": 0,
  "entries": [{ "entryType": "PHYSICAL_PORT", "routingTarget": 2 }] } }
```

### `pbr:setDrt`
```json
// Request:
{ "drtIndex": 0, "startEntry": 291,
  "entries": [{ "entryType": "PHYSICAL_PORT", "routingTarget": 2 }] }
// Response:
{ "error": "", "result": "SUCCESS" }
```

---

## 9. Modified Files Summary

| File | Status | Purpose |
|------|--------|---------|
| `opencis/cxl/transport/packet_constants.py` | Modified | `SYSTEM_PAYLOAD_TYPE.PBR = 5` |
| `opencis/cxl/transport/fields.py` | Modified | Added `PbrHeader` field layout |
| `opencis/cxl/transport/packets.py` | Modified | Added `PbrBasePacket` composite |
| `opencis/cxl/transport/mixin.py` | Modified | Added `is_pbr()` to `BasePacketMixin` |
| `opencis/cxl/transport/generate_py_fallback.py` | **New** | Generates pure-Python `packet_structs.py` |
| `opencis/cxl/transport/pbr_packets.py` | **New** | `PbrBasePacket` with `create()` / `encapsulate()` |
| `opencis/cxl/transport/packet_structs.py` | Generated | Pure-Python drop-in for Cython extension |
| `opencis/cxl/component/hdm_decoder.py` | Modified | Added `PbrHdmDecoder` + `PbrHdmDecoderManager` |
| `opencis/cxl/component/pbr_switch_manager.py` | **New** | PID table, DRT, bindings — full control-plane state |
| `opencis/cxl/component/pbr_switch_router.py` | **New** | Async data-plane engine (encap/decap/route) |
| `opencis/cxl/cci/common.py` | Modified | Added 6 PBR opcode entries to `CCI_FM_API_COMMAND_OPCODE` |
| `opencis/cxl/cci/fabric_manager/pbr_switch/__init__.py` | **New** | Package exports |
| `opencis/cxl/cci/fabric_manager/pbr_switch/identify_pbr_switch.py` | **New** | Opcode 0x5700 |
| `opencis/cxl/cci/fabric_manager/pbr_switch/configure_pid_assignment.py` | **New** | Opcode 0x5704 |
| `opencis/cxl/cci/fabric_manager/pbr_switch/get_pid_binding.py` | **New** | Opcode 0x5705 |
| `opencis/cxl/cci/fabric_manager/pbr_switch/configure_pid_binding.py` | **New** | Opcode 0x5706 |
| `opencis/cxl/cci/fabric_manager/pbr_switch/get_drt.py` | **New** | Opcode 0x5708 |
| `opencis/cxl/cci/fabric_manager/pbr_switch/set_drt.py` | **New** | Opcode 0x5709 |
| `opencis/cxl/component/mctp/mctp_cci_api_client.py` | Modified | 6 new PBR async client methods |
| `opencis/cxl/component/fabric_manager/socketio_server.py` | Modified | 6 new `pbr:*` Socket.IO handlers |
| `opencis/apps/cxl_switch.py` | Modified | `enable_pbr` flag + PBR command registration |
| `tests/test_pbr_data_plane.py` | **New** | Integration tests (2 tests) |
| `tests/test_pbr_switch_command_set.py` | **New** | CCI command unit tests (45 tests) |
| `pbr_cli_test.py` | **New** | Standalone FM command smoke-test |

---

## 10. Testing

Three testing modes are available, from simplest to most complete.

| Mode | Script | Requires | Checks |
|------|--------|----------|--------|
| **Standalone in-process** | `py pbr_standalone_test.py` | Nothing | 27 |
| **pytest suite** | `py -m pytest tests/test_pbr_*.py` | Nothing | 47 |
| **Live switch + MCTP** | `py pbr_cli_test.py` | Running switch | 6 |

---

### 10.1 Standalone In-Process Test (recommended first step)

Tests all 6 PBR CCI commands **without a running switch, server, or QEMU**.
The script calls the command handlers directly in-process — exactly how the
switch executes them when a real FM sends them over the wire.

#### How it works internally

```
pbr_standalone_test.py
        |
        |  Creates PbrSwitchManager with 2 pre-registered PidTargets
        |  (ports 2 and 3) so assign_pid() can validate them
        |
        +--[1]--> IdentifyPbrSwitchCommand._execute()      [0x5700]
        |              |
        |              +--> PbrSwitchManager.get_identify_info()
        |              +--> Checks: num_drts >= 1, gae_support_map type
        |
        +--[2]--> ConfigurePidAssignmentCommand._execute() [0x5704]
        |              |
        |              +--> PbrSwitchManager.assign_pid(0x100, target=2)
        |              +--> PbrSwitchManager.assign_pid(0x200, target=3)
        |              +--> Checks: success, duplicate rejection, idempotent assign
        |
        +--[3]--> GetPidBindingCommand._execute()          [0x5705]
        |              |
        |              +--> PbrSwitchManager.get_pid_binding(vcs=0, vppb=0)
        |              +--> Checks: pid=0xFFF (unbound before bind)
        |
        +--[4]--> ConfigurePidBindingCommand._execute()    [0x5706]
        |              |
        |              +--> PbrSwitchManager.configure_pid_binding(BIND,
        |              |        vcs=0, vppb=0, pid=0x100, hmat={lat=5, bw=10})
        |              +--> Checks: SUCCESS, GetPidBinding now shows pid=0x100
        |
        +--[5]--> SetDrtCommand._execute()                 [0x5709]
        |              |
        |              +--> PbrSwitchManager.set_drt(0, start=0x100,
        |              |        [DrtEntry(PHYSICAL_PORT, target=2)])
        |              +--> Checks: SUCCESS, RESERVED rejection, bad index
        |
        +--[6]--> GetDrtCommand._execute()                 [0x5708]
        |              |
        |              +--> PbrSwitchManager.get_drt(0, start=0x100, num=1)
        |              +--> Checks: entry type, routing_target, multi-read,
        |                          INVALID unset entry, bad index rejection
        |
        +--[B]--> ConfigurePidAssignmentCommand._execute() [0x5704 CLEAR]
                       |
                       +--> PbrSwitchManager.clear_pid(0x100, target=2)
                       +--> Checks: clear SUCCESS, re-assign to new target
```

#### Steps to run

**Step 1** — Open a command prompt and go to the repo:

```cmd
cd C:\Users\pavan\Desktop\cxl\opencis-core
```

**Step 2** — Run the test:

```cmd
py pbr_standalone_test.py
```

**No other steps required.** No switch to start. No ports to open.

#### Expected output

```
PBR FM CCI Commands  --  In-Process Smoke-Test
No running switch required. Tests command handlers directly.

--------------------------------------------------------------
  1. Identify PBR Switch  [0x5700]
--------------------------------------------------------------
  [PASS]  Return code SUCCESS
  [PASS]  num_drts >= 1  (num_drts=1)
  [PASS]  gae_support_map is int  (0x0000000000000000)
  [PASS]  routing_caps is int  (0x00)

--------------------------------------------------------------
  2. Configure PID Assignment  (ASSIGN)  [0x5704]
--------------------------------------------------------------
  [PASS]  Assign PID 0x100 -> port 2 and PID 0x200 -> port 3
  [PASS]  Duplicate PID to different target -> INVALID_INPUT  (rc=INVALID_INPUT)
  [PASS]  Re-assign same PID to same target (idempotent) -> SUCCESS

--------------------------------------------------------------
  3. Get PID Binding  (before bind)  [0x5705]
--------------------------------------------------------------
  [PASS]  Return code SUCCESS
  [PASS]  pid = 0xFFF (not yet bound)  (pid=0xfff)

--------------------------------------------------------------
  4. Configure PID Binding  (BIND)  [0x5706]
--------------------------------------------------------------
  [PASS]  Bind vcs0/vppb0 -> PID 0x100 succeeds
  [PASS]  Binding now shows PID = 0x100  (pid=0x100)
  [PASS]  HMAT latency entry = 5  (latency=5)
  [PASS]  HMAT bw entry = 10  (bw=10)

--------------------------------------------------------------
  5. Set DRT  [0x5709]
--------------------------------------------------------------
  [PASS]  DRT[0][0x100] -> Physical Port 2
  [PASS]  DRT[0][0x200] -> Physical Port 3
  [PASS]  RESERVED entry type -> INVALID_INPUT  (rc=INVALID_INPUT)
  [PASS]  Invalid DRT index -> INVALID_INPUT  (rc=INVALID_INPUT)

--------------------------------------------------------------
  6. Get DRT  [0x5708]
--------------------------------------------------------------
  [PASS]  Return code SUCCESS
  [PASS]  1 entry returned  (count=1)
  [PASS]  entry type = PHYSICAL_PORT  (type=PHYSICAL_PORT)
  [PASS]  routing_target = 2  (target=2)
  [PASS]  2 entries returned for num_entries=2  (count=2)
  [PASS]  Entry[0x100] = PHYSICAL_PORT/2
  [PASS]  Entry[0x101] = INVALID (unset)  (type=INVALID)
  [PASS]  Invalid DRT index -> INVALID_INPUT

--------------------------------------------------------------
  B. Configure PID Assignment  (CLEAR)  [0x5704]
--------------------------------------------------------------
  [PASS]  Clear PID 0x100 succeeds
  [PASS]  Re-assign cleared PID to new target -> SUCCESS

==============================================================
  RESULT : ALL 27 PASSED / 27 total checks
==============================================================
```

> **Note**: Lines like `[PbrSwitchManager] set_drt: drt_index 99 out of range`
> printed to the console are **expected** — they are the switch manager's error
> logs for the intentional invalid-input test cases. The `[PASS]` lines confirm
> those errors were correctly returned as `INVALID_INPUT`.

---

### 10.2 pytest Unit + Integration Tests (no running switch needed)

```cmd
# All 47 PBR tests — verbose
py -m pytest tests/test_pbr_data_plane.py tests/test_pbr_switch_command_set.py -v

# Quick (no verbose)
py -m pytest tests/test_pbr_data_plane.py tests/test_pbr_switch_command_set.py -q
```

Expected output:
```
tests/test_pbr_data_plane.py::test_pbr_data_plane_routing          PASSED
tests/test_pbr_data_plane.py::test_pbr_end_to_end_address_routing  PASSED
tests/test_pbr_switch_command_set.py::... (45 tests)               PASSED
======================= 47 passed in 0.50s ============================
```


### 10.3 All 6 Commands via CLI (live switch over MCTP)

**Step 1** — Start the switch in PBR mode (edit your env config or use Python directly):

```python
# run_pbr_switch.py
import asyncio
from opencis.apps.cxl_switch import CxlSwitch, CxlSwitchConfig
from opencis.cxl.component.physical_port_manager import PortConfig, PORT_TYPE

async def main():
    config = CxlSwitchConfig(
        port_configs=[
            PortConfig(PORT_TYPE.USP),
            PortConfig(PORT_TYPE.DSP),
            PortConfig(PORT_TYPE.DSP),
        ],
        mctp_host="0.0.0.0",
        mctp_port=8100,
        enable_pbr=True,     # ← enables PBR command registration
    )
    switch = CxlSwitch(config, device_configs=[])
    await switch.run()

asyncio.run(main())
```

```bash
# Terminal 1 — start switch
py run_pbr_switch.py
```

**Step 2** — In a second terminal, run the smoke-test:

```bash
# Terminal 2 — run all 6 PBR commands
py pbr_cli_test.py --mctp-host 127.0.0.1 --mctp-port 8100
```

**Expected output:**
```
PBR FM CCI Command Smoke-Test
Connecting to MCTP endpoint at 127.0.0.1:8100 …
Connected.

────────────────────────────────────────────────────────────
1. Identify PBR Switch  [5700h]
  ✓ PASS  GAE Support Map : 0x0000000000000000
  ✓ PASS  Num DRTs        : 1
  ✓ PASS  Num RGTs        : 0
  ✓ PASS  Routing Caps    : 0x00

────────────────────────────────────────────────────────────
2. Configure PID Assignment — ASSIGN  [5704h]
  ✓ PASS  PID 0x123 → target_id=2 assigned successfully

────────────────────────────────────────────────────────────
3. Get PID Binding  [5705h]
  ✓ PASS  PID         : 0x123
  ✓ PASS  Bound PID   : 0xfff
  ✓ PASS  HMAT index  : 0

────────────────────────────────────────────────────────────
4. Configure PID Binding  [5706h]
  ✓ PASS  PID 0x123 bound to target PID 0x456

────────────────────────────────────────────────────────────
5. Set DRT  [5709h]
  ✓ PASS  DRT[0][0x123] → Physical Port 2 programmed

────────────────────────────────────────────────────────────
6. Get DRT  [5708h]
  ✓ PASS  DRT Index   : 0
  ✓ PASS  Start Entry : 0x123
  ✓ PASS  Entry[0x123] type=PHYSICAL_PORT  target=2

────────────────────────────────────────────────────────────
Results: 6 passed, 0 failed
────────────────────────────────────────────────────────────
```

### 10.3 Via Socket.IO (FM CLI with QEMU host)

Using any Socket.IO client (e.g. `socket.io-client` in Node.js, or the `python-socketio` library):

```python
import socketio
sio = socketio.SimpleClient()
sio.connect("http://localhost:8200")

# Identify
result = sio.call("pbr:identify")
print(result)

# Assign PID 0x123 to port 2
result = sio.call("pbr:configurePid", {
    "operation": 0,
    "entries": [{"pid": 0x123, "targetId": 2, "instanceId": 0}]
})

# Program DRT
result = sio.call("pbr:setDrt", {
    "drtIndex": 0,
    "startEntry": 0x123,
    "entries": [{"entryType": "PHYSICAL_PORT", "routingTarget": 2}]
})
```

---

## 11. Design Decisions

| Decision | Rationale |
|----------|-----------|
| Pure-Python `packet_structs.py` fallback | No MSVC available; Cython `.pyd` auto-takes-precedence when compiled |
| `_inner_packet` stash on `PbrBasePacket` | Zero-copy decapsulation — avoids re-parsing when the packet was just constructed |
| `enable_pbr=False` default on `CxlSwitchConfig` | Backward-compatible — existing VSM topologies unchanged |
| PBR commands registered in `_initialize_mctp_endpoint()` | Follows exact same pattern as VCS, MLD commands — no new abstractions |
| `PbrHdmDecoderManager` separate from `PbrSwitchManager` | Separation of concerns: HDM decoder is data-plane (address→DPID), switch manager is control-plane (CCI state) |
| `ConfigurePidBindingCommand` as `CciBackgroundCommand` | CXL spec §7.7.13.7 mandates background operation — binding requires link-state transitions |
| No changes to `MctpCciExecutor` dispatch loop | Opcode dispatch is fully generic; new opcodes handled automatically via `register_cci_commands()` |

---

## 12. Why Each File Was Changed — Per-File Design Rationale

### 12.1 Transport Layer

#### `packet_constants.py` — MODIFIED
**Why**: The CXL spec defines `SYSTEM_PAYLOAD_TYPE` as a field in `SystemHeader`
that identifies each TLP's payload type. PBR introduces type value `5` for
packets carrying a PBR TLP Header (PTH). Without registering this constant, the
router cannot distinguish a PBR-wrapped packet from CXL-IO or CXL.mem at runtime.

**Alternative rejected**: Reuse an existing type with a flag byte. Rejected —
the spec explicitly reserves value `5` for PBR; deviating breaks interop with hardware.

---

#### `fields.py` — MODIFIED
**Why**: `fields.py` is the single source of truth for all CXL packet header field
layouts. The PBR TLP Header (CXL 4.0 §7.6.1) has two 12-bit fields (SPID, DPID)
packed into 4 bytes. Adding `PbrHeader` here ensures both the Cython generator and
the pure-Python fallback generator produce correct bit-field accessors.

**Alternative rejected**: Hard-code bit manipulation in `pbr_packets.py`. Rejected —
all other headers use the declarative field list; deviating creates a maintenance
inconsistency and breaks the generator pipeline.

---

#### `packets.py` — MODIFIED
**Why**: Every CXL packet type is assembled as a `BasePacket` subclass or composite
in `packets.py`. The `PbrBasePacket` must be registered here so the packet
infrastructure (size calculation, buffer allocation, field accessor generation)
works consistently with all other packet types.

**Alternative rejected**: Define `PbrBasePacket` entirely in `pbr_packets.py`.
Rejected — the generated accessor classes produced by the generator reference
`packets.py` layouts; keeping the definition here preserves the generator pipeline contract.

---

#### `mixin.py` — MODIFIED
**Why**: `PbrSwitchRouter` must quickly classify every incoming packet as PBR or HBR
at the top of its routing loop. Without a method on the packet itself, the router
would scatter raw `system_header.payload_type` field checks throughout its logic.

**What added**: `is_pbr()` on `BasePacketMixin`:
```python
def is_pbr(self) -> bool:
    return self.system_header.payload_type == SYSTEM_PAYLOAD_TYPE.PBR
```

**Alternative rejected**: Inline the check in the router. Rejected — `is_pbr()` is
semantically a packet property, consistent with `is_cxl_io()`, `is_mem()` that already exist.

---

#### `generate_py_fallback.py` — NEW
**Why**: The packet field accessor classes are normally produced by compiling
`packet_structs.pyx` with Cython, which requires MSVC on Windows. The development
environment lacks MSVC. Without a fallback, the entire packet layer is broken.

**Critical fix needed**: Field bit-offsets must account for the struct's byte offset
within the shared parent buffer: `self._p * 8 + field_bit_start`. Without this,
all field reads/writes in composite packets are corrupted.

**Key design choice**: Generated file is a static artifact (not generated at import
time) — startup cost is zero and the file can be inspected. Python's import system
auto-prefers the `.pyd`/`.so` Cython extension when compiled, so no runtime
branching is needed.

---

#### `pbr_packets.py` — NEW
**Why**: A clean user-facing API was needed for two operations:
1. `PbrBasePacket.create(spid, dpid)` — allocate a fresh PBR header packet
2. `PbrBasePacket.encapsulate(spid, dpid, inner_packet)` — wrap an existing HBR
   packet in a PBR header for ingress routing

**Key design choice**: `encapsulate()` stores a reference to the original inner
packet as `_inner_packet`. This enables **zero-copy decapsulation** at egress —
the router retrieves `pbr_pkt._inner_packet` directly instead of re-parsing bytes.

---

### 12.2 Control Plane

#### `hdm_decoder.py` — MODIFIED
**Why**: At ingress, `PbrSwitchRouter` must translate the destination Host Physical
Address (HPA) of an HBR TLP into a DPID to look up the correct DRT entry. The
existing `HdmDecoder` handles HPA→CXL memory decoding for HBR; PBR needs an
analogous component for address-to-DPID resolution.

Added to the **existing file** (not a new file) because `PbrHdmDecoder` and
`PbrHdmDecoderManager` are logically part of the HDM decoder family.

**Alternative rejected**: Embed address lookup inside `PbrSwitchManager`. Rejected —
HDM decoder is a data-plane concept (address translation); `PbrSwitchManager` is a
control-plane concept (CCI state). Mixing them violates separation of concerns.

---

#### `pbr_switch_manager.py` — NEW
**Why**: A central, injectable state store was needed for all PBR control-plane data:
PID assignments, DRT tables, and PID bindings. This follows the exact same pattern as
`VirtualSwitchManager` and `PhysicalPortManager` — a plain Python class injected into
each CCI command handler, making each command independently testable.

**Key design choices**:
- **Stateless across restarts**: No persistence. The FM re-programs all state on
  reconnect (standard CXL FM model).
- **`PidTarget` list constructor-injected**: The manager doesn't auto-discover ports;
  the topology owner provides the target list, making the manager unit-testable without
  a running switch.
- **DRT initialized all-INVALID**: Packets to unrouted DPIDs are dropped, not silently
  misrouted to port 0.

---

#### `pbr_switch_router.py` — NEW
**Why**: The data plane engine (classify → encapsulate → route → decapsulate) does not
fit inside any existing component. `VirtualSwitch` handles HBR routing via vPPB
bindings; PBR routing is DRT-based and needs its own async task loop.

**Key design choices**:
- Inherits `RunnableComponent` for consistent lifecycle management
- One `asyncio.Task` per physical port watching for incoming packets
- Calls `PbrHdmDecoderManager.lookup_dpid()` for HBR→PBR address classification
- Zero-copy path via `_inner_packet` stash on decapsulation

---

### 12.3 CCI Command Layer

#### `opencis/cxl/cci/common.py` — MODIFIED
**Why**: `CCI_FM_API_COMMAND_OPCODE` is the registry of all CXL FM API command opcodes.
Without adding the 6 PBR opcodes, the `MctpCciExecutor` dispatch loop logs "Unknown
Command" for every PBR packet — making debugging impossible. The range check in
`get_opcode_string()` was also extended to cover through `SET_DRT (0x5709)`.

---

#### Six CCI command files — NEW
**Why one file per command**: Follows the existing pattern established by `bind_vppb.py`,
`get_physical_port_state.py` etc.:
1. Keeps PRs reviewable — each file is ~100–165 lines
2. Matches spec structure — one section per command in §7.7.13
3. Enables independent unit testing per command

**Why `ConfigurePidBindingCommand` is `CciBackgroundCommand`** (not foreground):
CXL spec §7.7.13.7 explicitly mandates this — binding requires Hot Reset → Detect → L0
link-state transitions that cannot complete synchronously within a single CCI request.

Each file contains a request payload dataclass with `dump()`/`parse()`, a response
payload dataclass where applicable, the command class, and static `create_cci_request()`
/ `parse_response_payload()` helpers for the client side.

---

### 12.4 FM Integration Layer

#### `mctp_cci_api_client.py` — MODIFIED
**Why**: `MctpCciApiClient` is the FM-side client that sends CCI commands over MCTP TCP
and awaits responses. Every command the FM can issue needs a corresponding typed async
method — this is the contract between the FM application layer and the transport layer.

Added 6 async methods following the **identical pattern** of existing methods
(`bind_vppb()`, `get_virtual_cxl_switch_info()` etc.).

**Alternative rejected**: A single generic `send_pbr_command(opcode, data)` method.
Rejected — typed methods provide IDE autocomplete, type-checker support, and
self-documenting code.

---

#### `socketio_server.py` — MODIFIED
**Why**: The FM CLI communicates with opencis-core exclusively through Socket.IO events.
Without adding the 6 `pbr:*` events, there is no way for a QEMU host or external FM
tool to invoke any PBR command, even if the switch supports them over MCTP.

**What added**:
- 6 new event registrations (`pbr:identify`, `pbr:configurePid`, `pbr:getPidBinding`,
  `pbr:configurePidBinding`, `pbr:getDrt`, `pbr:setDrt`)
- 6 handler methods: translate incoming JSON dict → typed payload → `MctpCciApiClient`
  method → serialize response back to JSON
- 6 dispatch branches in `_handle_event()`

**Key design choice**: JSON field names use camelCase (`drtIndex`, `entryType`) to
match JavaScript/Socket.IO client conventions. Python dataclasses use snake_case
internally. The handler methods perform this translation at the boundary.

---

#### `cxl_switch.py` — MODIFIED
**Why**: `CxlSwitch` is the top-level application class that wires all components
together. To make PBR commands reachable over MCTP, the 6 `CciCommand` instances must
be registered with `MctpCciExecutor` via `register_cci_commands()`. Without this step,
the executor returns "Unsupported" for all PBR opcodes regardless of what was implemented.

**Key design choice**: `enable_pbr: bool = False` opt-in flag — all existing VSM-based
topology configs continue to work unchanged. Switches without PBR hardware return
"Unsupported" for PBR opcodes, not silently accept them.

**Alternative rejected**: Always register PBR commands. Rejected — capabilities should
be opt-in; blind registration could cause unexpected behavior on HBR-only switches.
