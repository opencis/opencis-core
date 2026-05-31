# GFD / GFA / GAE Team Explainer
### CXL 4.0 §§7.7.13–7.7.14 — opencis-core Implementation Deep-Dive

> **Audience**: Engineers working on the PBR switch, Fabric Manager, and device-side code in opencis-core.  
> **Goal**: Understand what a Generic Fabric Device (GFD) is, how a Generic Access Endpoint (GAE) proxies commands to it, how the Fabric Manager commissions the full pipeline, and exactly which code handles each step.

---

## Table of Contents

1. [Big Picture: Where GFD/GFA Fit in CXL 4.0](#1-big-picture)
2. [What Is a GFD? (§7.7.13)](#2-what-is-a-gfd)
3. [What Is GFA / GAE? (§7.7.14)](#3-what-is-gfa--gae)
4. [Architecture Overview Diagram](#4-architecture-overview-diagram)
5. [Component Summary Table](#5-component-summary-table)
6. [File-by-File Deep Dive](#6-file-by-file-deep-dive)
7. [DRT (DPID Routing Table) Explained](#7-drt-dpid-routing-table-explained)
8. [8-Step FM Commissioning Workflow](#8-8-step-fm-commissioning-workflow)
9. [Control Plane vs. Data Plane](#9-control-plane-vs-data-plane)
10. [GAE Opcode Reference](#10-gae-opcode-reference)
11. [Key Invariants and Common Pitfalls](#11-key-invariants-and-common-pitfalls)

---

## 1. Big Picture

CXL 3.x introduced **Port-Based Routing (PBR)** as an alternative to the traditional Bus/Device/Function (BDF) routing used in HBR (Host-Bridge Routing) fabrics. PBR allows a CXL switch to route packets purely by a 12-bit **Port Identifier (PID)**, enabling flexible fabric topologies not possible with BDF hierarchies.

A **Generic Fabric Device (GFD)** is the simplest thing that can attach to a PBR switch DSP port:

- It has **no CXL.mem** capability (no HDM decoder, no device memory).
- It exposes a single **4 KB MMIO BAR-0** reachable over CXL.io.
- The Fabric Manager (FM) assigns it a PID and programs the switch's DRT so host TLPs reach the device.

The **Generic Fabric Attach (GFA)** capability is what makes a device "PID-addressable". The corresponding endpoint visible on the host side is the **Generic Access Endpoint (GAE)**, which lives on the PBR switch's Host-Edge USP and can proxy CCI management commands to attached GFDs.

```
   Host CPU
      │ PCIe/CXL.io TLP (BDF-addressed, HBR fabric)
      │
  ┌───┴─────────────────────────────────────────────────────┐
  │           PBR Switch                                     │
  │                                                          │
  │  USP (GAE) ──── PBR Fabric (DRT lookup by DPID) ──── DSP│───► GFD
  │      │                                                   │
  │  PBR Mgmt CCI (5800h–580Bh)                             │
  └──────────────────────────────────────────────────────────┘
      │
    FM/Host
```

---

## 2. What Is a GFD? (§7.7.13)

### 2.1 Spec Definition

A **Generic Fabric Device** (CXL 4.0 §7.7.13) is a CXL device that:

| Property | Value |
|---|---|
| Attachment | PBR switch DSP port |
| Routing | By PID (12-bit), **not** by BDF |
| Protocol | CXL.io **only** |
| BAR | BAR-0 — 4 KB MMIO register block |
| CXL.mem | ❌ None |
| HDM Decoder | ❌ None |
| CCI Identify `component_type` | `0x04` (GFD) |
| Config space `cache_capable` | `0` |
| Config space `mem_capable` | `0` |
| PCI Class Code | `MEMORY_CONTROLLER` (0x05) |

### 2.2 Why PID Instead of BDF?

In an HBR fabric, every device is reachable via the root complex's address decoder and Bus/Device/Function numbering. This is fine for a tree topology but does not scale to large fabric meshes. PBR decouples routing from the PCI hierarchy: the switch maintains a flat DRT table mapping each 12-bit DPID to an egress port. The host can reach any GFD regardless of the PCI bus hierarchy by sending TLPs wrapped in a PBR header with the correct DPID.

### 2.3 What the GFD Exposes

```
GFD BAR-0 (4 KB)
┌─────────────────────────┐  0x0000
│  Scratchpad Register    │
├─────────────────────────┤  0x0004
│  Status Register        │
├─────────────────────────┤  0x0008
│  Control Register       │
├─────────────────────────┤  0x000C
│  (reserved / future)    │
└─────────────────────────┘  0x1000
```

The host reads/writes these registers using normal PCIe Memory Read/Write TLPs via the PBR fabric. No CXL.mem protocol involved.

---

## 3. What Is GFA / GAE? (§7.7.14)

### 3.1 GFA — Generic Fabric Attach (capability)

**GFA** is the *capability* of a device to be addressable in a PBR fabric. When a device advertises GFA support it is saying: "An FM can assign me a PID and route TLPs to me through the DRT."

A GFD by definition has GFA capability — that is the whole point.

### 3.2 GAE — Generic Access Endpoint (management interface)

**GAE** is the management endpoint that lives on the **Host-Edge USP** of the PBR switch. It appears to the host like a normal CCI-speaking device but provides special commands (opcode space 0x5800–0x580B) that let the host/FM:

1. Query what GFDs are attached to the switch.
2. **Proxy** CCI commands through the switch to a specific GFD — without the FM needing a direct FM-to-GFD MCTP connection.

This is the key value of GAE: the FM reaches GFDs **indirectly** through the switch's GAE using opcode `0x5809` (Proxy GFD Mgmt Cmd).

### 3.3 GAE CCI Opcodes

| Opcode | Name | Description |
|---|---|---|
| `0x5800` | Identify GAE | Returns GAE capabilities: vPPB count, GFA support map |
| `0x5801` | Get PID Interrupt Vec | PID interrupt vectors (optional) |
| `0x5802` | Get PID Access Vecs | PID access vector table |
| `0x5803` | Get FAST/IDT Caps | Returns UNSUPPORTED in basic GFD scenario |
| `0x5809` | **Proxy GFD Mgmt Cmd** | Forward any CCI opcode to the GFD; returns thread_id |
| `0x580A` | **Get Proxy Thread Status** | Poll completion of a proxied command |
| `0x580B` | **Cancel Proxy Thread** | Cancel an in-flight proxied command |

> **Important**: The proxy mechanism is **asynchronous**. The host issues `0x5809` and gets back `BACKGROUND_COMMAND_STARTED` with a `thread_id`. It then polls `0x580A` until the GFD response is ready.

---

## 4. Architecture Overview Diagram

```
┌────────────────────────────────────────────────────────────────────┐
│                         Host / FM                                  │
│                                                                    │
│  FM CLI / Test Harness                                             │
│    │                                                               │
│    ├─ MCTP CCI (port 8100/8200/8300) ───► Switch GAE CCI          │
│    │    0x5700  IdentifyPbrSwitch                                  │
│    │    0x5704  ConfigurePidAssignment                             │
│    │    0x5705  GetPidBinding                                      │
│    │    0x5706  ConfigurePidBinding                                │
│    │    0x5709  SetDrt                                             │
│    │    0x5809  Proxy GFD Mgmt Cmd ──► GFD CciExecutor            │
│    │                                                               │
│    └─ CXL.io TLP (port 8000) ──────► PbrSwitchRouter              │
│         MMIO Read/Write to BAR-0        (DRT lookup → DSP port)   │
└────────────────────────────────────────────────────────────────────┘
                                │
                    ┌───────────┴───────────────────┐
                    │        PBR Switch               │
                    │                                 │
                    │  PbrSwitchManager               │
                    │  ├─ DRT tables (4096 entries)   │
                    │  ├─ PID assignments              │
                    │  └─ PID bindings                │
                    │                                 │
                    │  PbrSwitchRouter                │
                    │  └─ _route_packet()             │
                    │     DPID → DRT → egress port    │
                    │                                 │
                    │  GaeManager (on USP/GAE)        │
                    │  ├─ set_gfd_executor()          │
                    │  └─ start_proxy() → thread_id  │
                    └───────────┬─────────────────────┘
                                │ TCP port 8000
                    ┌───────────┴─────────────────────┐
                    │         GFD (Device side)        │
                    │                                  │
                    │  GenericFabricDevice             │
                    │  └─ CxlGfdDevice                │
                    │     ├─ GfdMmioRegisters (BAR-0) │
                    │     ├─ CxlIoManager             │
                    │     ├─ CxlMemManager (stub)     │
                    │     └─ CciExecutor              │
                    │        └─ IdentifyCommand(GFD)  │
                    └──────────────────────────────────┘
```

---

## 5. Component Summary Table

| Component | File | Layer | Purpose |
|---|---|---|---|
| `GenericFabricDevice` | [generic_fabric_device.py](file:///c:/Users/pavan/Desktop/cxl/opencis-core/opencis/apps/generic_fabric_device.py) | App | Runnable wrapper: TCP connect + device lifecycle |
| `CxlGfdDevice` | [cxl_gfd_device.py](file:///c:/Users/pavan/Desktop/cxl/opencis-core/opencis/cxl/device/cxl_gfd_device.py) | Device Core | MMIO registers, CCI, config space, GFD identity |
| `SwitchConnectionClient` | [switch_connection_client.py](file:///c:/Users/pavan/Desktop/cxl/opencis-core/opencis/cxl/component/switch_connection_client.py) | Transport | TCP handshake + sideband protocol to switch port 8000 |
| `PbrSwitchManager` | [pbr_switch_manager.py](file:///c:/Users/pavan/Desktop/cxl/opencis-core/opencis/cxl/component/pbr_switch_manager.py) | Control Plane | DRT tables, PID assignments, PID bindings — all switch state |
| `PbrSwitchRouter` | [pbr_switch_router.py](file:///c:/Users/pavan/Desktop/cxl/opencis-core/opencis/cxl/component/pbr_switch_router.py) | Data Plane | TLP routing: DRT lookup, HBR→PBR encapsulation |
| `GaeManager` | [gae_manager.py](file:///c:/Users/pavan/Desktop/cxl/opencis-core/opencis/cxl/component/gae_manager.py) | Control Plane | GAE: proxy CCI commands to GFD, manage proxy threads |

---

## 6. File-by-File Deep Dive

---

### 6.1 `generic_fabric_device.py`

**File**: [generic_fabric_device.py](file:///c:/Users/pavan/Desktop/cxl/opencis-core/opencis/apps/generic_fabric_device.py)  
**Layer**: Application wrapper (entry point)  
**Spec**: §7.7.13 (GFD lifecycle)

This is the top-level "runnable" that you instantiate to launch a GFD process. It stitches together the TCP transport and the core device logic.

#### `GenericFabricDevice.__init__()`

```python
gfd = GenericFabricDevice(
    host="127.0.0.1",
    port=8000,
    port_index=1,           # which DSP port on the switch
    serial_number="0000000000000001",
)
```

What it does:
1. Creates a `SwitchConnectionClient` (unless in test mode) to open the TCP connection to the switch.
2. Creates a `CxlGfdDevice` backed by the `CxlConnection` obtained from the client.
3. In **test mode**, accepts a pre-built `CxlConnection` directly — no TCP socket needed. This is how unit tests inject mock FIFO pairs.

The `CXL_COMPONENT_TYPE.D2` constant passed to `SwitchConnectionClient` tells the switch sideband handshake that this is a generic downstream device.

#### `GenericFabricDevice._run()` — Lifecycle

```python
async def _run(self):
    run_tasks  = [create_task(self._gfd_device.run())]
    wait_tasks = [create_task(self._gfd_device.wait_for_ready())]

    if not self._test_mode:
        run_tasks.append(create_task(self._sw_conn_client.run()))
        wait_tasks.append(create_task(self._sw_conn_client.wait_for_ready()))

    await gather(*wait_tasks)               # wait until both are READY
    await self._change_status_to_running()  # signal parent
    await gather(*run_tasks)                # run until stopped
```

**Why it matters**: The `wait_for_ready()` barrier ensures the TCP connection is established and the device MMIO/CCI stacks are initialized before the GFD is declared "running". This prevents race conditions where the FM tries to enumerate the device before it is ready.

#### `GenericFabricDevice._stop()`

Gracefully tears down both the device and the TCP client concurrently. The `gather()` pattern ensures neither is left dangling.

#### `GenericFabricDevice.get_gfd_device()`

Returns the `CxlGfdDevice` instance. Primarily used in tests to introspect register state or inject the executor into a `GaeManager`.

---

### 6.2 `cxl_gfd_device.py`

**File**: [cxl_gfd_device.py](file:///c:/Users/pavan/Desktop/cxl/opencis-core/opencis/cxl/device/cxl_gfd_device.py)  
**Layer**: Device core  
**Spec**: §7.7.13 (GFD device requirements)

This is the heart of the GFD. It configures:
- PCI identity and class code
- BAR-0 MMIO register block
- CXL DVSEC config space (with `mem_capable=0`, `cache_capable=0`)
- CCI `IdentifyCommand` with `component_type=GFD`

#### `CxlGfdDevice.__init__()`

The constructor follows a strict ordering discipline:

```
GfdMmioRegisters  ← created FIRST
CciExecutor       ← created SECOND
CxlIoManager      ← calls _init_device() synchronously in __init__
CxlMemManager     ← idle stub (no CXL.mem)
```

> ⚠️ **Ordering matters**: `CxlIoManager` calls `_init_device()` synchronously during `__init__`. Anything referenced by `_init_device()` (the registers, the CCI executor) must exist before `CxlIoManager` is constructed.

#### `CxlGfdDevice._init_device()` — The Config Callback

This is called by `CxlIoManager` and does the full device initialization:

**Step 1 — PCI Identity**
```python
pci_identity = PciComponentIdentity(
    vendor_id=EEUM_VID,
    device_id=SW_GFD_DID,
    base_class_code=PCI_CLASS.MEMORY_CONTROLLER,  # per §7.7.13
    device_port_type=PCI_DEVICE_PORT_TYPE.PCI_EXPRESS_ENDPOINT,
)
```
`PCI_CLASS.MEMORY_CONTROLLER` is the spec-mandated class code for GFD. It distinguishes GFDs from normal Type-3 memory devices in enumeration.

**Step 2 — BAR-0 Registration**
```python
cxl_io_callback_data.mmio_manager.set_bar_entries([
    BarEntry(
        register=self._gfd_registers,
        info=BarInfo(prefetchable=False, memory_type=MEMORY_TYPE.ADDRESS_64BIT),
    )
])
```
The 4 KB `GfdMmioRegisters` block is mapped as BAR-0. The host sees this during config-space probing and maps it into its MMIO address space.

**Step 3 — Memory-Device Stub**
```python
_stub_mem_component = CxlMemoryDeviceComponent(
    _gfd_identity,
    decoder_count=HDM_DECODER_COUNT.DECODER_1,
    memory_file="",     # empty → no backing file
)
```
The DVSEC `CxlType3SldConfigSpace` requires a non-None `memory_device_component` even for `mem_capable=0` devices. We create a zero-capacity stub to satisfy this structural requirement without allocating real memory.

**Step 4 — CXL DVSEC Config Space (IO-only)**
```python
capability_options=DvsecCxlCapabilityOptions(
    cache_capable=0,
    mem_capable=0,
    hdm_count=0,
    cache_writeback_and_invalidate_capable=0,
    cache_size_unit=0,
    cache_size=0,
),
```
All capability bits are zero. This tells the enumerating host that the device does not participate in CXL.cache or CXL.mem protocols.

**Step 5 — CCI Identify (marks device as GFD)**
```python
identity = IdentifyResponsePayload(
    ...
    component_type=IdentifyComponentType.GFD,   # 0x04
)
self._cci_executor.register_command(
    IdentifyCommand.OPCODE,
    IdentifyCommand(identity, label=self._label),
)
```
When the FM sends a CCI `Identify` command (opcode `0x0001`), the response will contain `component_type=0x04`. This is how the FM distinguishes a GFD from a Type-3 memory device or a switch component.

#### `CxlGfdDevice.get_bar_size()` / `get_registers()`

Simple accessors used in tests:
- `get_bar_size()` returns `GFD_BAR_SIZE` (4096 bytes).
- `get_registers()` returns the live `GfdMmioRegisters` object — useful for verifying register values after a test write.

#### `CxlGfdDevice._run()` / `_stop()`

Runs three coroutines concurrently:

| Coroutine | Purpose |
|---|---|
| `_cxl_io_manager.run()` | Processes MMIO reads/writes and config-space accesses |
| `_cxl_mem_manager.run()` | Stub — handles (and ignores) any errant CXL.mem traffic |
| `_cci_executor.run()` | Dispatches inbound CCI commands to registered handlers |

---

### 6.3 `switch_connection_client.py`

**File**: [switch_connection_client.py](file:///c:/Users/pavan/Desktop/cxl/opencis-core/opencis/cxl/component/switch_connection_client.py)  
**Layer**: Transport  
**Spec**: §7.7.13 (device-to-switch connection)

#### `SwitchConnectionClient.__init__()`

Creates the `CxlConnection` object that holds the FIFO pairs (mmio_fifo, cfg_fifo, cxl_mem_fifo) used by `CxlGfdDevice`. The `CxlConnection` is created regardless of whether the TCP connection succeeds — it is a pure in-memory structure.

#### `SwitchConnectionClient._connect()` — TCP + Sideband Handshake

```
GFD Client                         Switch Server
    │                                   │
    │──SidebandConnectionRequestPacket──►│  (includes port_index)
    │                                   │
    │◄──SidebandConnectionAccept────────│
    │                                   │
    │         [CxlPacketProcessor running]
```

If the switch rejects the connection (wrong port_index, port already occupied), `_connect()` raises an exception and `_run()` retries until the 120-second timeout expires.

**Error injection**: `inject_error()` allows tests to send malformed sideband packets to test the switch's rejection logic.

#### `SwitchConnectionClient._run()` — Retry Loop

```python
while True:
    try:
        (reader, writer) = await self._connect()
        break
    except Exception:
        if loop.time() >= end_time:
            raise  # 120s timeout
        await asyncio.sleep(1)  # retry every second
```

The 120-second retry window accommodates real deployments where the switch may not be ready when the GFD process starts.

#### `SwitchConnectionClient.get_cxl_connection()`

Returns the pre-created `CxlConnection`. Called by `GenericFabricDevice.__init__()` before `_run()`, so the FIFOs are available for `CxlGfdDevice` during construction — even before the TCP connection is established.

---

### 6.4 `pbr_switch_manager.py`

**File**: [pbr_switch_manager.py](file:///c:/Users/pavan/Desktop/cxl/opencis-core/opencis/cxl/component/pbr_switch_manager.py)  
**Layer**: Control Plane  
**Spec**: §7.7.13.4–7.7.13.9

The **central state owner** for the PBR switch. Holds all tables the FM programs and the data-plane router consults.

#### Data Structures

**`DrtEntryType`** (§7.7.13.9 Table 7-133)

| Value | Name | Meaning |
|---|---|---|
| `0b00` | `INVALID` | Drop the packet |
| `0b01` | `PHYSICAL_PORT` | Route to egress port number |
| `0b10` | `RGT_INDEX` | Route via Routing Group Table (multicast/group) |
| `0b11` | `RESERVED` | Invalid — causes `INVALID_INPUT` error |

**`DrtEntry`** — 2-byte wire format

```
 Byte 0              Byte 1
┌─────────────────┐┌─────────────────┐
│ reserved[7:2]   ││ routing_target  │
│ type[1:0]       ││ [7:0]           │
└─────────────────┘└─────────────────┘
```

**`DrtTable`** — 4096-entry array indexed by DPID. All entries start as `DrtEntryType.INVALID`.

**`PidBinding`** — maps `(vcs_id, vppb_id) → PidBinding(pid, hmat)`. The "last mile" association that tells the host fabric side which PID is visible through which virtual port.

#### `PbrSwitchManager.get_identify_info()` → `PbrSwitchInfo`

Returns switch capabilities for the FM's `IdentifyPbrSwitch` (opcode `0x5700`) call. `num_drts` is dynamically derived from `len(self._drt_tables)` to stay consistent with actual state.

#### `PbrSwitchManager.assign_pid(pid, target_id, instance_id)` — §7.7.13.5

Associates a 12-bit PID with a physical port. Key behaviors:
- Returns `INVALID_INPUT` if PID > 0xFFF.
- Returns `INVALID_INPUT` if `pid` is already assigned to a *different* target.
- Re-assigning the same PID to the same target is idempotent (returns `SUCCESS`).
- **Does NOT update DRT** — `set_drt()` must be called separately.

> 🔑 **Critical Invariant**: `assign_pid()` and `set_drt()` are decoupled. Assigning a PID records FM intent. Routing only works after the DRT entry is also written.

#### `PbrSwitchManager.clear_pid(pid, target_id, instance_id)` — §7.7.13.5

Removes a PID assignment. Returns `INVALID_INPUT` if the PID was never assigned. Clearing a PID does **not** automatically clear the DRT entry — clear DRT first to avoid routing stale traffic.

#### `PbrSwitchManager.get_drt(drt_index, start_entry, num_entries)` — §7.7.13.9

Returns a slice of a DRT table. Used by the FM (`GetDrt` CCI) and by `PbrSwitchRouter` per-packet. Returns `None` on invalid `drt_index` or out-of-range access.

#### `PbrSwitchManager.set_drt(drt_index, start_entry, entries)` — §7.7.13.9

Writes `DrtEntry` objects into the DRT. Validates that `drt_index` is valid, write range is within `[0, 4096)`, and no entry has `entry_type=RESERVED`.

#### `PbrSwitchManager.get_pid_binding()` / `configure_pid_binding()`

Manages the `(vcs_id, vppb_id) → PidBinding` map. `BIND` creates the binding; `UNBIND` removes it. `UNBIND` of a non-existent binding returns `INVALID_INPUT`.

---

### 6.5 `pbr_switch_router.py`

**File**: [pbr_switch_router.py](file:///c:/Users/pavan/Desktop/cxl/opencis-core/opencis/cxl/component/pbr_switch_router.py)  
**Layer**: Data Plane  
**Spec**: §7.7.13 (PBR packet forwarding)

The **data plane** — moves TLPs between ports using DRT state maintained by `PbrSwitchManager`.

#### `PbrSwitchRouter.__init__()`

```python
def __init__(
    self,
    switch_id: int,
    pbr_switch_manager: PbrSwitchManager,
    port_fifos: List[FifoPair],
    hdm_decoder_manager: Optional[PbrHdmDecoderManager] = None,
    port_types: Optional[List[bool]] = None,  # True = USP, False = DSP
):
```

- `port_fifos[i]` is the FIFO pair for port `i`. Each `FifoPair` has `host_to_target` and `target_to_host` queues.
- `port_types[i] = True` means port `i` is a USP (host-edge); `False` or `None` means DSP (device-edge).
- `hdm_decoder_manager` is only needed for HBR→PBR encapsulation — not required for a pure CXL.io GFD.

#### `PbrSwitchRouter._route_packet()` — The Core Routing Logic

```
Incoming packet
      │
      ├─ is_pbr() == True?
      │      │
      │      ▼
      │   Extract DPID from PBR header
      │   DRT lookup: manager.get_drt(0, dpid, 1)
      │      │
      │      ├─ None or entry_type != PHYSICAL_PORT → DROP
      │      │
      │      └─ egress_port = drt_entry.routing_target
      │         Decapsulate inner packet
      │         Put to port_fifos[egress_port].host_to_target
      │
      └─ is_pbr() == False (HBR packet)
             │
             ▼
          Extract address from CXL.mem or CXL.io packet
          HDM decoder: get_dpid(address) → DPID
          Encapsulate into PbrBasePacket
          Recurse → hits the PBR branch above
```

Key drop conditions: DRT lookup returns `None`, entry type not `PHYSICAL_PORT`, invalid egress port, no HDM decoder for HBR packets, cannot extract address.

#### `PbrSwitchRouter._run()` / `_stop()`

`_run()` starts one ingress-processing coroutine per port and gathers them.
`_stop()` enqueues `None` sentinels on all FIFOs to unblock `await fifo.*.get()` calls.

---

### 6.6 `gae_manager.py`

**File**: [gae_manager.py](file:///c:/Users/pavan/Desktop/cxl/opencis-core/opencis/cxl/component/gae_manager.py)  
**Layer**: Control Plane (GAE side)  
**Spec**: §7.7.14

Manages the GAE state: which GFD is connected and what proxy threads are active.

#### Two GFD-Binding Modes

| Mode | Method | When Used |
|---|---|---|
| **Tunnel** (production) | `set_gfd_tunnel(tunnel)` | Real switch with `DspCciTunnel` over `cci_fifo` |
| **Executor** (test) | `set_gfd_executor(executor)` | In-process unit tests with direct executor reference |

#### `GaeManager.set_gfd_tunnel(tunnel)` — Production Path

Called once a `DspCciTunnel` is started (after the GFD connects to its DSP port). Clears `_gfd_executor` — tunnel takes precedence.

#### `GaeManager.set_gfd_executor(executor)` — Test Path

Directly binds a `CciExecutor`. Used in tests:
```python
gae_manager.set_gfd_executor(gfd.get_gfd_device()._cci_executor)
```

#### `GaeManager.start_proxy(gfd_opcode, gfd_request_payload)` → `thread_id` — §7.7.14.10

Implements the asynchronous proxy mechanism for opcode `0x5809`:

```python
async def start_proxy(self, gfd_opcode, gfd_request_payload) -> int:
    tid = self._alloc_thread_id()
    entry = ProxyThreadEntry(thread_id=tid, gfd_opcode=gfd_opcode)
    self._proxy_threads[tid] = entry

    async def _run():
        req = CciRequest(opcode=gfd_opcode, payload=gfd_request_payload)
        if has_tunnel:
            resp = await self._gfd_tunnel.send_and_wait(req)
        else:
            resp = await self._gfd_executor.execute_command(req)
        entry.response = resp
        entry.completed = True

    entry.task = asyncio.create_task(_run())
    return tid
```

The host gets back `tid` immediately (with `BACKGROUND_COMMAND_STARTED`) then polls `get_proxy_status(tid)` until `entry.completed == True`.

#### `GaeManager.get_proxy_status(thread_id)` → `ProxyThreadEntry | None` — §7.7.14.11

Returns the `ProxyThreadEntry`. The CCI handler translates:
- `entry.completed == False` → `BACKGROUND_COMMAND_RUNNING`
- `entry.completed == True` → return `entry.response`
- `thread_id` not found → `INVALID_INPUT`

#### `GaeManager.cancel_proxy(thread_id)` — §7.7.14.12

Cancels in-flight async task via `entry.task.cancel()`. Idempotent if already completed. Removes entry from `_proxy_threads`.

#### `GaeManager.cleanup_completed_threads()`

Prunes completed entries from `_proxy_threads`. Call periodically from the CCI server to prevent unbounded growth.

---

## 7. DRT (DPID Routing Table) Explained

### 7.1 Table Structure

```
DRT[drt_index]          ← one of num_drts tables (usually just DRT[0])
  entries[0x000]        ← DrtEntry for DPID=0x000
  entries[0x001]        ← DrtEntry for DPID=0x001
  ...
  entries[0x010]        ← DrtEntry for DPID=0x010 (e.g., our GFD)
  ...
  entries[0xFFF]        ← DrtEntry for DPID=0xFFF
```

- **4096 entries** — one per possible 12-bit DPID value (2^12 = 4096).
- **Index IS the DPID** — `entries[dpid]` gives the routing for that DPID.
- **All INVALID at startup** — no routing until FM explicitly programs entries.

### 7.2 DrtEntry Wire Format (Table 7-133)

```
 Byte 0              Byte 1
┌─────────────────┐┌─────────────────┐
│ reserved[7:2]   ││ routing_target  │
│ type[1:0]       ││ [7:0]           │
└─────────────────┘└─────────────────┘
```

### 7.3 Example: GFD on Physical Port 1, PID=0x010

After FM commissioning, DRT[0][0x010] should contain:

```python
DrtEntry(entry_type=DrtEntryType.PHYSICAL_PORT, routing_target=1)
# Wire bytes: [0x01, 0x01]
```

When the router sees a PBR packet with DPID=0x010:
```
get_drt(0, 0x010, 1) → ([DrtEntry(PHYSICAL_PORT, 1)], rgt_index=0)
egress_port = 1
port_fifos[1].host_to_target.put(inner_packet)
```

### 7.4 assign_pid vs. set_drt — Critical Separation

```
FM calls ConfigurePidAssignment(pid=0x010, target=port1)
  └─► PbrSwitchManager.assign_pid(0x010, target_id=1, instance_id=0)
      Records: _pid_assignments[0x010] = PidAssignment(0x010, 1, 0)
      ⚠️  DRT is NOT updated. Router still drops DPID=0x010 packets.

FM calls SetDrt(drt_index=0, start_entry=0x010, entries=[DrtEntry(PHYSICAL_PORT,1)])
  └─► PbrSwitchManager.set_drt(0, 0x010, [...])
      Updates: _drt_tables[0].entries[0x010] = DrtEntry(PHYSICAL_PORT, 1)
      ✅  Router now routes DPID=0x010 to port 1.
```

These are two separate CCI commands by design: the FM may pre-assign PIDs before committing DRT entries for atomic topology changes.

---

## 8. 8-Step FM Commissioning Workflow

The following sequence commissions a GFD attached to DSP port 1 with PID=0x010.

```
FM                              PBR Switch (GAE/CCI)            GFD
│                                      │                          │
│── 1. IdentifyPbrSwitch (0x5700) ────►│                          │
│◄── PbrSwitchInfo{num_drts=1, ...} ───│                          │
│                                      │                          │
│── 2. ConfigurePidAssignment (0x5704)─►│                          │
│      pid=0x010, target=port1         │                          │
│◄── SUCCESS ──────────────────────────│ assign_pid(0x010, 1, 0)  │
│                                      │                          │
│── 3. SetDrt (0x5709) ───────────────►│                          │
│      DRT[0][0x010]=PHYSICAL_PORT→1  │ set_drt(0, 0x010, [...]) │
│◄── SUCCESS ──────────────────────────│                          │
│                                      │                          │
│── 4. GetPidBinding (0x5705) ─────── ►│                          │
│◄── PidBinding{pid=0xFFF} ────────── │ (verify: still unbound)  │
│                                      │                          │
│── 5. ConfigurePidBinding (0x5706) ──►│                          │
│      BIND, vcs_id=0, vppb_id=1,     │                          │
│      pid=0x010                       │ configure_pid_binding(   │
│◄── BACKGROUND_COMMAND_STARTED ───────│   BIND, 0, 1, 0x010)    │
│                                      │                          │
│── 6. GetPidBinding (0x5705) ─────── ►│                          │
│◄── PidBinding{pid=0x010} ────────── │ (verify: now bound ✅)    │
│                                      │                          │
│── 7. Host sends CXL.io TLP ─────────────────────────────────── ►│
│      DPID=0x010 → DRT lookup → port1                            │
│                                      │                          │
│── 8. (Optional) Proxy GFD CCI ──────►│                          │
│      0x5809 Proxy, opcode=0x0001     │──start_proxy(0x0001)───►│
│◄── thread_id=1 ──────────────────────│                          │
│── 0x580A GetProxyStatus(thread=1) ──►│                          │
│◄── {completed=True, response=...} ───│◄─ executor.execute() ────│
```

### Step-by-Step Summary

| Step | CCI Opcode | Manager Method | What Happens |
|---|---|---|---|
| 1 | `0x5700` | `get_identify_info()` | FM learns `num_drts`, routing capabilities |
| 2 | `0x5704` | `assign_pid()` | Records PID→target mapping; DRT unchanged |
| 3 | `0x5709` | `set_drt()` | Programs DRT entry; router can now forward packets |
| 4 | `0x5705` | `get_pid_binding()` | Verify vPPB not yet bound (pid=0xFFF expected) |
| 5 | `0x5706` | `configure_pid_binding(BIND)` | Stitches PID to host-side vPPB |
| 6 | `0x5705` | `get_pid_binding()` | Confirm binding succeeded (pid=0x010 expected) |
| 7 | N/A | `PbrSwitchRouter._route_packet()` | Data plane: TLP forwarded to GFD |
| 8 | `0x5809` | `gae_manager.start_proxy()` | FM-to-GFD CCI without direct FM-GFD connection |

---

## 9. Control Plane vs. Data Plane

### 9.1 Control Plane

```
Transport:    MCTP over CXL.io (sideband), ports 8100 / 8200 / 8300
Direction:    FM → Switch
Owner:        PbrSwitchManager
Key methods:  assign_pid(), clear_pid(), set_drt(), get_drt(),
              configure_pid_binding(), get_pid_binding()
              + GaeManager.start_proxy(), get_proxy_status(), cancel_proxy()
```

Control plane operations are synchronous from the FM perspective (except proxy commands which use the background-command pattern).

### 9.2 Data Plane

```
Transport:    CXL.io TLP (PBR-encapsulated), port 8000
Direction:    Host ↔ GFD (bidirectional)
Owner:        PbrSwitchRouter
Key methods:  _route_packet(), _process_port_ingress(),
              _process_port_host_ingress()
              + PbrSwitchManager.get_drt() (read-only, per packet)
```

The router calls `get_drt()` on every packet — no caching. DRT updates by the FM are immediately visible (asyncio cooperative scheduling ensures consistency without explicit locking in the Python simulator).

### 9.3 Interaction Between the Planes

```
Control Plane (FM)              Data Plane (Router)
       │                               │
       │  set_drt(0, 0x010, [...])     │
       ▼                               │
  _drt_tables[0].entries[0x010]        │
  = DrtEntry(PHYSICAL_PORT, 1)         │
                                       │  _route_packet(...)
                                       │  get_drt(0, 0x010, 1)
                                       ▼
                               drt_entry = entries[0x010]
                               egress_port = 1
                               → forward to port_fifos[1]
```

---

## 10. GAE Opcode Reference

| Opcode | Name | Spec Section | Request | Response | Notes |
|---|---|---|---|---|---|
| `0x5800` | Identify GAE | §7.7.14.1 | — | vPPB count, GFA support map | Read-only capabilities query |
| `0x5802` | Get PID Access Vecs | §7.7.14.3 | start_index, num_vecs | PID access vector list | Which PIDs are accessible |
| `0x5809` | **Proxy GFD Mgmt Cmd** | §7.7.14.10 | gfd_opcode, payload | `BACKGROUND_COMMAND_STARTED` + thread_id | Async; poll with 580Ah |
| `0x580A` | **Get Proxy Thread Status** | §7.7.14.11 | thread_id | `{completed, return_code, response}` | Poll until `completed=True` |
| `0x580B` | **Cancel Proxy Thread** | §7.7.14.12 | thread_id | SUCCESS / INVALID_INPUT | Idempotent if already done |

### GAE Proxy Flow Detail

```
Host                    Switch GAE CCI              GFD CciExecutor
  │                           │                           │
  │── 0x5809 ────────────────►│                           │
  │   {opcode=0x0001,         │  start_proxy(0x0001, ...)│
  │    payload=b""}           │  asyncio.create_task(_run)│
  │◄── BACKGROUND_COMMAND_    │                           │
  │    STARTED + thread_id=1  │                           │
  │                           │  [async] send CCI req ──►│
  │── 0x580A(thread=1) ──────►│                           │  (processing)
  │◄── {completed=False} ─────│                           │
  │                           │◄─── CCI response ─────────│
  │── 0x580A(thread=1) ──────►│  entry.completed=True     │
  │◄── {completed=True,       │                           │
  │     response=...} ────────│                           │
```

---

## 11. Key Invariants and Common Pitfalls

### 11.1 Invariants

> **I-1**: `assign_pid()` does NOT update the DRT. You must call `set_drt()` separately after assigning a PID. Until `set_drt()` is called, packets with that DPID are dropped by the router.

> **I-2**: All DRT entries start as `INVALID` (0b00). No routing happens until the FM explicitly programs them.

> **I-3**: `PID_UNASSIGNED = 0xFFF`. A `GetPidBinding` response with `pid=0xFFF` means the vPPB is not bound — expected state before Step 5 of commissioning.

> **I-4**: `component_type=0x04` in the CCI Identify response distinguishes a GFD from any other CXL device. The FM uses this to issue PBR CCI commands.

> **I-5**: The `CxlMemManager` in `CxlGfdDevice` is a stub. `mem_capable=0` means the switch will never send CXL.mem traffic to the GFD, but the stub absorbs errant packets gracefully.

### 11.2 Common Pitfalls

| Pitfall | Symptom | Fix |
|---|---|---|
| Calling `set_drt()` before `assign_pid()` | Works, but FM state is inconsistent | Always do assign_pid → set_drt in that order |
| Not calling `set_drt()` after `assign_pid()` | Packets silently dropped by router | Always call `set_drt()` with a `PHYSICAL_PORT` entry |
| `DrtEntry(RESERVED, ...)` in `set_drt()` payload | `INVALID_INPUT` return code | Use only `INVALID`, `PHYSICAL_PORT`, or `RGT_INDEX` |
| `GaeManager` with no executor/tunnel bound | `start_proxy` returns `thread_id=0` | Call `set_gfd_executor()` or `set_gfd_tunnel()` before first proxy command |
| Wrong `port_types[]` in `PbrSwitchRouter` | Packets read from wrong FIFO direction | `True` = USP (host-edge), `False` = DSP (device-edge) |
| Constructing `CxlIoManager` before `GfdMmioRegisters` | `AttributeError` in `_init_device()` | Registers and `CciExecutor` must be created before `CxlIoManager` |

### 11.3 Test Mode Pattern

When writing unit tests for GFD:

```python
conn = CxlConnection()   # in-memory FIFOs, no TCP
gfd = GenericFabricDevice(
    port_index=1,
    serial_number="DEADBEEF00000001",
    test_mode=True,
    cxl_connection=conn,
)

# Inject executor into GAE
gae = GaeManager()
gae.set_gfd_executor(gfd.get_gfd_device()._cci_executor)

# Run both concurrently
await gather(gfd.run(), your_test_coroutine())
```

This pattern avoids all network I/O while exercising the full CCI dispatch and MMIO register paths.

---

*Document generated: 2026-05-26 | opencis-core GFD/GFA implementation | CXL 4.0 §§7.7.13–7.7.14*
