# MCTP FM CCI Port Design Document

---

| Field       | Value                              |
|-------------|------------------------------------|
| **Version** | 2.0                                |
| **Date**    | May 2026                           |
| **Release** | v0.5-dev                           |
| **Status**  | Implemented                        |
| **Author**  | OpenCIS Core Team                  |
| **File**    | `docs/mctp_fm_cci_port_design.md`  |

---

## Table of Contents

1. [Overview](#1-overview)
2. [Architecture](#2-architecture)
3. [Component Descriptions](#3-component-descriptions)
4. [Packet Flow — Wire Level](#4-packet-flow--wire-level)
5. [Depacketization Layers](#5-depacketization-layers)
6. [Data Plane vs Control Plane Separation](#6-data-plane-vs-control-plane-separation)
7. [CCI Commands Supported](#7-cci-commands-supported)
8. [Error Handling](#8-error-handling)
9. [Multi-Client Concurrency Model](#9-multi-client-concurrency-model)
10. [Port Assignment Reference](#10-port-assignment-reference)
11. [Files Added / Modified / Deleted](#11-files-added--modified--deleted)
12. [Test Coverage](#12-test-coverage)
13. [How to Use Port 8300](#13-how-to-use-port-8300)
14. [Design Decisions](#14-design-decisions)

---

## 1. Overview

### 1.1 Problem Statement

The OpenCIS Fabric Manager (FM) must expose an **MCTP-over-TCP endpoint** so that external MCTP
clients (e.g., hardware BMCs, test tools, or other subsystems) can issue CXL Component Command
Interface (CCI) commands to PBR (Pooled Buffer/Resource) switches managed by the FM.

Prior to v2.0, an experimental implementation attempted to embed a full `PbrSwitchManager` and
`PbrCommandService` directly inside the MCTP server. This caused:

- **Duplicated switch-programming logic** — two independent code paths that could diverge.
- **State synchronization bugs** — the MCTP path had its own view of switch state, separate from
  the authoritative `MctpCciApiClient`-based FM CLI path.
- **Maintenance burden** — any change to CCI command handling needed to be applied in two places.
- **Test complexity** — integration tests had to set up an entire parallel switch stack.

### 1.2 Solution: Pure Adapter

Version 2.0 replaces the embedded logic with a **Pure Adapter** pattern:

```
External MCTP Client  ──TCP──►  FmMctpCciServer (port 8300)
                                        │
                            depacketize (2 layers)
                                        │
                                        ▼
                            MctpCciApiClient.send_raw_cci()
                                        │
                            (shared FM CLI path, same instance
                             used by SocketIO server port 8200)
                                        │
                                        ▼
                              Switch (via port 8100)
```

**Port 8300 contains ZERO local state and ZERO CCI logic.** It is a transparent translator between
the MCTP wire format and the internal `MctpCciApiClient` API.

### 1.3 Key Principle

> **Single Source of Truth:** All CCI command logic lives in `MctpCciApiClient` (and the switch
> itself). Port 8300 merely adapts the wire format. Any client — whether SocketIO (port 8200) or
> MCTP (port 8300) — reaches the switch through the same code path.

---

## 2. Architecture

### 2.1 System-Level Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          OpenCIS Fabric Manager Process                      │
│                                                                              │
│  ┌──────────────────────┐      ┌──────────────────────────────────────────┐ │
│  │  CxlFabricManager    │      │         MctpConnectionManager            │ │
│  │  (fabric_manager.py) │      │              (Port 8100)                 │ │
│  │                      │      │  Switch connects here over TCP/MCTP      │ │
│  │  self._api_client ──────────►  (MctpCciApiClient internal use)         │ │
│  │  (MctpCciApiClient)  │      └──────────────────────────────────────────┘ │
│  │          │           │                        ▲                          │
│  │          │           │                        │ MCTP over TCP            │
│  │          ▼           │                        │                          │
│  │  ┌───────────────┐   │             ┌──────────┴──────────┐               │
│  │  │  SocketIO     │   │             │   PBR Switch / CXL  │               │
│  │  │  Server       │   │             │   Component         │               │
│  │  │  (Port 8200)  │   │             └─────────────────────┘               │
│  │  │  FM CLI path  │   │                                                   │
│  │  └───────────────┘   │                                                   │
│  │          │           │                                                   │
│  │          │  shared   │                                                   │
│  │          │  instance │                                                   │
│  │          ▼           │                                                   │
│  │  ┌───────────────┐   │                                                   │
│  │  │FmMctpCciServer│   │                                                   │
│  │  │  (Port 8300)  │   │                                                   │
│  │  │  Pure Adapter │   │                                                   │
│  │  └───────────────┘   │                                                   │
│  └──────────────────────┘                                                   │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
         ▲                          ▲
         │ SocketIO / HTTP          │ MCTP over TCP
         │                          │
  ┌──────┴──────┐          ┌────────┴────────┐
  │  FM CLI     │          │  External MCTP  │
  │  (curl,     │          │  Client (BMC,   │
  │   scripts)  │          │   test tool)    │
  └─────────────┘          └─────────────────┘
```

### 2.2 Shared FM CLI Path

The critical insight is that `MctpCciApiClient` is **one shared instance** instantiated in
`CxlFabricManager.__init__()`. It is passed both to:

- `FabricManagerSocketIoServer` (port 8200) — used by CLI clients (curl, scripts, etc.)
- `FmMctpCciServer` (port 8300) — used by external MCTP clients (BMCs, hardware)

This is the "shared FM CLI path." Any request from either port 8200 or port 8300 flows through
`MctpCciApiClient` and ultimately reaches the switch via port 8100 (MCTP connection).

```
fabric_manager.py (CxlFabricManager.__init__):

    self._api_client = MctpCciApiClient(...)   # ONE instance

    self._socketio_server = FabricManagerSocketIoServer(
        api_client=self._api_client,           # shared
        port=8200
    )

    self._mctp_cci_server = FmMctpCciServer(
        host="0.0.0.0",
        port=8300,
        mctp_client=self._api_client           # same shared instance
    )
```

### 2.3 Component Interaction

```
External MCTP Client
        │
        │  TCP connection to port 8300
        │  Wire: CciPayloadPacket (TCP framed)
        ▼
┌───────────────────────────────────────────┐
│           FmMctpCciServer                 │
│                                           │
│  asyncio.start_server (ServerComponent)  │
│           │                               │
│           ▼                               │
│  _handle_client(reader, writer)           │
│           │                               │
│           ├──► MctpPacketProcessor        │
│           │    (TCP bytes → Queue)        │  Layer 1
│           │                               │
│           └──► _process_client()          │
│                (Queue → CciPayloadPacket) │
│                │                          │
│                │  raw.get_cci_message()   │  Layer 2
│                ▼                          │
│           _forward_to_cli()               │
│                │                          │
└────────────────┼──────────────────────────┘
                 │
                 │  MctpCciApiClient.send_raw_cci(
                 │      opcode, payload, port_index)
                 ▼
        MctpCciApiClient
                 │
                 │  (same path as SocketIO / port 8200)
                 ▼
           Switch (port 8100)
```

---

## 3. Component Descriptions

### 3.1 FmMctpCciServer

**File:** `opencis/cxl/component/mctp/fm_mctp_cci_server.py`

This is the main class implementing the pure adapter. It listens on TCP port 8300, accepts MCTP
CCI connections from external clients, depacketizes incoming MCTP packets, and forwards them to
`MctpCciApiClient.send_raw_cci()`.

#### Constructor

```python
def __init__(
    self,
    host: str,
    port: int,
    mctp_client: Optional[MctpCciApiClient] = None,
):
```

| Parameter     | Type                          | Description                                        |
|---------------|-------------------------------|----------------------------------------------------|
| `host`        | `str`                         | Bind address (e.g., `"0.0.0.0"` or `"127.0.0.1"`) |
| `port`        | `int`                         | TCP port to listen on (default: 8300)              |
| `mctp_client` | `Optional[MctpCciApiClient]`  | Shared API client; `None` = offline/test mode      |

**Offline mode:** When `mctp_client=None`, the server still starts and accepts connections, but
every CCI command receives a `CCI_RETURN_CODE.UNSUPPORTED` response. This enables testing the
MCTP framing pipeline without a live switch.

#### Methods

| Method               | Signature                                        | Description                                                      |
|----------------------|--------------------------------------------------|------------------------------------------------------------------|
| `bind_mctp_client`   | `(client: MctpCciApiClient) -> None`             | Late-inject the API client after switch connects asynchronously  |
| `get_port`           | `() -> int`                                      | Returns the TCP port this server is bound to                     |
| `_handle_client`     | `(reader, writer) -> None`                       | Called by asyncio for each new TCP connection; spawns tasks      |
| `_process_client`    | `(conn: MctpConnection) -> None`                 | Reads from queue, depacketizes Layer 2, calls `_forward_to_cli` |
| `_forward_to_cli`    | `(raw: CciPayloadPacket, writer) -> None`        | Calls `send_raw_cci()`, builds response packet, writes to TCP    |
| `_run`               | `() -> None`                                     | Starts the asyncio TCP server (called by `RunnableComponent`)    |
| `_stop`              | `() -> None`                                     | Gracefully stops the server and all active connections           |

#### Offline Mode Behavior

```python
# mctp_client=None → UNSUPPORTED for every command
server = FmMctpCciServer(host="127.0.0.1", port=8300, mctp_client=None)
# Any CCI command sent to port 8300 gets:
#   return_code = CCI_RETURN_CODE.UNSUPPORTED
#   response_bytes = b""
#   is_background = False
```

#### Late Binding

```python
# After the switch connects to port 8100:
await mctp_connection_manager.wait_for_switch()
server.bind_mctp_client(api_client)
# From this point, commands are forwarded to the switch
```

---

### 3.2 MctpCciApiClient.send_raw_cci()

**File:** `opencis/cxl/component/mctp/mctp_cci_api_client.py`

This method was added in v2.0 specifically to support the pure adapter pattern. It accepts raw
opcode and payload bytes (already extracted from the MCTP packet by `_process_client()`), forwards
them to the switch, and returns raw response bytes.

#### Signature

```python
async def send_raw_cci(
    self,
    opcode: int,
    payload: bytes,
    port_index: int = 0,
) -> Tuple[CCI_RETURN_CODE, bytes, bool]:
```

#### Parameters

| Parameter    | Type                | Description                                                     |
|--------------|---------------------|-----------------------------------------------------------------|
| `opcode`     | `int`               | CCI command opcode (e.g., `0x5700` for IDENTIFY_PBR_SWITCH)    |
| `payload`    | `bytes`             | Raw request payload bytes (extracted from CciMessagePacket)     |
| `port_index` | `int`               | Switch port index (default: 0)                                  |

#### Return Value

Returns a 3-tuple `(CCI_RETURN_CODE, bytes, bool)`:

| Element          | Type              | Description                                                 |
|------------------|-------------------|-------------------------------------------------------------|
| `return_code`    | `CCI_RETURN_CODE` | Switch's CCI return code (SUCCESS, UNSUPPORTED, etc.)       |
| `response_bytes` | `bytes`           | Raw response payload bytes from the switch                  |
| `is_background`  | `bool`            | `True` if the command was accepted as a background command  |

#### Why Raw Bytes?

`send_raw_cci()` deliberately avoids parsing or constructing typed struct objects. The adapter
passes `payload` bytes as received from the wire (after MCTP depacketization). This means:

- Zero struct parsing overhead in the adapter
- No risk of deserialization bugs introducing subtle field mutations
- Bytes forwarded verbatim — what the external client sent is exactly what the switch sees

---

### 3.3 MctpPacketProcessor

**File:** `opencis/cxl/component/mctp/mctp_packet_processor.py`

Handles the **Layer 1** of depacketization: TCP byte-stream framing.

#### Responsibilities

- Reads raw bytes from `asyncio.StreamReader`
- Assembles complete `CciPayloadPacket` frames (handles partial reads / TCP fragmentation)
- Places assembled packets into an `asyncio.Queue`
- Runs as a background asyncio task

#### Operation

```
TCP StreamReader
      │
      │  raw bytes (possibly fragmented)
      ▼
MctpPacketProcessor
      │
      │  assembles CciPayloadPacket (fixed header + variable payload)
      │  handles partial reads, retries until complete packet received
      ▼
asyncio.Queue[CciPayloadPacket]
      │
      ▼
_process_client() (Layer 2)
```

#### Framing Protocol

The TCP framing uses a length-prefixed format embedded in the `CciPayloadPacket` header. The
processor reads the fixed-size header first, extracts the payload length, then reads exactly that
many additional bytes to complete the packet.

---

### 3.4 MctpConnection

**File:** `opencis/cxl/component/mctp/mctp_connection.py`

Represents a logical MCTP connection between two parties, backed by a pair of asyncio Queues.

#### Structure

```python
@dataclass
class MctpConnection:
    controller_to_ep: asyncio.Queue  # commands: controller → endpoint
    ep_to_controller: asyncio.Queue  # responses: endpoint → controller
```

#### Usage in FmMctpCciServer

```
External Client → TCP → MctpPacketProcessor → controller_to_ep Queue
                                                        │
                                              _process_client() reads
                                                        │
                                              _forward_to_cli() sends to switch
                                                        │
                                              ep_to_controller Queue (responses)
                                                        │
                                              Written back to TCP → External Client
```

The two-queue model provides clean separation between the incoming command path and outgoing
response path, and allows `_process_client()` and the TCP writer to operate independently.

---

### 3.5 ServerComponent

**File:** `opencis/cxl/component/mctp/server_component.py` (or integrated into base class)

Manages the lifecycle of the `asyncio.start_server()` call:

- `_run()`: calls `asyncio.start_server(self._handle_client, host, port)`, stores the server
  object, logs the bound address, signals ready.
- `_stop()`: calls `server.close()`, awaits `server.wait_closed()`, cancels all active connection
  tasks.

`FmMctpCciServer` extends `RunnableComponent` which provides the `run()` / `stop()` interface used
by `CxlFabricManager` to start/stop all server components in parallel.

---

## 4. Packet Flow — Wire Level

### 4.1 Request Wire Format

An external MCTP client sends a `CciPayloadPacket` wrapping a `CciMessagePacket`:

```
┌──────────────────────────────────────────────────────────┐
│                    TCP Stream                            │
│                                                          │
│  ┌────────────────────────────────────────────────────┐  │
│  │              CciPayloadPacket                      │  │
│  │                                                    │  │
│  │  ┌──────────────────────┐  ┌─────────────────────┐ │  │
│  │  │  MCTP Transport Hdr  │  │   CciMessagePacket  │ │  │
│  │  │  (message_type,      │  │                     │ │  │
│  │  │   message_tag,       │  │  ┌───────────────┐  │ │  │
│  │  │   category,          │  │  │  CCI Header   │  │ │  │
│  │  │   tag_owner, ...)    │  │  │  (opcode,     │  │ │  │
│  │  └──────────────────────┘  │  │   length,     │  │ │  │
│  │                            │  │   message_tag,│  │ │  │
│  │                            │  │   bg_op, ...)  │  │ │  │
│  │                            │  ├───────────────┤  │ │  │
│  │                            │  │  CCI Payload  │  │ │  │
│  │                            │  │  (opcode-     │  │ │  │
│  │                            │  │   specific    │  │ │  │
│  │                            │  │   bytes)      │  │ │  │
│  │                            │  └───────────────┘  │ │  │
│  │                            └─────────────────────┘ │  │
│  └────────────────────────────────────────────────────┘  │
│                                                          │
│  (Next packet follows immediately — no delimiter)        │
└──────────────────────────────────────────────────────────┘
```

### 4.2 Response Wire Format

The response packet **must echo** key fields from the request:

```
Response CciPayloadPacket:
  - message_tag     = same as request (echoed)
  - command_opcode  = same as request (echoed)
  - return_code     = switch's CCI_RETURN_CODE
  - payload         = switch's raw response bytes
  - category        = CCI_MCTP_MESSAGE_CATEGORY.RESPONSE
  - tag_owner       = 0 (response clears tag ownership)
```

### 4.3 Example Hex — IDENTIFY_PBR_SWITCH Request

```
Opcode: 0x5700 (IDENTIFY_PBR_SWITCH)
Payload: (empty for identify)

Wire bytes (CciPayloadPacket):
  Offset  Bytes   Description
  ──────  ──────  ──────────────────────────────────
  0x00    1       message_type = 0x7e (MCTP CCI)
  0x01    1       integrity_check | message_tag (bits)
  0x02    1       flags (tag_owner=1, SOM=1, EOM=1)
  0x03    1       reserved
  0x04    2       command_opcode = 0x00 0x57  (LE: 0x5700)
  0x06    2       message_length = 0x08 0x00  (8 bytes CCI header)
  0x08    1       message_tag (CCI header tag, echoed in response)
  0x09    1       background_operation = 0x00
  0x0a    2       return_code = 0x00 0x00  (N/A in request)
  0x0c    2       vendor_specific_extended_status = 0x00 0x00
  0x0e    2       (padding / reserved)
  ──────  ──────  ──────────────────────────────────
  Total:  16 bytes (header only, no payload for identify)
```

### 4.4 Example Hex — IDENTIFY_PBR_SWITCH Response

```
Response wire bytes:
  Offset  Bytes   Description
  ──────  ──────  ──────────────────────────────────
  0x00    1       message_type = 0x7e (MCTP CCI)
  0x01    1       message_tag (echoed from request)
  0x02    1       flags (tag_owner=0, SOM=1, EOM=1, category=RESPONSE)
  0x03    1       reserved
  0x04    2       command_opcode = 0x00 0x57  (echoed)
  0x06    2       message_length = total CCI payload length
  0x08    1       message_tag (echoed)
  0x09    1       background_operation = 0x00
  0x0a    2       return_code = 0x00 0x00  (SUCCESS)
  0x0c    2       vendor_specific_extended_status = 0x00 0x00
  0x0e    ...     Switch response payload (identify info bytes)
  ──────  ──────  ──────────────────────────────────
```

---

## 5. Depacketization Layers

Port 8300 performs a **two-layer depacketization** to extract the raw CCI opcode and payload:

```
┌─────────────────────────────────────────────────────────────────┐
│                    Layer 1 Depacketization                      │
│                   (MctpPacketProcessor)                         │
│                                                                 │
│  Input:  raw TCP bytes (possibly fragmented)                    │
│  Output: complete CciPayloadPacket objects in asyncio.Queue     │
│                                                                 │
│  TCP bytes ──► read_exactly(header_size) ──► parse header       │
│              ──► read_exactly(payload_len) ──► assemble packet  │
│              ──► Queue.put(CciPayloadPacket)                     │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             │  asyncio.Queue[CciPayloadPacket]
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Layer 2 Depacketization                      │
│                   (_process_client)                             │
│                                                                 │
│  Input:  CciPayloadPacket from queue                            │
│  Output: opcode (int), tag (int), payload (bytes)              │
│                                                                 │
│  raw = await conn.controller_to_ep.get()                        │
│  cci_msg = raw.get_cci_message()          # extracts inner msg  │
│  opcode = cci_msg.header.command_opcode                         │
│  tag    = cci_msg.header.message_tag                            │
│  payload= bytes(cci_msg.payload)                                │
│                                                                 │
│  ──► _forward_to_cli(raw, writer, opcode, tag, payload)         │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             │  opcode, tag, payload (raw bytes)
                             ▼
                  MctpCciApiClient.send_raw_cci()
                             │
                             ▼
                      Switch (port 8100)
```

### 5.1 Why Two Layers?

| Layer | Class                  | Responsibility                                          |
|-------|------------------------|---------------------------------------------------------|
| 1     | `MctpPacketProcessor`  | TCP framing → complete MCTP packet (byte assembly)      |
| 2     | `_process_client()`    | MCTP packet → CCI inner message (protocol unwrapping)  |

This separation mirrors the MCTP stack layering in the CXL specification:
- Layer 1 handles transport-level concerns (TCP stream → MCTP packet boundaries)
- Layer 2 handles messaging-level concerns (MCTP packet → CCI command extraction)

---

## 6. Data Plane vs Control Plane Separation

> **⚠️ CRITICAL:** Port 8300 handles the **CONTROL PLANE only**. It never touches the DATA PLANE.

### 6.1 Control Plane (Port 8300)

```
External Client ──TCP:8300──► FmMctpCciServer
                               │
                               │  CCI commands over MCTP
                               │  (IDENTIFY, CONFIGURE_PID, GET_DRT, SET_DRT, ...)
                               ▼
                         MctpCciApiClient
                               │
                               ▼
                        Switch programming
                        (switch state changes)
```

- Protocol: CCI (Component Command Interface) over MCTP over TCP
- Purpose: Configure and query the PBR switch (port assignments, DRT, PIDs)
- Packet type: `CciPayloadPacket` wrapping `CciMessagePacket`
- Handled by: `FmMctpCciServer` → `MctpCciApiClient.send_raw_cci()`

### 6.2 Data Plane (PbrSwitchRouter — completely separate)

```
CXL Host ──CXL TLP──► PbrSwitchRouter
                            │
                            │  MemRead / MemWrite TLPs
                            │  (actual memory access requests)
                            ▼
                      PBR switch routing
                      (route to correct memory device)
```

- Protocol: CXL Transaction Layer Packets (TLP)
- Purpose: Route actual memory read/write operations
- Packet type: `CxlIoPacket` (MemRead, MemWrite, etc.)
- Handled by: `PbrSwitchRouter` (completely independent subsystem)

### 6.3 Why This Separation Matters

```
┌─────────────────────────────────────────────────────────────────┐
│              NEVER mix these two planes:                        │
│                                                                 │
│  Control Plane (port 8300):                                     │
│    CCI over MCTP → switch programming → port assignments        │
│    "Tell the switch HOW to route"                               │
│                                                                 │
│  Data Plane (PbrSwitchRouter):                                  │
│    CXL TLPs → actual memory transactions → routed data          │
│    "Actually MOVE the data"                                     │
│                                                                 │
│  Port 8300 sets up routing tables.                              │
│  PbrSwitchRouter uses those tables for data traffic.            │
│  They never interact directly.                                  │
└─────────────────────────────────────────────────────────────────┘
```

A `SET_DRT` command via port 8300 configures where MemRead/MemWrite TLPs will be routed — but the
TLPs themselves never flow through port 8300.

---

## 7. CCI Commands Supported

All six PBR CCI opcodes are forwarded verbatim through `send_raw_cci()` to the switch:

| Opcode   | Name                         | Description                                           | Background? |
|----------|------------------------------|-------------------------------------------------------|-------------|
| `0x5700` | `IDENTIFY_PBR_SWITCH`        | Query switch identity, capabilities, firmware version | No          |
| `0x5704` | `CONFIGURE_PID_ASSIGNMENT`   | Assign Physical IDs to switch ports/devices           | No          |
| `0x5705` | `GET_PID_BINDING`            | Read current PID-to-port binding table                | No          |
| `0x5706` | `CONFIGURE_PID_BINDING`      | Configure PID-to-port bindings (complex operation)    | **Yes**     |
| `0x5708` | `GET_DRT`                    | Read the Device Routing Table                         | No          |
| `0x5709` | `SET_DRT`                    | Write/update the Device Routing Table                 | No          |

### 7.1 Background Commands

`CONFIGURE_PID_BINDING` (0x5706) is a background command. When `is_background=True` is returned
from `send_raw_cci()`, the response packet's `background_operation` field is set to `1`, signaling
to the external client that the operation will complete asynchronously.

The external client is responsible for polling or waiting for completion using whatever mechanism
the switch supports (typically a separate GET command or interrupt).

### 7.2 CCI Enum Reference

```python
from opencis.cxl.cci.common import CCI_FM_API_COMMAND_OPCODE

# PBR switch opcodes (fabric manager specific)
IDENTIFY_PBR_SWITCH     = CCI_FM_API_COMMAND_OPCODE(0x5700)
CONFIGURE_PID_ASSIGNMENT = CCI_FM_API_COMMAND_OPCODE(0x5704)
GET_PID_BINDING         = CCI_FM_API_COMMAND_OPCODE(0x5705)
CONFIGURE_PID_BINDING   = CCI_FM_API_COMMAND_OPCODE(0x5706)
GET_DRT                 = CCI_FM_API_COMMAND_OPCODE(0x5708)
SET_DRT                 = CCI_FM_API_COMMAND_OPCODE(0x5709)
```

---

## 8. Error Handling

### 8.1 Error Handling Table

| Scenario                              | Detection Point          | Response                                   | Log Level |
|---------------------------------------|--------------------------|--------------------------------------------|-----------|
| `mctp_client` is `None`              | `_forward_to_cli()`      | `CCI_RETURN_CODE.UNSUPPORTED`, empty bytes | WARNING   |
| `send_raw_cci()` raises exception     | `_forward_to_cli()`      | `CCI_RETURN_CODE.INTERNAL_ERROR` (if defined), close conn | ERROR |
| TCP connection reset by peer          | `_handle_client()`       | Cancel tasks, clean up resources           | INFO      |
| Malformed packet (parse error)        | `MctpPacketProcessor`    | Close connection, log details              | ERROR     |
| Queue overflow (slow consumer)        | `asyncio.Queue.put()`    | Backpressure (producer blocks)             | N/A       |
| Switch timeout (no response)          | `send_raw_cci()`         | Propagated as exception to adapter         | ERROR     |
| `asyncio.CancelledError`             | `_process_client()`      | Graceful shutdown (re-raise)               | DEBUG     |
| Client disconnects mid-packet         | `MctpPacketProcessor`    | Raise `EOFError`, close connection         | INFO      |
| Unknown opcode sent to switch         | Switch (via `send_raw_cci`) | Switch returns `UNSUPPORTED`, forwarded | INFO   |

### 8.2 Offline Mode Detailed Flow

```python
async def _forward_to_cli(self, raw: CciPayloadPacket, writer):
    cci_msg = raw.get_cci_message()
    opcode = cci_msg.header.command_opcode
    tag = cci_msg.header.message_tag
    payload = bytes(cci_msg.payload)

    if self._mctp_client is None:
        # Offline mode: return UNSUPPORTED
        return_code = CCI_RETURN_CODE.UNSUPPORTED
        response_bytes = b""
        is_background = False
    else:
        # Forward to switch
        return_code, response_bytes, is_background = \
            await self._mctp_client.send_raw_cci(opcode, payload)

    # Build and send response packet (always, even in offline mode)
    response = build_cci_response(
        tag=tag,
        opcode=opcode,
        return_code=return_code,
        payload=response_bytes,
        is_background=is_background,
    )
    writer.write(bytes(response))
    await writer.drain()
```

### 8.3 Connection Cleanup

Each TCP connection has two associated asyncio tasks:
1. `MctpPacketProcessor` task (reads TCP → queue)
2. `_process_client()` task (reads queue → processes)

When either task terminates (normally or by exception), `_handle_client()` cancels the other task
and closes the TCP writer. This prevents resource leaks with hung connections.

---

## 9. Multi-Client Concurrency Model

### 9.1 Per-Connection Isolation

Each accepted TCP connection gets its own isolated set of resources:

```
Connection A ──► handler_task_A ──► processor_task_A ──► queue_A
Connection B ──► handler_task_B ──► processor_task_B ──► queue_B
Connection C ──► handler_task_C ──► processor_task_C ──► queue_C
                                                │
                                                │  All converge here
                                                ▼
                                    MctpCciApiClient.send_raw_cci()
                                    (async, handles concurrency via
                                     internal locking/queueing)
```

### 9.2 asyncio Concurrency

All connection handling is `async/await` — no threads, no locks at the adapter level. The event
loop multiplexes all connections. `MctpCciApiClient` is responsible for serializing concurrent
`send_raw_cci()` calls if the underlying MCTP link is single-duplex.

### 9.3 Active Connection Tracking

```python
self._active_tasks: Set[asyncio.Task] = set()

# In _handle_client():
task = asyncio.create_task(self._process_client(conn, writer))
self._active_tasks.add(task)
task.add_done_callback(self._active_tasks.discard)
```

In `_stop()`, all active tasks are cancelled:
```python
async def _stop(self):
    if self._server:
        self._server.close()
        await self._server.wait_closed()
    for task in list(self._active_tasks):
        task.cancel()
    await asyncio.gather(*self._active_tasks, return_exceptions=True)
```

### 9.4 No State Shared Between Connections

Because `FmMctpCciServer` has no local CCI state, there is no risk of one connection's state
affecting another. The only shared resource is `MctpCciApiClient`, which manages its own
concurrency internally.

---

## 10. Port Assignment Reference

| Port | Component                        | Direction        | Protocol          | Purpose                                    |
|------|----------------------------------|------------------|-------------------|--------------------------------------------|
| 8100 | `MctpConnectionManager`          | Switch → FM      | MCTP over TCP     | Switch connects here to be managed by FM   |
| 8200 | `FabricManagerSocketIoServer`    | CLI → FM         | SocketIO / HTTP   | FM CLI (curl, scripts, FM management UI)   |
| 8300 | `FmMctpCciServer`                | MCTP clients → FM| MCTP over TCP     | External MCTP clients (BMC, test tools)    |

### 10.1 Traffic Flow Summary

```
Switch ─────────────────────────────────────────────────────► FM:8100
  (MCTP CCI responses flowing back from switch)

curl/script ─────────────────────────────────────────────────► FM:8200
  (REST/SocketIO commands from FM CLI)

BMC / Test Tool ──────────────────────────────────────────────► FM:8300
  (MCTP CCI commands from external MCTP clients)

All three ultimately converge through MctpCciApiClient → FM:8100 → Switch
```

---

## 11. Files Added / Modified / Deleted

### 11.1 Added (New Files)

| File                                          | Description                                           |
|-----------------------------------------------|-------------------------------------------------------|
| `tests/test_mctp_fm_port.py`                  | 11 unit tests for FmMctpCciServer (AsyncMock-based)   |
| `tests/test_mctp_fm_port_integration.py`      | 15 integration tests (MCTP framing pipeline)          |

### 11.2 Modified (Changed Files)

| File                                                           | Change Description                                                    |
|----------------------------------------------------------------|-----------------------------------------------------------------------|
| `opencis/cxl/component/mctp/fm_mctp_cci_server.py`            | **Complete rewrite** — pure adapter (removed all embedded CCI logic) |
| `opencis/cxl/component/mctp/mctp_cci_api_client.py`           | Added `send_raw_cci(opcode, payload, port_index)` method             |
| `opencis/apps/fabric_manager.py`                               | Removed `PbrSwitchManager`, `PbrCommandService`; pass `mctp_client=self._api_client` |

### 11.3 Deleted (Removed Files)

| File                                                                    | Reason                                                       |
|-------------------------------------------------------------------------|--------------------------------------------------------------|
| `opencis/cxl/component/fabric_manager/pbr_command_service.py`          | Replaced by `send_raw_cci()` in `MctpCciApiClient`           |

### 11.4 Key Change: fabric_manager.py

Before (v1.x):
```python
# fabric_manager.py (BEFORE)
self._pbr_switch_manager = PbrSwitchManager(...)
self._pbr_command_service = PbrCommandService(
    switch_manager=self._pbr_switch_manager
)
self._mctp_cci_server = FmMctpCciServer(
    host="0.0.0.0",
    port=8300,
    pbr_command_service=self._pbr_command_service  # embedded logic
)
```

After (v2.0):
```python
# fabric_manager.py (AFTER)
# No PbrSwitchManager, no PbrCommandService
self._mctp_cci_server = FmMctpCciServer(
    host="0.0.0.0",
    port=8300,
    mctp_client=self._api_client  # shared FM CLI path
)
```

---

## 12. Test Coverage

### 12.1 Test Summary

| File                                     | Tests | Coverage Focus                                      |
|------------------------------------------|-------|-----------------------------------------------------|
| `tests/test_mctp_fm_port.py`             | 11    | Unit tests: constructor, offline mode, bind client  |
| `tests/test_mctp_fm_port_integration.py` | 15    | Integration: full MCTP framing pipeline             |
| **Total**                                | **26**| **All pass in 0.84s**                               |

### 12.2 Unit Tests (`test_mctp_fm_port.py`)

| # | Test Name                              | What It Verifies                                              |
|---|----------------------------------------|---------------------------------------------------------------|
| 1 | `test_init_no_client`                  | Constructor with `mctp_client=None` succeeds                  |
| 2 | `test_init_with_client`                | Constructor with valid `MctpCciApiClient` stores reference    |
| 3 | `test_get_port`                        | `get_port()` returns configured port number                   |
| 4 | `test_offline_returns_unsupported`     | No client → every opcode returns `UNSUPPORTED`                |
| 5 | `test_bind_mctp_client`                | `bind_mctp_client()` replaces `None` with live client         |
| 6 | `test_bind_replaces_existing`          | `bind_mctp_client()` can replace existing client              |
| 7 | `test_forward_identify`                | `IDENTIFY_PBR_SWITCH` forwarded to `send_raw_cci`             |
| 8 | `test_forward_get_drt`                 | `GET_DRT` forwarded with correct opcode bytes                 |
| 9 | `test_forward_set_drt`                 | `SET_DRT` payload bytes forwarded verbatim                    |
| 10| `test_forward_background`              | `CONFIGURE_PID_BINDING` → `is_background=True` in response    |
| 11| `test_response_echoes_tag`             | Response `message_tag` matches request `message_tag`          |

### 12.3 Integration Tests (`test_mctp_fm_port_integration.py`)

| #  | Test Name                                      | What It Verifies                                                |
|----|------------------------------------------------|-----------------------------------------------------------------|
| 1  | `test_full_pipeline_identify`                  | End-to-end: TCP bytes → depacketize → send_raw_cci → response  |
| 2  | `test_full_pipeline_get_drt`                   | Full pipeline for GET_DRT                                       |
| 3  | `test_full_pipeline_set_drt`                   | Full pipeline for SET_DRT with payload                          |
| 4  | `test_full_pipeline_configure_pid_assignment`  | Full pipeline for CONFIGURE_PID_ASSIGNMENT                      |
| 5  | `test_full_pipeline_get_pid_binding`           | Full pipeline for GET_PID_BINDING                               |
| 6  | `test_full_pipeline_configure_pid_binding`     | Background command: `is_background=True` in response           |
| 7  | `test_multi_client_concurrent`                 | Two clients simultaneously, isolated queues                     |
| 8  | `test_offline_mode_identify`                   | Offline: IDENTIFY returns UNSUPPORTED via full pipeline         |
| 9  | `test_offline_mode_set_drt`                    | Offline: SET_DRT returns UNSUPPORTED via full pipeline          |
| 10 | `test_late_bind_before_command`                | `bind_mctp_client()` called before first command works          |
| 11 | `test_late_bind_after_connect`                 | Client connects first (offline), then client bound → commands work |
| 12 | `test_response_tag_echoed`                     | Framing: response tag == request tag (verified at wire level)   |
| 13 | `test_response_opcode_echoed`                  | Framing: response opcode == request opcode at wire level        |
| 14 | `test_connection_close_cleanup`                | TCP close → all tasks cancelled, no resource leaks             |
| 15 | `test_malformed_packet_handling`               | Malformed TCP input → connection closed gracefully              |

### 12.4 Running the Tests

```bash
# Run all 26 tests
pytest tests/test_mctp_fm_port.py tests/test_mctp_fm_port_integration.py -v

# Expected output:
# ========================= 26 passed in 0.84s ==========================

# Run with coverage
pytest tests/test_mctp_fm_port.py tests/test_mctp_fm_port_integration.py \
    --cov=opencis/cxl/component/mctp/fm_mctp_cci_server \
    --cov=opencis/cxl/component/mctp/mctp_cci_api_client \
    --cov-report=term-missing
```

---

## 13. How to Use Port 8300

### 13.1 Connection Setup

```python
import asyncio
import struct
from opencis.cxl.transport.cci_packets import CciMessagePacket, CciPayloadPacket
from opencis.cxl.transport.packet_constants import CCI_MCTP_MESSAGE_CATEGORY
from opencis.cxl.cci.common import CCI_FM_API_COMMAND_OPCODE

HOST = "127.0.0.1"
PORT = 8300

async def connect_to_fm_mctp():
    reader, writer = await asyncio.open_connection(HOST, PORT)
    return reader, writer
```

### 13.2 Build and Send a CCI Command

```python
async def send_cci_command(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    opcode: int,
    payload: bytes = b"",
    message_tag: int = 1,
):
    """Send a CCI command packet and receive the response."""

    # Build CciMessagePacket (inner)
    cci_msg = CciMessagePacket()
    cci_msg.header.command_opcode = opcode
    cci_msg.header.message_tag = message_tag
    cci_msg.header.message_length = len(payload)
    cci_msg.header.background_operation = 0
    if payload:
        cci_msg.payload = payload

    # Wrap in CciPayloadPacket (outer MCTP transport)
    packet = CciPayloadPacket()
    packet.mctp_header.category = CCI_MCTP_MESSAGE_CATEGORY.REQUEST
    packet.mctp_header.tag_owner = 1
    packet.mctp_header.message_tag = message_tag
    packet.cci_message = cci_msg

    # Send over TCP
    raw_bytes = bytes(packet)
    writer.write(raw_bytes)
    await writer.drain()

    # Read response header (fixed size)
    header_size = CciPayloadPacket.get_header_size()
    header_bytes = await reader.readexactly(header_size)

    # Parse response header to get payload length
    response_header = CciPayloadPacket.parse_header(header_bytes)
    payload_len = response_header.cci_message_length

    # Read response payload
    payload_bytes = b""
    if payload_len > 0:
        payload_bytes = await reader.readexactly(payload_len)

    return response_header, payload_bytes
```

### 13.3 Example: IDENTIFY_PBR_SWITCH

```python
async def identify_pbr_switch():
    reader, writer = await connect_to_fm_mctp()
    try:
        header, payload = await send_cci_command(
            reader, writer,
            opcode=0x5700,   # IDENTIFY_PBR_SWITCH
            payload=b"",
            message_tag=1,
        )
        print(f"Return code: {header.return_code}")
        print(f"Response payload ({len(payload)} bytes): {payload.hex()}")
    finally:
        writer.close()
        await writer.wait_closed()

asyncio.run(identify_pbr_switch())
```

### 13.4 Example: SET_DRT Using PBR Struct Classes

```python
from opencis.cxl.cci.fabric_manager.pbr_switch import SetDrtCommand, SetDrtRequestPayload
from opencis.cxl.component.pbr_switch_manager import DrtEntry, DrtEntryType

async def set_drt(entries: list[DrtEntry]):
    reader, writer = await connect_to_fm_mctp()
    try:
        # Build typed payload using PBR struct classes
        request = SetDrtRequestPayload()
        request.num_entries = len(entries)
        for i, entry in enumerate(entries):
            request.entries[i].entry_type = entry.entry_type
            request.entries[i].start_port = entry.start_port
            request.entries[i].end_port = entry.end_port

        payload_bytes = bytes(request)

        header, response = await send_cci_command(
            reader, writer,
            opcode=0x5709,   # SET_DRT
            payload=payload_bytes,
            message_tag=2,
        )
        print(f"SET_DRT result: {header.return_code}")
    finally:
        writer.close()
        await writer.wait_closed()
```

### 13.5 Example: CONFIGURE_PID_ASSIGNMENT

```python
from opencis.cxl.cci.fabric_manager.pbr_switch.configure_pid_assignment import (
    PidAssignmentEntry, PidAssignmentOperation
)
from opencis.cxl.cci.fabric_manager.pbr_switch import (
    ConfigurePidAssignmentCommand, ConfigurePidAssignmentRequestPayload
)

async def configure_pid_assignment(port: int, pid: int):
    reader, writer = await connect_to_fm_mctp()
    try:
        request = ConfigurePidAssignmentRequestPayload()
        request.num_entries = 1
        request.entries[0].port_index = port
        request.entries[0].pid = pid
        request.entries[0].operation = PidAssignmentOperation.ASSIGN

        payload_bytes = bytes(request)

        header, response = await send_cci_command(
            reader, writer,
            opcode=0x5704,   # CONFIGURE_PID_ASSIGNMENT
            payload=payload_bytes,
            message_tag=3,
        )
        print(f"CONFIGURE_PID_ASSIGNMENT result: {header.return_code}")
    finally:
        writer.close()
        await writer.wait_closed()
```

### 13.6 Example: Handle Background Command (CONFIGURE_PID_BINDING)

```python
async def configure_pid_binding(binding_payload: bytes):
    reader, writer = await connect_to_fm_mctp()
    try:
        header, response = await send_cci_command(
            reader, writer,
            opcode=0x5706,   # CONFIGURE_PID_BINDING
            payload=binding_payload,
            message_tag=4,
        )

        if header.background_operation:
            print("Command accepted as background operation.")
            print("Poll switch for completion status.")
        else:
            print(f"Command completed synchronously: {header.return_code}")
    finally:
        writer.close()
        await writer.wait_closed()
```

---

## 14. Design Decisions

### Decision 1: Pure Adapter (No Duplicated Logic)

**Choice:** `FmMctpCciServer` contains zero CCI processing logic. It is a pure adapter that
translates the wire format and delegates entirely to `MctpCciApiClient`.

**Rationale:** The alternative (embedding a `PbrSwitchManager` / `PbrCommandService` in the MCTP
server) requires maintaining two independent code paths for CCI command handling. Any bug fix or
feature addition must be applied in both places. The pure adapter ensures a **single source of
truth**: the switch's actual state, accessed through one canonical API client.

**Trade-off:** The MCTP adapter cannot apply any MCTP-specific filtering or pre-processing before
reaching the switch. This is acceptable because all such logic belongs in `MctpCciApiClient`.

---

### Decision 2: `send_raw_cci()` vs. Typed Methods

**Choice:** `send_raw_cci(opcode, payload_bytes)` takes raw bytes rather than typed struct objects.

**Rationale:** If the adapter were required to deserialize request bytes into typed structs and
re-serialize them before calling the API client, it would need to:
- Know the type of every possible command
- Be updated whenever a new command is added
- Risk subtle mutations during deserialization/re-serialization

By passing bytes verbatim, the adapter is completely opcode-agnostic. A new PBR command opcode
can be added to the switch without any change to `FmMctpCciServer`.

**Trade-off:** Error messages at the API client level refer to raw bytes rather than named fields.
Debugging malformed requests requires hex-level inspection.

---

### Decision 3: AsyncMock in Tests

**Choice:** Tests use `unittest.mock.AsyncMock` for `MctpCciApiClient` rather than setting up a
full switch stack.

**Rationale:** Setting up a complete switch stack (port 8100, MCTP connection, PBR switch process)
would make tests slow, flaky, and environment-dependent. AsyncMock allows the 26 tests to:
- Run in 0.84 seconds
- Be deterministic (no timing dependencies)
- Test the complete MCTP framing pipeline without infrastructure
- Be run in CI without any external processes

**Trade-off:** Tests do not verify actual switch behavior. Full end-to-end testing (with a real
switch or a switch simulator) is a separate test suite concern.

---

### Decision 4: `bind_mctp_client()` for Late Injection

**Choice:** The `mctp_client` parameter is optional in `__init__()`, with `bind_mctp_client()`
available for late injection.

**Rationale:** In the real system, the switch connects to port 8100 asynchronously after
`FmMctpCciServer` has already started. The server must be ready to accept TCP connections before
the switch has connected. `bind_mctp_client()` allows the `MctpConnectionManager` to inject the
client once the switch handshake is complete, without requiring a restart.

**Implementation:** `bind_mctp_client()` is thread-safe for asyncio (assignment is atomic in
CPython). In `_forward_to_cli()`, the client reference is read once at the start; if `None`, the
UNSUPPORTED response is returned.

---

### Decision 5: UNSUPPORTED When No Client

**Choice:** When `mctp_client is None`, return `CCI_RETURN_CODE.UNSUPPORTED` (not an error,
not a timeout, not a silent drop).

**Rationale:** 
- **Not timeout:** A timeout would cause the client to wait and then fail with a different error.
- **Not drop:** Dropping the packet would cause the client to wait indefinitely.
- **Not hard error (close connection):** The client might legitimately connect before the switch
  does. An UNSUPPORTED response allows the client to retry later.

`UNSUPPORTED` is the standard CCI return code for "this endpoint does not support this command."
In offline mode, no command is supported, so UNSUPPORTED is semantically correct and
immediately informative.

---

## Appendix A: Class Relationship Diagram

```
CxlFabricManager
    │
    ├── MctpConnectionManager (port 8100)
    │       │
    │       └── manages switch TCP connection
    │
    ├── MctpCciApiClient   ◄─────────────────────── shared instance
    │       │                                            │
    │       │  .send_raw_cci()                          │
    │       └── sends CCI commands to switch             │
    │                                                    │
    ├── FabricManagerSocketIoServer (port 8200)          │
    │       │                                            │
    │       └── api_client ──────────────────────────────┤ (same shared)
    │                                                    │
    └── FmMctpCciServer (port 8300)                     │
            │                                            │
            └── _mctp_client ─────────────────────────── (same shared)
                    │
                    ├── MctpPacketProcessor (Layer 1)
                    ├── _process_client() (Layer 2)
                    └── _forward_to_cli()
                            │
                            └── MctpCciApiClient.send_raw_cci()
```

## Appendix B: Sequence Diagram — Full Request/Response Cycle

```
External         FmMctp         MctpPacket       _process_    MctpCci
Client           CciServer      Processor        Client()     ApiClient    Switch
  │                │                │                │              │         │
  │──TCP bytes──►  │                │                │              │         │
  │                │──spawn task──► │                │              │         │
  │                │                │──assemble pkt─►│              │         │
  │                │                │                │              │         │
  │                │                │──Queue.put()──►│              │         │
  │                │                │                │              │         │
  │                │                │                │──get_cci_msg()         │
  │                │                │                │  (Layer 2)   │         │
  │                │                │                │              │         │
  │                │                │                │──send_raw────►         │
  │                │                │                │  _cci()      │         │
  │                │                │                │              │──MCTP──►│
  │                │                │                │              │         │
  │                │                │                │              │◄─resp───│
  │                │                │                │              │         │
  │                │                │                │◄─(rc,bytes,  │         │
  │                │                │                │   is_bg)─────│         │
  │                │                │                │              │         │
  │                │                │                │─build resp   │         │
  │                │                │                │─writer.write()         │
  │                │                │                │              │         │
  │◄──TCP bytes────────────────────────────────────── │              │         │
  │  (response pkt)│                │                │              │         │
```

---

*End of MCTP FM CCI Port Design Document v2.0*
