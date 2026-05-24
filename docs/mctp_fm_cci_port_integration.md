# FM MCTP CCI Port — Integration Steps

**Document:** End-to-end integration guide for `FmMctpCciServer` (port 8300)
**Branch:** `v0.5-dev`
**Author:** CXL Architect

---

## Part 1 — What Is Already Done (Baseline)

Port 8300 is **live and tested**. Any MCTP client can connect and drive these
6 PBR CCI commands against the FM's own state machine:

```
0x5700  Identify PBR Switch
0x5704  Configure PID Assignment
0x5705  Get PID Binding
0x5706  Configure PID Binding
0x5708  Get DRT
0x5709  Set DRT
```

Start the FM and verify:
```bash
python run_pbr_env.py
# FM logs: "FM MCTP CCI server listening on 0.0.0.0:8300"

python -m pytest tests/test_mctp_fm_port.py -v
# 7 passed in ~10s
```

---

## Part 2 — Integration Steps: FM State ↔ Switch Programming

Currently, port 8300 updates **FM-side state only**. The switch's DRT/PID tables
are not automatically updated. This section describes the steps to close that gap.

### Step 1 — Inject `MctpCciApiClient` into `FmMctpCciServer`

**File:** `opencis/apps/fabric_manager.py`

After `MctpCciApiClient` is created and before `FmMctpCciServer` is built,
pass the client reference to the server:

```python
# existing
self._api_client = MctpCciApiClient(self._connection_manager.get_mctp_connection())

# NEW — pass api_client so FM can program the switch after local execution
self._fm_mctp_cci_server = FmMctpCciServer(
    host=mctp_host,
    port=fm_mctp_cci_port,
    cci_commands=pbr_commands,
    switch_api_client=self._api_client,   # ← inject here
)
```

**File:** `opencis/cxl/component/mctp/fm_mctp_cci_server.py`

Add `switch_api_client` parameter to `__init__`:

```python
def __init__(
    self,
    host: str = "0.0.0.0",
    port: int = 8300,
    cci_commands: Optional[List[CciCommand]] = None,
    switch_api_client=None,   # MctpCciApiClient | None
    label: Optional[str] = None,
):
    ...
    self._switch_api_client = switch_api_client
```

---

### Step 2 — Add Post-Execution Hook to Forward Commands to Switch

In `_process_client()`, after `execute_command()` returns SUCCESS, call the
switch API client to mirror the command:

```python
async def _process_client(self, conn: MctpConnection) -> None:
    while True:
        raw = await conn.controller_to_ep.get()
        if raw is None:
            break

        cci_msg = raw.get_cci_message()
        opcode  = cci_msg.cci_msg_header.command_opcode
        tag     = cci_msg.cci_msg_header.message_tag
        request = CciRequest(opcode=opcode, payload=cci_msg.get_payload())

        # 1. Execute locally on FM state
        response = await self._cci_executor.execute_command(request)

        # 2. If SUCCESS and switch client available, mirror to switch
        if (
            response.return_code == CCI_RETURN_CODE.SUCCESS
            and self._switch_api_client is not None
        ):
            await self._forward_to_switch(opcode, request.payload)

        # 3. Send MCTP response back to caller
        resp_msg = CciMessagePacket.create(
            message_category=CCI_MCTP_MESSAGE_CATEGORY.RESPONSE,
            opcode=opcode,
            data=response.payload or b"",
            message_tag=tag,
            return_code=int(response.return_code),
            background_operation=int(response.bo_flag),
            vendor_specific_extended_status=response.vendor_specific_status,
        )
        await conn.ep_to_controller.put(CciPayloadPacket.create(resp_msg))


async def _forward_to_switch(self, opcode: int, payload: bytes) -> None:
    """Mirror a successfully-executed FM command to the switch via port 8100."""
    from opencis.cxl.cci.common import CCI_FM_API_COMMAND_OPCODE
    try:
        if opcode == CCI_FM_API_COMMAND_OPCODE.SET_DRT:
            # Parse SetDrtRequestPayload and call switch API
            from opencis.cxl.cci.fabric_manager.pbr_switch import SetDrtRequestPayload
            req_payload = SetDrtRequestPayload.parse(payload)
            await self._switch_api_client.set_drt(req_payload)

        elif opcode == CCI_FM_API_COMMAND_OPCODE.CONFIGURE_PID_ASSIGNMENT:
            from opencis.cxl.cci.fabric_manager.pbr_switch import ConfigurePidAssignmentRequestPayload
            req_payload = ConfigurePidAssignmentRequestPayload.parse(payload)
            await self._switch_api_client.configure_pid_assignment(req_payload)

        elif opcode == CCI_FM_API_COMMAND_OPCODE.CONFIGURE_PID_BINDING:
            from opencis.cxl.cci.fabric_manager.pbr_switch import ConfigurePidBindingRequestPayload
            req_payload = ConfigurePidBindingRequestPayload.parse(payload)
            await self._switch_api_client.configure_pid_binding(req_payload)

        # Read-only commands (Identify, GetDRT, GetPidBinding) are NOT forwarded
        # — they only read FM state, no switch programming needed

    except Exception as exc:
        logger.warning(self._create_message(
            f"Failed to forward opcode {opcode:#06x} to switch: {exc}"
        ))
        # Non-fatal: FM state was already updated; log and continue
```

---

### Step 3 — Add Corresponding Methods to `MctpCciApiClient`

**File:** `opencis/cxl/component/mctp/mctp_cci_api_client.py`

Check which PBR switch methods already exist. Likely `set_drt` and
`configure_pid_assignment` are already there (used by the Socket.IO server).
If not, add them following the existing `_send_cci_command` pattern:

```python
async def set_drt(self, payload: SetDrtRequestPayload) -> tuple:
    """Send SET_DRT (0x5709) to the switch."""
    request = SetDrtCommand.create_cci_request(payload)
    return await self._send_cci_command(request)

async def configure_pid_assignment(self, payload) -> tuple:
    """Send CONFIGURE_PID_ASSIGNMENT (0x5704) to the switch."""
    request = ConfigurePidAssignmentCommand.create_cci_request(payload)
    return await self._send_cci_command(request)
```

---

### Step 4 — Handle Switch Not Connected (Graceful Degradation)

When `run_pbr_env.py` is not running or the switch has not yet connected on
port 8100, `self._switch_api_client` will have no live connection. The FM
must degrade gracefully — update its own state but skip switch programming:

```python
async def _forward_to_switch(self, opcode, payload) -> None:
    if not self._switch_api_client.is_connected():
        logger.warning(self._create_message(
            "Switch not connected; skipping switch programming for "
            f"opcode {opcode:#06x}. FM state updated."
        ))
        return
    # ... forward as above
```

Add `is_connected()` to `MctpCciApiClient`:
```python
def is_connected(self) -> bool:
    return self._mctp_connection is not None and self._running
```

---

### Step 5 — Add Integration Test

**File:** `tests/test_mctp_fm_port_integration.py`

This test starts the **full** `CxlFabricManager` (not just `FmMctpCciServer`),
connects a mock switch on port 8100, then sends commands to port 8300 and
verifies both the FM state AND the switch state are updated:

```python
@pytest_asyncio.fixture(loop_scope="function")
async def full_fm():
    """Start full CxlFabricManager with mock switch."""
    from opencis.apps.fabric_manager import CxlFabricManager
    fm = CxlFabricManager(
        mctp_port=0,            # ephemeral
        socketio_port=0,        # ephemeral
        host_fm_conn_port=0,    # ephemeral
        fm_mctp_cci_port=0,     # ephemeral
    )
    fm_task = asyncio.create_task(fm.run())
    await fm.wait_for_ready()
    yield fm
    await fm.stop()
    try:
        await asyncio.wait_for(fm_task, timeout=5.0)
    except Exception:
        pass


@pytest.mark.asyncio
async def test_set_drt_programs_both_fm_and_switch(full_fm):
    """
    Send SET_DRT to port 8300.
    Verify:
      1. FM PbrSwitchManager DRT is updated
      2. Switch receives SET_DRT via port 8100
    """
    port = full_fm.get_fm_mctp_cci_port()
    client = MctpCciTestClient("127.0.0.1", port)
    await client.connect()

    entries = [DrtEntry(DrtEntryType.PHYSICAL_PORT, routing_target=1)]
    req = SetDrtCommand.create_cci_request(
        SetDrtRequestPayload(drt_index=0, start_entry=0x042, entries=entries)
    )
    response = await asyncio.wait_for(client.send_command(req), timeout=5.0)
    assert response.cci_msg_header.return_code == CCI_RETURN_CODE.SUCCESS

    # Verify FM state
    fm_drt = full_fm._fm_mctp_cci_server._fm_pbr_manager.get_drt_entry(0, 0x042)
    assert fm_drt.entry_type == DrtEntryType.PHYSICAL_PORT
    assert fm_drt.routing_target == 1

    # Verify switch received the command (check mock switch's DRT)
    # ... (requires mock switch fixture)

    await client.close()
```

---

## Part 3 — Integration with Existing FM CLI (Port 8200)

Currently port 8200 (Socket.IO) sends CCI commands to the **switch** via
`MctpCciApiClient`. Port 8300 updates **FM state only**. For a unified
state view, both paths should write to the same `PbrSwitchManager`:

### Option A — Shared PbrSwitchManager (Recommended)

Pass the same `PbrSwitchManager` instance to both:
- `FmMctpCciServer` (port 8300) — for direct MCTP CCI
- `FabricManagerSocketIoServer` (port 8200) — for CLI commands

```python
# In CxlFabricManager.__init__:
self._fm_pbr_manager = PbrSwitchManager(...)   # one shared instance

# Port 8300: executes CCI locally against fm_pbr_manager
self._fm_mctp_cci_server = FmMctpCciServer(
    cci_commands=make_pbr_commands(self._fm_pbr_manager),
    ...
)

# Port 8200: reads fm_pbr_manager state for CLI display
self._socketio_server = FabricManagerSocketIoServer(
    ..., pbr_manager=self._fm_pbr_manager
)
```

### Option B — Event Bus (Loose Coupling)

Both ports publish state changes to an `asyncio.Queue`. A reconciler
component reads from the queue and syncs both FM state and switch state.
More complex but more flexible for future extensions.

---

## Part 4 — Connecting a Real MCTP Hardware Client

### 4.1 Required Wire Format

The client must send standard `CciPayloadPacket` bytes:

```python
# Python example — sending from any script/tool
import asyncio, struct

HOST = "192.168.1.10"   # FM IP
PORT = 8300

async def send_identify():
    reader, writer = await asyncio.open_connection(HOST, PORT)

    # Build raw MCTP packet for IDENTIFY_PBR_SWITCH (0x5700)
    # SystemHeader (2B) + CciHeader (2B) + CciMessagePacket (12B) = 16B
    pkt = bytes([
        0x04, 0x10,   # SystemHeader: type=CCI_MCTP(4), length=16
        0x00, 0x01,   # CciHeader: port=0, class=REQ(1)
        0x00, 0x00,   # CciMsgHeader: category=REQUEST(0), ...
        0x00, 0x57,   # opcode = 0x5700 (little-endian)
        0x00, 0x00,   # message_tag=0, padding
        0x00, 0x00,   # return_code=0
        0x00, 0x00,   # vendor_specific=0
        0x00, 0x00,   # payload_length=0
    ])

    writer.write(pkt)
    await writer.drain()

    # Read response
    hdr = await reader.readexactly(2)
    payload_length = ((hdr[1] & 0xFF) << 4) | (hdr[0] >> 4)  # 12-bit field
    body = await reader.readexactly(payload_length - 2)
    print("Response:", (hdr + body).hex())

asyncio.run(send_identify())
```

### 4.2 Using the Built-in Test Client Class

Copy `MctpCciTestClient` from `tests/test_mctp_fm_port.py` — it handles
all framing automatically and can be used as a standalone library.

### 4.3 FPGA / Hardware MCTP Controller

For hardware MCTP controllers, ensure:
- The controller uses **TCP transport** (not PCIe VDM or SMBus)
- The MCTP binding follows the same 2-byte `SystemHeader` framing
- `payload_length` in the header = total packet byte count (inclusive)
- `payload_type` = 4 (`CCI_MCTP`)

---

## Part 5 — Configuring Port Number

Default is `8300`. To change:

### In `run_pbr_env.py`

```python
fm = CxlFabricManager(
    ...
    fm_mctp_cci_port=9000,   # custom port
)
```

### In a test

```python
server = FmMctpCciServer(host="0.0.0.0", port=0)  # port=0 → OS picks
await server.wait_for_ready()
actual_port = server.get_port()
```

### Via environment variable (recommended addition)

```python
import os
FM_MCTP_CCI_PORT = int(os.getenv("FM_MCTP_CCI_PORT", "8300"))
```

---

## Part 6 — Security Considerations

| Concern | Current State | Recommendation |
|---------|--------------|----------------|
| Authentication | None (simulation env) | Add HMAC token header for production |
| Authorisation | All clients equal | Add per-client role checking |
| Bind address | `0.0.0.0` (all interfaces) | Restrict to `127.0.0.1` for loopback-only |
| DoS | No rate limiting | Add per-IP connection limit |
| TLS | Plain TCP | Wrap with `ssl.create_default_context()` |

To restrict to loopback only immediately:
```python
# In CxlFabricManager.__init__:
self._fm_mctp_cci_server = FmMctpCciServer(
    host="127.0.0.1",   # loopback only
    port=fm_mctp_cci_port,
    cci_commands=pbr_commands,
)
```

---

## Part 7 — Quick Verification Checklist

After running `python run_pbr_env.py`:

```bash
# 1. Confirm port is open
netstat -an | findstr "8300"
# Expected: TCP  0.0.0.0:8300  LISTENING

# 2. Run unit tests (no FM needed)
python -m pytest tests/test_mctp_fm_port.py -v
# Expected: 7 passed

# 3. Run existing PBR tests (regression check)
python -m pytest tests/test_pbr_switch_command_set.py -v
python -m pytest tests/test_pbr_data_plane.py -v

# 4. Manual smoke test (Python one-liner)
python -c "
import asyncio
from tests.test_mctp_fm_port import MctpCciTestClient
from opencis.cxl.cci.fabric_manager.pbr_switch import IdentifyPbrSwitchCommand
from opencis.cxl.cci.common import CCI_RETURN_CODE

async def main():
    c = MctpCciTestClient('127.0.0.1', 8300)
    await c.connect()
    r = await c.send_command(IdentifyPbrSwitchCommand.create_cci_request())
    print('RC:', CCI_RETURN_CODE(r.cci_msg_header.return_code).name)
    await c.close()

asyncio.run(main())
"
# Expected: RC: SUCCESS
```

---

## Summary of All Integration Steps

```
Phase 1 — DONE ✅
  [x] FmMctpCciServer implemented (fm_mctp_cci_server.py)
  [x] Wired into CxlFabricManager (fabric_manager.py)
  [x] 7 unit tests passing (test_mctp_fm_port.py)
  [x] Design doc written (docs/mctp_fm_cci_port_design.md)
  [x] Integration doc written (docs/mctp_fm_cci_port_integration.md)

Phase 2 — Switch Programming (Next)
  [ ] Inject MctpCciApiClient into FmMctpCciServer
  [ ] Implement _forward_to_switch() for write commands
  [ ] Add is_connected() to MctpCciApiClient
  [ ] Write integration test with full FM + mock switch

Phase 3 — Unified State (Future)
  [ ] Share PbrSwitchManager between port 8300 and port 8200
  [ ] CLI (port 8200) reflects commands sent via MCTP (port 8300)

Phase 4 — Production Hardening (Future)
  [ ] Bind address configuration via env var
  [ ] Authentication token header
  [ ] Rate limiting per client IP
  [ ] TLS support
```
