# SMBus ↔ MCTP Bridge — Developer Guide

**Version:** 1.0  
**Date:** May 2026  
**Branch:** `v0.5-dev`  
**Status:** Implemented

---

## Overview

This guide describes the **host-side adapter** that bridges QEMU's SMBus Slave
and SMBus Master to the Fabric Manager's MCTP CCI port (TCP 8300).

The FM/Switch stack is **unchanged** — it continues to accept raw
`CciPayloadPacket` over TCP on port 8300 (`FmMctpCciServer`).  
The bridge is a pure relay running on the host.

---

## Architecture

```
QEMU Guest
┌───────────────────────────────────────────────────────────────┐
│  SMBus Slave                            SMBus Master          │
│  (sends raw MCTP CciPayloadPackets)     (receives CCI resp)   │
└──────────────┬─────────────────────────────────┬─────────────┘
               │  Unix domain socket (full-duplex) │
               ▼                                  ▲
┌──────────────────────────────────────────────────────────────┐
│                SmbusToMctpBridge  (host)                     │
│                                                              │
│  asyncio.start_unix_server(path=/tmp/smbus_mctp.sock)        │
│  Per connection:                                             │
│    1. MctpPacketReader reads CciPayloadPacket from Slave     │
│    2. Bridge patches message_tag → auto-sequence (0-255)     │
│    3. Opens TCP connection to FM :8300                       │
│    4. Forwards CciPayloadPacket bytes → FM                   │
│    5. Reads CciPayloadPacket response from FM                │
│    6. Writes response bytes → Unix socket → Master           │
└─────────────────────────┬────────────────────────────────────┘
                          │ TCP :8300
                          ▼
          ┌──────────────────────────────────┐
          │  Docker FM  (unchanged)           │
          │  FmMctpCciServer  :8300           │
          │    → send_raw_cci()               │
          │    → MctpCciApiClient  :8100      │
          │    → CxlSwitch / PbrSwitchManager │
          └──────────────────────────────────┘
```

---

## Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| **Unix domain socket** | Kernel IPC — zero TCP overhead, native QEMU `-chardev socket` support, shareable via Docker volume mount |
| **Full-duplex (one socket)** | QEMU sends on the same fd it receives on; single `asyncio.start_unix_server` handles both directions |
| **Raw MCTP packets** | QEMU Slave sends `CciPayloadPacket` directly — no SMBus framing header needed |
| **Auto-sequenced tags** | Bridge overrides `message_tag` with a per-session counter (0–255 cyclic); eliminates tag collision between sessions |
| **Dedicated TCP conn per session** | Each QEMU client gets its own TCP stream to FM — no mux/demux needed |
| **Zero FM stack changes** | `FmMctpCciServer` stays pure MCTP-over-TCP; bridge is fully decoupled |

---

## Packet Flow (Wire Level)

```
QEMU Slave  →  Unix socket  →  Bridge  →  TCP:8300  →  FM

Step 1: QEMU Slave sends raw CciPayloadPacket bytes on Unix socket

Step 2: Bridge reads packet via _read_cci_payload_packet()
        Parses inner CciMessagePacket
        Extracts: opcode, payload_bytes, original_tag

Step 3: Bridge rebuilds CciMessagePacket with auto_tag = (seq & 0xFF)
        Wraps in new CciPayloadPacket
        Sends bytes over TCP to FM :8300

Step 4: FM (FmMctpCciServer) receives packet
        Calls MctpCciApiClient.send_raw_cci(opcode, payload)
        Switch processes CCI command
        Returns (return_code, response_bytes, is_background)
        FM sends back CciPayloadPacket RESPONSE on same TCP connection

Step 5: Bridge reads response from FM TCP stream
        Forwards raw response bytes → Unix socket → QEMU Master

Step 6: Tag counter incremented: seq = (seq + 1) & 0xFF
```

---

## Wire Format

Both sides use standard `CciPayloadPacket` framing (same as the rest of opencis):

```
┌─────────────────────────────────────────────────────────┐
│  SystemHeader  (payload_type=CCI_MCTP, payload_length)  │
├─────────────────────────────────────────────────────────┤
│  CciHeader     (port_index, msg_class=REQ/RSP)          │
├─────────────────────────────────────────────────────────┤
│  CciMessagePacket                                       │
│    ├─ cci_msg_header.message_category  (0=REQ, 1=RSP)   │
│    ├─ cci_msg_header.command_opcode    (e.g. 0x5700)    │
│    ├─ cci_msg_header.message_tag       (auto-assigned)  │
│    ├─ cci_msg_header.return_code       (in responses)   │
│    ├─ cci_msg_header.background_operation               │
│    └─ payload bytes  (command-specific)                 │
└─────────────────────────────────────────────────────────┘
```

---

## Files

| File | Description |
|------|-------------|
| `opencis/cxl/component/smbus/__init__.py` | Package init |
| `opencis/cxl/component/smbus/smbus_mctp_bridge.py` | Bridge implementation |
| `tests/test_smbus_mctp_bridge.py` | 7 pytest tests |
| `run_pbr_env.py` | `--smbus-bridge` and `--smbus-fm-port` flags added |

---

## Usage

### Option A — Integrated with `run_pbr_env.py`

```bash
# Start full PBR environment WITH the SMBus bridge
python run_pbr_env.py --smbus-bridge /tmp/smbus_mctp.sock

# Custom FM port (if FM MCTP CCI is on a different port)
python run_pbr_env.py --smbus-bridge /tmp/smbus_mctp.sock --smbus-fm-port 8300
```

The bridge starts **after the FM is ready**, so QEMU can connect immediately
once `run_pbr_env.py` prints:

```
[Env] SMBus-MCTP bridge ready on /tmp/smbus_mctp.sock
```

---

### Option B — Standalone bridge

```bash
python -m opencis.cxl.component.smbus.smbus_mctp_bridge \
    --unix-path /tmp/smbus_mctp.sock \
    --fm-host 127.0.0.1 \
    --fm-port 8300
```

Use this when the FM is running separately (e.g., inside Docker).

---

## QEMU Configuration

### Expose SMBus Slave on Unix socket

```bash
qemu-system-x86_64 \
  ...existing args... \
  -chardev socket,id=smbus_slave,path=/tmp/smbus_mctp.sock,server=off \
  -device smbus-slave,chardev=smbus_slave
```

> **Note:** `server=off` means QEMU connects to the socket (bridge is the
> server).  Use `server=on,wait=off` if you want QEMU to be the server instead
> — in that case, configure the bridge as a client (requires code change).

---

### Docker volume mount (if FM runs in Docker)

```yaml
# docker-compose.yml
services:
  fm:
    image: opencis-core
    volumes:
      - /tmp/smbus_mctp.sock:/tmp/smbus_mctp.sock
    ports:
      - "8100:8100"
      - "8200:8200"
      - "8300:8300"
```

The Unix socket is shared between the host (where QEMU runs) and the Docker
container via a bind mount.

---

## Testing

### Run all tests

```bash
python -m pytest tests/test_smbus_mctp_bridge.py -v
```

Expected output:
```
tests/test_smbus_mctp_bridge.py::test_bridge_auto_sequences_tag         PASSED
tests/test_smbus_mctp_bridge.py::test_bridge_round_trip_identify        PASSED
tests/test_smbus_mctp_bridge.py::test_bridge_background_command         PASSED
tests/test_smbus_mctp_bridge.py::test_bridge_tag_rollover               PASSED
tests/test_smbus_mctp_bridge.py::test_bridge_removes_socket_on_stop     PASSED
tests/test_smbus_mctp_bridge.py::test_bridge_replaces_stale_socket      PASSED
tests/test_smbus_mctp_bridge.py::test_bridge_multiple_concurrent_clients PASSED

7 passed in ~1.2s
```

### Manual end-to-end test

```python
# Simulate QEMU SMBus Slave — send IDENTIFY_PBR_SWITCH
import asyncio, socket, struct
from opencis.cxl.transport.cci_packets import CciMessagePacket, CciPayloadPacket
from opencis.cxl.transport.packet_constants import CCI_MCTP_MESSAGE_CATEGORY
from opencis.cxl.cci.common import CCI_FM_API_COMMAND_OPCODE

OPCODE = CCI_FM_API_COMMAND_OPCODE.IDENTIFY_PBR_SWITCH   # 0x5700

# Build request
cci_msg = CciMessagePacket.create(
    message_category=CCI_MCTP_MESSAGE_CATEGORY.REQUEST,
    opcode=OPCODE,
    data=b"",
)
req_pkt = CciPayloadPacket.create(cci_msg)
req_bytes = bytes(req_pkt)

# Send over Unix socket
s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
s.connect("/tmp/smbus_mctp.sock")
s.sendall(req_bytes)
resp = s.recv(4096)
s.close()

print(f"Response: {resp.hex()}")
# Parse response
resp_pkt = CciPayloadPacket(bytearray(resp))
resp_msg = resp_pkt.get_cci_message()
print(f"Opcode  : {resp_msg.cci_msg_header.command_opcode:#06x}")
print(f"RC      : {resp_msg.cci_msg_header.return_code}")
print(f"BG      : {resp_msg.cci_msg_header.background_operation}")
print(f"Payload : {resp_msg.get_payload().hex()}")
```

---

## Supported CCI Commands

All commands that `FmMctpCciServer` supports are automatically bridged:

| Command | Opcode | Type | Notes |
|---------|--------|------|-------|
| IDENTIFY_PBR_SWITCH | 0x5700 | Foreground | Returns PBR switch capabilities |
| CONFIGURE_PID_ASSIGNMENT | 0x5704 | Foreground | Assign PID to target port |
| GET_PID_BINDING | 0x5705 | Foreground | Query binding for VPPB slot |
| CONFIGURE_PID_BINDING | 0x5706 | **Background** | rc = BACKGROUND_COMMAND_STARTED |
| GET_DRT | 0x5708 | Foreground | Read DRT entry |
| SET_DRT | 0x5709 | Foreground | Program DRT entry |
| IDENTIFY_GAE | 0x5800 | Foreground | GAE capabilities |
| GET_PID_ACCESS_VECTORS | 0x5801 | Foreground | Access vector table |
| PROXY_GFD_MGMT | 0x5802 | Foreground | Tunnel to GFD |
| GET_PROXY_THREAD_STATUS | 0x5803 | Foreground | Background thread status |
| CANCEL_PROXY_THREAD | 0x5804 | Foreground | Cancel background GFD op |

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `ConnectionRefusedError` on Unix socket | Bridge not running or wrong path | Confirm `run_pbr_env.py` printed `SMBus-MCTP bridge ready` |
| `ConnectionRefusedError` to FM | FM not started yet or wrong port | Bridge starts after FM; check `--smbus-fm-port` matches |
| Response is `UNSUPPORTED` | FM has no switch connected yet | Wait for switch to connect to FM before sending commands |
| `asyncio.IncompleteReadError` | Packet truncated — wrong framing | Verify QEMU sends complete `CciPayloadPacket` (not raw opcode bytes) |
| Tags not 0, 1, 2… | Checking QEMU's original tags, not FM-forwarded | Check the FM-side capture, not the QEMU socket — bridge patches before forwarding |
| Bridge re-creates socket on restart | Stale `.sock` file | Bridge auto-removes stale file on startup — no action needed |
