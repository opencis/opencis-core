# MCTP CCI Port 8300 — Integration Guide

**Version:** 2.0
**Date:** May 2026
**Branch:** `v0.5-dev`
**Status:** Implemented & Tested — 26/26 tests pass

---

## Purpose

Step-by-step guide for developers integrating with or extending the
`FmMctpCciServer` (port 8300) — the Fabric Manager's external MCTP CCI adapter.

---

## Prerequisites

```bash
# Install the package in editable mode
cd opencis-core
pip install -e .

# Verify all MCTP tests pass
python -m pytest tests/test_mctp_fm_port.py tests/test_mctp_fm_port_integration.py -v
# Expected: 26 passed in ~0.84s

# Required imports used throughout this guide
from opencis.cxl.component.mctp.fm_mctp_cci_server import FmMctpCciServer
from opencis.cxl.component.mctp.mctp_cci_api_client import MctpCciApiClient
from opencis.cxl.component.mctp.mctp_connection_client import MctpConnectionClient
from opencis.cxl.cci.common import CCI_RETURN_CODE, CCI_FM_API_COMMAND_OPCODE
from opencis.cxl.transport.cci_packets import CciMessagePacket, CciPayloadPacket
from opencis.cxl.transport.packet_constants import CCI_MCTP_MESSAGE_CATEGORY
```

---

## Architecture Quick Reference

```
External MCTP Client (test tool / BMC / remote FM)
        │  TCP connection to port 8300
        ▼
┌────────────────────────────────────────────────────┐
│  FmMctpCciServer  (pure MCTP adapter)              │
│                                                    │
│  Per connection:                                   │
│    MctpPacketProcessor  ← TCP bytes                │
│    _process_client()                               │
│      raw.get_cci_message()     ← Layer 2 depacket  │
│      cci_msg.get_payload()     ← extract bytes     │
│      _forward_to_cli(opcode, payload)              │
│        └─► MctpCciApiClient.send_raw_cci() ───────►│──── TCP 8100 ──► Switch
│      CciMessagePacket.create(RESPONSE) ◄───────────│◄── switch response
│      MctpPacketProcessor  ──► TCP bytes             │
└────────────────────────────────────────────────────┘

KEY PRINCIPLE:  FmMctpCciServer has ZERO local state.
                All CCI processing happens in the switch.
                Port 8300 is a pure bridge: MCTP bytes ↔ FM CLI path.
```

---

## Step 1: Production Wiring — `CxlFabricManager`

In production, `fabric_manager.py` wires everything automatically:

```python
from opencis.apps.fabric_manager import CxlFabricManager

fm = CxlFabricManager(
    mctp_host="0.0.0.0",
    mctp_port=8100,          # switch connects to FM here
    socketio_host="0.0.0.0",
    socketio_port=8200,      # CLI (pbr_fm_cli.py) connects here
    fm_mctp_cci_port=8300,   # external MCTP clients connect here
)

async def run():
    await fm.run()
```

Internally `fabric_manager.py` does:

```python
# Shared FM CLI path — same api_client for BOTH port 8200 and port 8300
self._api_client = MctpCciApiClient(
    self._connection_manager.get_mctp_connection()
)

# Port 8300 — pure MCTP adapter bridged to the shared FM CLI path
self._fm_mctp_cci_server = FmMctpCciServer(
    host=mctp_host,
    port=fm_mctp_cci_port,
    mctp_client=self._api_client,  # <-- the FM CLI path
)
```

---

## Step 2: Standalone `FmMctpCciServer` (Test Harness with AsyncMock)

For unit tests and isolated integration tests, mock `send_raw_cci()`:

```python
import asyncio
from unittest.mock import AsyncMock, MagicMock
from opencis.cxl.component.mctp.fm_mctp_cci_server import FmMctpCciServer
from opencis.cxl.cci.common import CCI_RETURN_CODE

# Build a mock api_client whose send_raw_cci returns SUCCESS
mock_client = MagicMock()
mock_client.send_raw_cci = AsyncMock(
    return_value=(CCI_RETURN_CODE.SUCCESS, b"", False)
)

# Create server on ephemeral port (OS picks port when port=0)
server = FmMctpCciServer(host="127.0.0.1", port=0, mctp_client=mock_client)

async def main():
    task = asyncio.create_task(server.run())
    await server.wait_for_ready()               # blocks until TCP listener is up
    port = server.get_port()                    # get actual assigned port
    print(f"Server ready on port {port}")

    # ... connect test client, send commands ...

    await server.stop()

asyncio.run(main())
```

**No switch needed.** `send_raw_cci()` is intercepted by the mock.

---

## Step 3: Send a Raw MCTP CCI Command from a Test Client

Full Python client that connects and sends one CCI command:

```python
import asyncio
from opencis.cxl.transport.cci_packets import CciMessagePacket, CciPayloadPacket
from opencis.cxl.transport.packet_constants import CCI_MCTP_MESSAGE_CATEGORY
from opencis.cxl.cci.common import CCI_FM_API_COMMAND_OPCODE, CCI_RETURN_CODE

async def send_identify(host: str, port: int):
    reader, writer = await asyncio.open_connection(host, port)

    # ── Build MCTP CCI REQUEST ──────────────────────────────────────────
    req_msg = CciMessagePacket.create(
        message_category=CCI_MCTP_MESSAGE_CATEGORY.REQUEST,
        opcode=CCI_FM_API_COMMAND_OPCODE.IDENTIFY_PBR_SWITCH,   # 0x5700
        data=b"",          # no payload for IDENTIFY
        message_tag=1,     # client chooses; server echoes it back
    )
    writer.write(bytes(CciPayloadPacket.create(req_msg)))
    await writer.drain()

    # ── Read MCTP CCI RESPONSE ──────────────────────────────────────────
    from opencis.cxl.transport.packet_structs import SystemHeader
    from opencis.cxl.transport.common import BasePacket

    hdr = await reader.readexactly(SystemHeader.get_size())
    base = BasePacket(bytearray(hdr))
    body = await reader.readexactly(
        max(0, base.system_header.payload_length - len(base))
    )
    resp_pkt = CciPayloadPacket(bytearray(hdr + body))
    resp_msg  = resp_pkt.get_cci_message()

    # ── Inspect response ────────────────────────────────────────────────
    rc  = CCI_RETURN_CODE(resp_msg.cci_msg_header.return_code)
    tag = resp_msg.cci_msg_header.message_tag
    opc = resp_msg.cci_msg_header.command_opcode

    print(f"Opcode:      {opc:#06x}  (should mirror request: {CCI_FM_API_COMMAND_OPCODE.IDENTIFY_PBR_SWITCH:#06x})")
    print(f"Tag:         {tag}      (should mirror request: 1)")
    print(f"Return code: {rc.name}")
    print(f"Payload:     {resp_msg.get_payload()!r}")

    writer.close()
    await writer.wait_closed()

asyncio.run(send_identify("127.0.0.1", 8300))
```

---

## Step 4: Send a Structured SET_DRT Command

Use the PBR struct classes to build a properly encoded payload:

```python
import asyncio
from opencis.cxl.cci.fabric_manager.pbr_switch import (
    SetDrtCommand,
    SetDrtRequestPayload,
)
from opencis.cxl.component.pbr_switch_manager import DrtEntry, DrtEntryType
from opencis.cxl.transport.cci_packets import CciMessagePacket, CciPayloadPacket
from opencis.cxl.transport.packet_constants import CCI_MCTP_MESSAGE_CATEGORY
from opencis.cxl.cci.common import CCI_RETURN_CODE

async def send_set_drt(host: str, port: int):
    reader, writer = await asyncio.open_connection(host, port)

    # ── Build payload ───────────────────────────────────────────────────
    payload = SetDrtRequestPayload(
        drt_index=0,
        start_entry=0x042,
        entries=[
            DrtEntry(DrtEntryType.PHYSICAL_PORT, routing_target=1),
        ],
    )
    cci_req = SetDrtCommand.create_cci_request(payload)
    # cci_req.opcode   = 0x5709
    # cci_req.payload  = struct-packed bytes

    # ── Wrap in MCTP envelope ───────────────────────────────────────────
    req_msg = CciMessagePacket.create(
        message_category=CCI_MCTP_MESSAGE_CATEGORY.REQUEST,
        opcode=cci_req.opcode,
        data=cci_req.payload or b"",
        message_tag=2,
    )
    writer.write(bytes(CciPayloadPacket.create(req_msg)))
    await writer.drain()

    # ── Read response ───────────────────────────────────────────────────
    from opencis.cxl.transport.packet_structs import SystemHeader
    from opencis.cxl.transport.common import BasePacket
    hdr  = await reader.readexactly(SystemHeader.get_size())
    base = BasePacket(bytearray(hdr))
    body = await reader.readexactly(max(0, base.system_header.payload_length - len(base)))
    resp = CciPayloadPacket(bytearray(hdr + body)).get_cci_message()

    rc = CCI_RETURN_CODE(resp.cci_msg_header.return_code)
    print(f"SET_DRT result: {rc.name}")   # SUCCESS if switch accepted it

    writer.close()
    await writer.wait_closed()

asyncio.run(send_set_drt("127.0.0.1", 8300))
```

---

## Step 5: Send CONFIGURE_PID_ASSIGNMENT

```python
import asyncio
from opencis.cxl.cci.fabric_manager.pbr_switch import (
    ConfigurePidAssignmentCommand,
    ConfigurePidAssignmentRequestPayload,
)
from opencis.cxl.cci.fabric_manager.pbr_switch.configure_pid_assignment import (
    PidAssignmentEntry,
    PidAssignmentOperation,
)
from opencis.cxl.transport.cci_packets import CciMessagePacket, CciPayloadPacket
from opencis.cxl.transport.packet_constants import CCI_MCTP_MESSAGE_CATEGORY
from opencis.cxl.cci.common import CCI_RETURN_CODE

async def configure_pid(host: str, port: int):
    reader, writer = await asyncio.open_connection(host, port)

    payload = ConfigurePidAssignmentRequestPayload(
        operation=PidAssignmentOperation.ASSIGN,
        entries=[
            PidAssignmentEntry(pid=0x010, target_id=0, instance_id=0),
        ],
    )
    cci_req = ConfigurePidAssignmentCommand.create_cci_request(payload)

    req_msg = CciMessagePacket.create(
        message_category=CCI_MCTP_MESSAGE_CATEGORY.REQUEST,
        opcode=cci_req.opcode,     # 0x5704
        data=cci_req.payload or b"",
        message_tag=3,
    )
    writer.write(bytes(CciPayloadPacket.create(req_msg)))
    await writer.drain()

    from opencis.cxl.transport.packet_structs import SystemHeader
    from opencis.cxl.transport.common import BasePacket
    hdr  = await reader.readexactly(SystemHeader.get_size())
    base = BasePacket(bytearray(hdr))
    body = await reader.readexactly(max(0, base.system_header.payload_length - len(base)))
    resp = CciPayloadPacket(bytearray(hdr + body)).get_cci_message()

    print(f"CONFIGURE_PID_ASSIGNMENT: {CCI_RETURN_CODE(resp.cci_msg_header.return_code).name}")

    writer.close()
    await writer.wait_closed()

asyncio.run(configure_pid("127.0.0.1", 8300))
```

---

## Step 6: Handle Background Commands (CONFIGURE_PID_BINDING)

`CONFIGURE_PID_BINDING` (0x5706) is a **background command**. The switch returns
`BACKGROUND_COMMAND_STARTED` instead of `SUCCESS` immediately.

```python
import asyncio
from opencis.cxl.cci.fabric_manager.pbr_switch import (
    ConfigurePidBindingCommand,
    ConfigurePidBindingRequestPayload,
)
from opencis.cxl.cci.fabric_manager.pbr_switch.configure_pid_binding import (
    PidBindingOperation,
)
from opencis.cxl.transport.cci_packets import CciMessagePacket, CciPayloadPacket
from opencis.cxl.transport.packet_constants import CCI_MCTP_MESSAGE_CATEGORY
from opencis.cxl.cci.common import CCI_RETURN_CODE

async def configure_pid_binding(host: str, port: int):
    reader, writer = await asyncio.open_connection(host, port)

    payload = ConfigurePidBindingRequestPayload(
        operation=PidBindingOperation.BIND,
        target_vcs=0,
        target_vppb=0,
        pid=0x010,
    )
    cci_req = ConfigurePidBindingCommand.create_cci_request(payload)

    req_msg = CciMessagePacket.create(
        message_category=CCI_MCTP_MESSAGE_CATEGORY.REQUEST,
        opcode=cci_req.opcode,     # 0x5706
        data=cci_req.payload or b"",
        message_tag=4,
    )
    writer.write(bytes(CciPayloadPacket.create(req_msg)))
    await writer.drain()

    from opencis.cxl.transport.packet_structs import SystemHeader
    from opencis.cxl.transport.common import BasePacket
    hdr  = await reader.readexactly(SystemHeader.get_size())
    base = BasePacket(bytearray(hdr))
    body = await reader.readexactly(max(0, base.system_header.payload_length - len(base)))
    resp = CciPayloadPacket(bytearray(hdr + body)).get_cci_message()

    rc = CCI_RETURN_CODE(resp.cci_msg_header.return_code)
    bg = bool(resp.cci_msg_header.background_operation)

    if rc == CCI_RETURN_CODE.BACKGROUND_COMMAND_STARTED:
        print("Binding started in background — poll BackgroundOperationStatus to confirm completion")
        print(f"  background_operation flag = {bg}")
    elif rc == CCI_RETURN_CODE.SUCCESS:
        print("Binding completed synchronously (SUCCESS)")
    else:
        print(f"ERROR: {rc.name}")

    writer.close()
    await writer.wait_closed()

asyncio.run(configure_pid_binding("127.0.0.1", 8300))
```

---

## Step 7: Verify with pytest

```bash
# Run unit tests (mock-based, no switch, fast)
python -m pytest tests/test_mctp_fm_port.py -v --timeout=10
# Expected: 11 passed in ~0.44s

# Run integration tests (full framing pipeline, mock at send_raw_cci boundary)
python -m pytest tests/test_mctp_fm_port_integration.py -v --timeout=15
# Expected: 15 passed in ~0.40s

# Run both together
python -m pytest tests/test_mctp_fm_port.py tests/test_mctp_fm_port_integration.py -v
# Expected: 26 passed in 0.84s

# Run with debug logging
python -m pytest tests/test_mctp_fm_port.py -v -s --log-cli-level=DEBUG
```

---

## Step 8: Late-Bind `mctp_client` After Switch Connects

In production the switch connects to the FM asynchronously. Use `bind_mctp_client()`
to inject the api_client after it becomes ready:

```python
import asyncio
from opencis.cxl.component.mctp.fm_mctp_cci_server import FmMctpCciServer
from opencis.cxl.component.mctp.mctp_cci_api_client import MctpCciApiClient
from opencis.cxl.component.mctp.mctp_connection_manager import MctpConnectionManager

async def start_fm():
    # Start port 8300 immediately — before switch connects
    mctp_server = FmMctpCciServer(
        host="0.0.0.0",
        port=8300,
        mctp_client=None,    # no client yet — returns UNSUPPORTED until bound
    )
    srv_task = asyncio.create_task(mctp_server.run())
    await mctp_server.wait_for_ready()
    print("Port 8300 accepting connections (UNSUPPORTED mode until switch connects)")

    # Wait for switch to connect on port 8100
    conn_mgr = MctpConnectionManager("0.0.0.0", 8100)
    conn_task = asyncio.create_task(conn_mgr.run())
    await conn_mgr.wait_for_ready()

    api_client = MctpCciApiClient(conn_mgr.get_mctp_connection())
    api_task = asyncio.create_task(api_client.run())
    await api_client.wait_for_ready()

    # NOW bind — all subsequent requests on port 8300 go to the switch
    mctp_server.bind_mctp_client(api_client)
    print("Port 8300 now bridged to switch via FM CLI path")

    await asyncio.gather(srv_task, conn_task, api_task)

asyncio.run(start_fm())
```

---

## Step 9: Check Server is Ready Before Sending

Always call `wait_for_ready()` before connecting a client:

```python
server = FmMctpCciServer(host="127.0.0.1", port=0, mctp_client=mock_client)
task = asyncio.create_task(server.run())

# This blocks until TCP listener is bound and ready
await server.wait_for_ready()

# NOW safe to connect
port = server.get_port()
reader, writer = await asyncio.open_connection("127.0.0.1", port)
```

---

## Test Fixtures Reference

Copy-paste ready pytest-asyncio fixtures:

```python
import asyncio
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock
from opencis.cxl.component.mctp.fm_mctp_cci_server import FmMctpCciServer
from opencis.cxl.cci.common import CCI_RETURN_CODE


@pytest_asyncio.fixture(loop_scope="function")
async def fm_no_client():
    """FmMctpCciServer with no mctp_client — every command returns UNSUPPORTED."""
    server = FmMctpCciServer(host="127.0.0.1", port=0, mctp_client=None)
    task = asyncio.create_task(server.run())
    await server.wait_for_ready()
    yield server
    await server.stop()
    try:
        await asyncio.wait_for(task, timeout=3.0)
    except Exception:
        task.cancel()


@pytest_asyncio.fixture(loop_scope="function")
async def fm_with_mock_switch():
    """
    FmMctpCciServer with a mocked send_raw_cci() — no real TCP to switch.

    Default: returns (SUCCESS, b"", False).
    Override: mock_client.send_raw_cci.return_value = (CCI_RETURN_CODE.INVALID_INPUT, b"", False)
    """
    mock_client = MagicMock()
    mock_client.send_raw_cci = AsyncMock(
        return_value=(CCI_RETURN_CODE.SUCCESS, b"", False)
    )
    server = FmMctpCciServer(host="127.0.0.1", port=0, mctp_client=mock_client)
    task = asyncio.create_task(server.run())
    await server.wait_for_ready()
    yield server, mock_client
    await server.stop()
    try:
        await asyncio.wait_for(task, timeout=3.0)
    except Exception:
        task.cancel()
```

---

## Troubleshooting

### 1. Server returns UNSUPPORTED for all commands

**Symptom:** Every opcode returns `CCI_RETURN_CODE.UNSUPPORTED`

**Cause:** `mctp_client` is `None` (not bound).

**Fix:**
```python
# At construction:
server = FmMctpCciServer(mctp_client=api_client)

# Or late-bind after switch connects:
server.bind_mctp_client(api_client)
```

---

### 2. `send_raw_cci()` hangs — asyncio.TimeoutError

**Symptom:** `await api_client.send_raw_cci(...)` never returns.

**Cause:** `MctpCciApiClient._get_response()` waits on `asyncio.Condition` for a switch
response tagged with `req_tag`. The switch is not responding (or is not connected).

**Fix:** Ensure the complete switch stack is running before calling `send_raw_cci()`:
```python
conn = MctpConnectionClient(host=switch_host, port=8100, auto_reconnect=False)
asyncio.create_task(conn.run())
await conn.wait_for_ready()          # ← TCP connection established

api = MctpCciApiClient(conn.get_mctp_connection())
asyncio.create_task(api.run())
await api.wait_for_ready()           # ← receive loop running

# NOW safe to call send_raw_cci
rc, resp, bg = await api.send_raw_cci(opcode, payload)
```

---

### 3. `api_client.wait_for_ready()` times out in tests

**Symptom:** Test fixture hangs at `await api_client.wait_for_ready()`.

**Cause:** `MctpCciApiClient` requires a real `MctpConnectionManager` on the switch
side speaking the full MCTP framing protocol. A raw TCP `MockSwitch` that just reads
bytes won't satisfy the handshake.

**Fix:** In unit/integration tests, **mock at the `send_raw_cci()` boundary**:
```python
from unittest.mock import AsyncMock, MagicMock
mock_client = MagicMock()
mock_client.send_raw_cci = AsyncMock(return_value=(CCI_RETURN_CODE.SUCCESS, b"", False))
server = FmMctpCciServer(mctp_client=mock_client)
# No api_client.wait_for_ready() needed — mock resolves instantly.
```

---

### 4. Windows `UnicodeEncodeError` in log output

**Symptom:**
```
UnicodeEncodeError: 'charmap' codec can't encode character '\u2192'
```

**Cause:** `→` (U+2192) in a log message can't be encoded by Windows cp1252.

**Status:** Already fixed in `fm_mctp_cci_server.py` — all log messages use `->` (ASCII).

**If you add new log messages:** Use only ASCII characters.

---

### 5. Response has wrong `message_tag`

**Symptom:** `resp.cci_msg_header.message_tag != request_tag`

**Cause:** The MCTP response did not echo the request tag. This violates the MCTP spec.

**Status:** Already correct in `_process_client()`:
```python
tag = cci_msg.cci_msg_header.message_tag   # from request
...
resp_msg = CciMessagePacket.create(
    message_tag=tag,    # echoed back — required by spec
    ...
)
```

If you see wrong tags, check your test client's request tag field.

---

## Complete E2E Example

One coherent script: start server → identify → configure PID → set DRT → verify via mock.

```python
"""
e2e_mctp_example.py — Full MCTP CCI commissioning sequence on port 8300.

Run with: python e2e_mctp_example.py
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock

from opencis.cxl.component.mctp.fm_mctp_cci_server import FmMctpCciServer
from opencis.cxl.cci.common import CCI_RETURN_CODE, CCI_FM_API_COMMAND_OPCODE
from opencis.cxl.transport.cci_packets import CciMessagePacket, CciPayloadPacket
from opencis.cxl.transport.packet_constants import CCI_MCTP_MESSAGE_CATEGORY
from opencis.cxl.transport.packet_structs import SystemHeader
from opencis.cxl.transport.common import BasePacket
from opencis.cxl.cci.fabric_manager.pbr_switch import (
    SetDrtCommand,
    SetDrtRequestPayload,
    ConfigurePidAssignmentCommand,
    ConfigurePidAssignmentRequestPayload,
)
from opencis.cxl.component.pbr_switch_manager import DrtEntry, DrtEntryType
from opencis.cxl.cci.fabric_manager.pbr_switch.configure_pid_assignment import (
    PidAssignmentEntry,
    PidAssignmentOperation,
)


# ── Helper: send one CCI command and receive response ──────────────────────
async def cci_round_trip(
    reader, writer, opcode: int, payload: bytes = b"", tag: int = 1
) -> CciMessagePacket:
    req = CciMessagePacket.create(
        message_category=CCI_MCTP_MESSAGE_CATEGORY.REQUEST,
        opcode=opcode,
        data=payload,
        message_tag=tag,
    )
    writer.write(bytes(CciPayloadPacket.create(req)))
    await writer.drain()

    hdr  = await reader.readexactly(SystemHeader.get_size())
    base = BasePacket(bytearray(hdr))
    body = await reader.readexactly(max(0, base.system_header.payload_length - len(base)))
    return CciPayloadPacket(bytearray(hdr + body)).get_cci_message()


# ── Main commissioning sequence ────────────────────────────────────────────
async def main():
    # 1. Set up mock switch (records what it receives)
    received_opcodes = []

    async def mock_send_raw_cci(opcode, payload=b"", port_index=0):
        received_opcodes.append(opcode)
        print(f"  [switch] received opcode={opcode:#06x} payload_len={len(payload)}")
        return (CCI_RETURN_CODE.SUCCESS, b"", False)

    mock_client = MagicMock()
    mock_client.send_raw_cci = AsyncMock(side_effect=mock_send_raw_cci)

    # 2. Start FmMctpCciServer
    server = FmMctpCciServer(host="127.0.0.1", port=0, mctp_client=mock_client)
    srv_task = asyncio.create_task(server.run())
    await server.wait_for_ready()
    port = server.get_port()
    print(f"FmMctpCciServer listening on port {port}\n")

    # 3. Connect test MCTP client
    reader, writer = await asyncio.open_connection("127.0.0.1", port)

    # ── Step A: IDENTIFY_PBR_SWITCH ───────────────────────────────────
    print("Step A: IDENTIFY_PBR_SWITCH (0x5700)")
    resp = await cci_round_trip(
        reader, writer,
        opcode=CCI_FM_API_COMMAND_OPCODE.IDENTIFY_PBR_SWITCH,
        tag=1,
    )
    rc = CCI_RETURN_CODE(resp.cci_msg_header.return_code)
    print(f"  Result: {rc.name}  tag={resp.cci_msg_header.message_tag}\n")
    assert rc == CCI_RETURN_CODE.SUCCESS

    # ── Step B: CONFIGURE_PID_ASSIGNMENT ─────────────────────────────
    print("Step B: CONFIGURE_PID_ASSIGNMENT (0x5704) — assign PID 0x010 → port 0")
    pid_payload = ConfigurePidAssignmentRequestPayload(
        operation=PidAssignmentOperation.ASSIGN,
        entries=[PidAssignmentEntry(pid=0x010, target_id=0, instance_id=0)],
    )
    pid_req = ConfigurePidAssignmentCommand.create_cci_request(pid_payload)
    resp = await cci_round_trip(
        reader, writer,
        opcode=pid_req.opcode,
        payload=pid_req.payload or b"",
        tag=2,
    )
    rc = CCI_RETURN_CODE(resp.cci_msg_header.return_code)
    print(f"  Result: {rc.name}\n")
    assert rc == CCI_RETURN_CODE.SUCCESS

    # ── Step C: SET_DRT ───────────────────────────────────────────────
    print("Step C: SET_DRT (0x5709) — DRT[0][0x010] = PhysicalPort 1")
    drt_payload = SetDrtRequestPayload(
        drt_index=0,
        start_entry=0x010,
        entries=[DrtEntry(DrtEntryType.PHYSICAL_PORT, routing_target=1)],
    )
    drt_req = SetDrtCommand.create_cci_request(drt_payload)
    resp = await cci_round_trip(
        reader, writer,
        opcode=drt_req.opcode,
        payload=drt_req.payload or b"",
        tag=3,
    )
    rc = CCI_RETURN_CODE(resp.cci_msg_header.return_code)
    print(f"  Result: {rc.name}\n")
    assert rc == CCI_RETURN_CODE.SUCCESS

    # ── Verify mock received all 3 commands ───────────────────────────
    print("Verification:")
    print(f"  Switch received {len(received_opcodes)} commands:")
    for opcode in received_opcodes:
        name = CCI_FM_API_COMMAND_OPCODE(opcode).name
        print(f"    {opcode:#06x}  {name}")

    assert CCI_FM_API_COMMAND_OPCODE.IDENTIFY_PBR_SWITCH   in received_opcodes
    assert CCI_FM_API_COMMAND_OPCODE.CONFIGURE_PID_ASSIGNMENT in received_opcodes
    assert CCI_FM_API_COMMAND_OPCODE.SET_DRT                in received_opcodes
    print("\nAll assertions passed. E2E commissioning sequence complete.")

    # 4. Teardown
    writer.close()
    await writer.wait_closed()
    await server.stop()
    srv_task.cancel()


if __name__ == "__main__":
    asyncio.run(main())
```

**Expected output:**
```
FmMctpCciServer listening on port 52XXX

Step A: IDENTIFY_PBR_SWITCH (0x5700)
  [switch] received opcode=0x5700 payload_len=0
  Result: SUCCESS  tag=1

Step B: CONFIGURE_PID_ASSIGNMENT (0x5704) — assign PID 0x010 → port 0
  [switch] received opcode=0x5704 payload_len=N
  Result: SUCCESS

Step C: SET_DRT (0x5709) — DRT[0][0x010] = PhysicalPort 1
  [switch] received opcode=0x5709 payload_len=N
  Result: SUCCESS

Verification:
  Switch received 3 commands:
    0x5700  IDENTIFY_PBR_SWITCH
    0x5704  CONFIGURE_PID_ASSIGNMENT
    0x5709  SET_DRT

All assertions passed. E2E commissioning sequence complete.
```

---

*Generated from opencis-core `v0.5-dev` — May 2026*
