# FM External MCTP CCI Port — In-Depth Design Document

**Component:** `FmMctpCciServer`
**Port:** 8300 (default, configurable)
**Branch:** `v0.5-dev`
**Author:** CXL Architect
**Status:** Implemented & Tested

---

## 1. Overview

### 1.1 Problem Statement

The CXL Fabric Manager (FM) in `opencis-core` exposes two control interfaces:

| Port | Protocol | Client | Purpose |
|------|----------|--------|---------|
| 8100 | Raw MCTP/TCP | CXL Switch | Switch ↔ FM internal CCI path |
| 8200 | Socket.IO/HTTP | `pbr_fm_cli.py` | Human operator CLI |

Neither of these ports accepts **raw MCTP packets from an arbitrary external client**.
Machine-to-machine MCTP communication (hardware MCTP controllers, remote FMs, test
harnesses, BMC/FPGA-based tools) has no entry point into the FM.

### 1.2 Solution

A new dedicated TCP port (`8300`) on the FM that:

1. **Accepts** raw MCTP-over-TCP connections from any client
2. **Depacketizes** the MCTP envelope to extract the CCI command
3. **Executes** the CCI command against the FM's authoritative state
4. **Repacketizes** the response into MCTP format
5. **Sends** it back over the same TCP connection

The implementation **reuses 100% of existing infrastructure** — no new packet formats,
no new framing, no new wire protocols.

---

## 2. Architecture

### 2.1 High-Level Block Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                      CxlFabricManager                               │
│                                                                     │
│  ┌──────────────────┐  ┌─────────────────┐  ┌──────────────────┐   │
│  │ MctpConnection   │  │ FabricManager   │  │ FmMctpCciServer  │   │
│  │ Manager          │  │ SocketIoServer  │  │ (NEW — port 8300)│   │
│  │ (port 8100)      │  │ (port 8200)     │  │                  │   │
│  │                  │  │                 │  │ ServerComponent  │   │
│  │ Switch ↔ FM CCI  │  │ CLI/WebSocket   │  │ CciExecutor      │   │
│  │ internal path    │  │ human operator  │  │ PbrSwitchManager │   │
│  └──────────────────┘  └─────────────────┘  └──────────────────┘   │
│                                                                     │
│  ┌──────────────────┐                                               │
│  │ ShortMsgConn     │                                               │
│  │ (port 8700)      │                                               │
│  │ Host notifications│                                              │
│  └──────────────────┘                                               │
└─────────────────────────────────────────────────────────────────────┘

External clients:
  CXL Switch ────────────────────────────────────── port 8100
  pbr_fm_cli / browser ──────────────────────────── port 8200
  Host root complex ─────────────────────────────── port 8700
  BMC / FPGA / remote FM / test tool ────────────── port 8300 (NEW)
```

### 2.2 FmMctpCciServer Internal Architecture

```
┌──────────────────────────────────────────────────────────┐
│                   FmMctpCciServer                        │
│                                                          │
│  ┌────────────────────────────────────────────────────┐  │
│  │                ServerComponent                     │  │
│  │         asyncio.start_server (port 8300)           │  │
│  │    spawns _handle_client() per connection           │  │
│  └──────────────────┬─────────────────────────────────┘  │
│                     │ per TCP connection                  │
│                     ▼                                     │
│  ┌────────────────────────────────────────────────────┐  │
│  │              _handle_client()                      │  │
│  │                                                    │  │
│  │   MctpConnection (fresh per client)                │  │
│  │   ┌──────────────────────────────────────────┐     │  │
│  │   │  controller_to_ep  Queue  ◄── TCP bytes  │     │  │
│  │   │  ep_to_controller  Queue  ──► TCP bytes  │     │  │
│  │   └──────────────────────────────────────────┘     │  │
│  │                                                    │  │
│  │   MctpPacketProcessor (ENDPOINT mode)              │  │
│  │   ┌──────────────────────────────────────────┐     │  │
│  │   │  Incoming pump: TCP → controller_to_ep   │     │  │
│  │   │  Outgoing pump: ep_to_controller → TCP   │     │  │
│  │   └──────────────────────────────────────────┘     │  │
│  │                                                    │  │
│  │   _process_client() loop                           │  │
│  │   ┌──────────────────────────────────────────┐     │  │
│  │   │  get() from controller_to_ep             │     │  │
│  │   │  → get_cci_message()                     │     │  │
│  │   │  → CciRequest(opcode, payload)           │     │  │
│  │   │  → CciExecutor.execute_command()         │     │  │
│  │   │  → CciMessagePacket.create(RESPONSE)     │     │  │
│  │   │  → put() to ep_to_controller             │     │  │
│  │   └──────────────────────────────────────────┘     │  │
│  └────────────────────────────────────────────────────┘  │
│                                                          │
│  ┌────────────────────────────────────────────────────┐  │
│  │   CciExecutor (shared across all clients)          │  │
│  │                                                    │  │
│  │   Registered commands:                             │  │
│  │     0x5700 → IdentifyPbrSwitchCommand              │  │
│  │     0x5704 → ConfigurePidAssignmentCommand         │  │
│  │     0x5705 → GetPidBindingCommand                  │  │
│  │     0x5706 → ConfigurePidBindingCommand            │  │
│  │     0x5708 → GetDrtCommand                         │  │
│  │     0x5709 → SetDrtCommand                         │  │
│  └────────────────────────────────────────────────────┘  │
│                                                          │
│  ┌────────────────────────────────────────────────────┐  │
│  │   PbrSwitchManager (FM-side authoritative state)   │  │
│  │                                                    │  │
│  │   DRT tables: num_drts=2, 4096 entries each        │  │
│  │   RGT tables: num_rgts=1                           │  │
│  │   PID targets: 3 (FABRIC_PORT, HOST_EDGE,          │  │
│  │                    DOWNSTREAM_EDGE)                │  │
│  └────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────┘
```

### 2.3 Concurrency Model

```
Event loop (single asyncio loop per FM process)
│
├── ServerComponent task          → accepts TCP connections
│
├── CciExecutor task              → background command slot management
│
└── Per-client tasks (N clients simultaneously):
      ├── MctpPacketProcessor task
      │     ├── Incoming pump coroutine  (TCP → Queue)
      │     └── Outgoing pump coroutine  (Queue → TCP)
      └── _process_client() coroutine    (Queue → CCI → Queue)
```

**Thread safety**: Entirely single-threaded asyncio. The `CciExecutor` background
command slot is an asyncio-level mutex — only one background CCI command executes
at a time across all clients (CXL spec compliant).

---

## 3. Packet Flow — Wire Level

### 3.1 Request: Client → FM

```
TCP stream bytes (client sends):

Byte offset  Size    Field
──────────────────────────────────────────────────────────
0            2B      SystemHeader
                       [3:0]  payload_type = 4 (CCI_MCTP)
                       [15:4] payload_length = total packet size
2            2B      CciHeader
                       [7:0]  port_index = 0
                       [15:8] msg_class = 1 (REQ)
4            variable CciMessagePacket
               [15:0]  message_category = 0 (REQUEST)
               [31:16] command_opcode  (e.g., 0x5700)
               [39:32] message_tag     (client-chosen, echoed in response)
               [71:40] return_code = 0 (unused in request)
               [72]    background_operation = 0
               [92:73] vendor_specific_extended_status = 0
               [108:93] message_payload_length_high
               [124:109] message_payload_length_low
               [...]   payload bytes (opcode-specific)
```

### 3.2 Example: Identify PBR Switch (0x5700) Request

```
Hex bytes sent by client:
04 10 00 01 00 00 70 57 00 00 00 00 00 00 00 00
│──┤ │───────────────────────────────────────│
 SH   CciHeader + CciMessagePacket

SystemHeader:    04 10  (type=4 CCI_MCTP, length=16)
CciHeader:       00 01  (port=0, class=REQ)
CciMsgHeader:    00 00 70 57 00 00 00 00 00 00 00 00
  category:      00     (REQUEST)
  opcode:        5700   (IDENTIFY_PBR_SWITCH)
  tag:           00
  return_code:   0000
  payload_len:   0      (no input payload)
```

### 3.3 Example: Identify PBR Switch (0x5700) Response

```
Hex bytes sent by server:
1C 10 00 02 01 00 70 57 00 00 00 00 00 00 0C 00
02 00 03 00 01 00 00 00 00 00 00 00

SystemHeader:    1C 10  (type=4 CCI_MCTP, length=28)
CciHeader:       00 02  (port=0, class=RSP)
CciMsgHeader:
  category:      01     (RESPONSE)
  opcode:        5700
  tag:           00     (echoed from request)
  return_code:   0000   (SUCCESS)
  payload_len:   0C     (12 bytes)
Payload (IdentifyPbrSwitchResponsePayload, 12 bytes):
  num_drts:      02
  num_rgts:      00 00
  num_pid_targets: 03
  ...
```

---

## 4. Component Reuse Map

| Existing Component | File | Reuse in FmMctpCciServer |
|---|---|---|
| `ServerComponent` | `opencis/util/server.py` | TCP listener, multi-client accept |
| `MctpConnection` | `opencis/cxl/component/mctp/mctp_connection.py` | Queue pair per client |
| `MctpPacketProcessor` | `opencis/cxl/component/mctp/mctp_packet_processor.py` | Byte framing ↔ Queue |
| `MctpPacketReader` | `opencis/cxl/component/mctp/mctp_packet_reader.py` | Stream → packet (used inside processor) |
| `CciExecutor` | `opencis/cxl/component/cci_executor.py` | Command dispatch, background slot |
| `CciRequest` / `CciResponse` | `opencis/cxl/component/cci_executor.py` | Request/response value objects |
| `CciMessagePacket` | `opencis/cxl/transport/cci_packets.py` | Wire format encode/decode |
| `CciPayloadPacket` | `opencis/cxl/transport/cci_packets.py` | Outer MCTP envelope |
| `PbrSwitchManager` | `opencis/cxl/component/pbr_switch_manager.py` | FM-side routing state |
| All 6 PBR CCI commands | `opencis/cxl/cci/fabric_manager/pbr_switch/` | Business logic |
| `RunnableComponent` | `opencis/util/component.py` | Lifecycle (run/stop/wait_for_ready) |

**Zero new dependencies. Zero new packet formats.**

---

## 5. State Ownership — Architectural Decision

### 5.1 Decision: Standalone FM-side PbrSwitchManager

The FM port 8300 owns a **standalone `PbrSwitchManager`** instance that is
**separate** from the switch's internal `PbrSwitchManager`.

```
FM process
│
├── FmMctpCciServer (port 8300)
│     └── FM-side PbrSwitchManager   ← FM's authoritative view
│               DRT[0][0x042] = PHYSICAL_PORT → 1
│               DRT[0][0x043] = PHYSICAL_PORT → 2
│               PID[0x010] → target_id=0
│
└── MctpConnectionManager (port 8100)
      └── (connects to switch)

Switch process
│
└── MctpCciExecutor
      └── Switch-side PbrSwitchManager ← switch hardware state
              DRT[0][0x042] = UNINITIALIZED   ← may differ!
```

### 5.2 Why separate state?

| Reason | Explanation |
|---|---|
| **CXL spec** | The FM is the authoritative control plane; the switch is a slave |
| **Atomicity** | FM records intent before programming the switch; crash-safe |
| **Auditability** | FM can always answer "what did I program?" independently |
| **Real hardware** | Physical FM chips track their own routing tables separately |

### 5.3 Current Gap (Next Integration Step)

At present, commands on port 8300 update FM state only. To also program the
switch, add a `post_execute_hook` that calls `MctpCciApiClient` over port 8100.
See `docs/mctp_fm_cci_port_integration.md` for the detailed integration plan.

---

## 6. CCI Commands Supported

### 6.1 Identify PBR Switch (0x5700)

- **Input**: No payload
- **Output**: `num_drts`, `num_rgts`, `num_pid_targets`, capability flags
- **FM behaviour**: Returns FM's configured PBR topology

### 6.2 Configure PID Assignment (0x5704)

- **Input**: Operation (ASSIGN/DEASSIGN), list of `{pid, target_id, instance_id}`
- **Output**: SUCCESS or INVALID_INPUT
- **FM behaviour**: Assigns Physical ID → PID target in FM's PID table

### 6.3 Get PID Binding (0x5705)

- **Input**: `pid`, `count`
- **Output**: List of PID→target bindings
- **FM behaviour**: Reads FM's PID assignment table

### 6.4 Configure PID Binding (0x5706)

- **Input**: Binding entries `{pid, rgt_index, rgt_entry}`
- **Output**: SUCCESS or error
- **FM behaviour**: Sets PID→RGT bindings in FM's routing table

### 6.5 Get DRT (0x5708)

- **Input**: `drt_index`, `start_entry`, `num_entries`
- **Output**: Array of DRT entries `{entry_type, routing_target}`
- **FM behaviour**: Reads FM's Device Routing Table

### 6.6 Set DRT (0x5709)

- **Input**: `drt_index`, `start_entry`, list of `{entry_type, routing_target}`
- **Output**: SUCCESS, INVALID_INPUT (out of range), or INTERNAL_ERROR
- **FM behaviour**: Writes FM's Device Routing Table

---

## 7. Error Handling

| Scenario | Behaviour |
|---|---|
| Unknown opcode | `CciExecutor` returns `UNSUPPORTED` (0x0003); client gets proper MCTP response |
| Invalid payload | Command's `_execute()` returns `INVALID_INPUT` (0x0002) |
| Out-of-range DRT index | `PbrSwitchManager` returns `INVALID_INPUT` |
| Client disconnects mid-request | `MctpPacketReader` raises exception → `_stop_outgoing_processor()` → connection cleaned up |
| Exception in command execution | `CciExecutor` catches and returns `INTERNAL_ERROR` (0x0004) |
| Background command busy | `CciExecutor` serialises — second caller waits, not rejected |

---

## 8. Multi-Client Behaviour

```
Client A ──────────────────────────────────────────────► port 8300
  connection 1: MctpConnection_A + MctpPacketProcessor_A + _process_client_A

Client B ──────────────────────────────────────────────► port 8300
  connection 2: MctpConnection_B + MctpPacketProcessor_B + _process_client_B

Both hit the SAME CciExecutor and PbrSwitchManager.

Foreground commands (Identify, GetDRT, GetPidBinding):
  → Execute concurrently (no lock needed, read-only or atomic writes)

Background commands (if registered):
  → CciExecutor background slot serialises — one at a time, spec compliant
```

---

## 9. Port Assignment Reference

| Port | Protocol | Direction | Component | Status |
|------|----------|-----------|-----------|--------|
| 8000 | TCP/CXL | Devices → Switch | Switch device listener | Existing |
| 8100 | TCP/MCTP | Switch → FM | `MctpConnectionManager` | Existing |
| 8200 | HTTP/WebSocket/Socket.IO | CLI → FM | `FabricManagerSocketIoServer` | Existing |
| 8700 | TCP/ShortMsg | Host → FM | `ShortMsgConn` | Existing |
| **8300** | **TCP/MCTP** | **Any client → FM** | **`FmMctpCciServer`** | **NEW** |

---

## 10. Files Added / Modified

```
opencis-core/
├── opencis/
│   ├── apps/
│   │   └── fabric_manager.py              MODIFIED
│   │         + fm_mctp_cci_port=8300 param
│   │         + FM-side PbrSwitchManager instantiation
│   │         + FmMctpCciServer wired into run()/stop()
│   │
│   └── cxl/component/mctp/
│         └── fm_mctp_cci_server.py        NEW
│               FmMctpCciServer(RunnableComponent)
│                 _handle_client()
│                 _process_client()
│                 get_port()
│                 register_command()
│
└── tests/
      └── test_mctp_fm_port.py             NEW
            7 pytest-asyncio tests
            MctpCciTestClient (raw TCP test client)
            fm_server fixture (ephemeral port, real server)
```

---

## 11. Test Coverage

| Test | Opcode | Verifies |
|------|--------|---------|
| `test_identify_pbr_switch` | 0x5700 | SUCCESS + `num_drts >= 1` |
| `test_set_drt_programs_route` | 0x5709 | Write DRT entry, SUCCESS |
| `test_get_drt_after_set` | 0x5708 | Round-trip: write then read-back |
| `test_configure_pid_assignment` | 0x5704 | Assign PID → target, SUCCESS |
| `test_invalid_opcode_returns_unsupported` | 0xDEAD | Returns UNSUPPORTED |
| `test_multiple_commands_same_connection` | multiple | Persistent connection, tag routing |
| `test_set_drt_out_of_range_returns_invalid_input` | 0x5709 | Boundary violation → INVALID_INPUT |

**Result: 7/7 PASSED** (`pytest tests/test_mctp_fm_port.py -v`)

---

## 12. How to Add a New CCI Command to Port 8300

1. Implement `CciCommand` subclass in `opencis/cxl/cci/fabric_manager/`
2. Register it at FM startup in `fabric_manager.py`:
   ```python
   pbr_commands.append(YourNewCommand(self._fm_pbr_manager))
   ```
3. Or register dynamically via `FmMctpCciServer.register_command(cmd)` after construction
4. Write a test in `tests/test_mctp_fm_port.py` using `MctpCciTestClient`

No changes to the server infrastructure are needed.
