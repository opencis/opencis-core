# GFD / PBR — Sequence Diagrams

**Project:** opencis-core CXL 4.0 PBR Simulator  
**Spec:** CXL 4.0 Rev 1.0 §7.7.13  
**Date:** May 2026

---

## 1. GFD Commissioning — 8-Step FM Workflow

The Fabric Manager executes this sequence to bring a GFD into a fully routed state.

```mermaid
sequenceDiagram
    autonumber
    participant FM as Fabric Manager<br/>(MctpCciApiClient)
    participant MGR as MctpConnectionManager<br/>(FM TCP Server :0)
    participant CLI as MctpConnectionClient<br/>(Switch TCP Client)
    participant EXE as MctpCciExecutor<br/>(Switch CCI Dispatcher)
    participant PBR as PbrSwitchManager<br/>(State Machine)

    Note over FM,PBR: ── Step 1: Discover switch capabilities ──
    FM->>MGR: identify_pbr_switch()
    MGR->>CLI: MCTP CCI Request [opcode=0x5700] over TCP
    CLI->>EXE: forward to cci_executor
    EXE->>PBR: get_identify_info()
    PBR-->>EXE: PbrSwitchInfo{num_drts=1, num_rgts=0}
    EXE-->>CLI: MCTP CCI Response [SUCCESS]
    CLI-->>MGR: response bytes over TCP
    MGR-->>FM: IdentifyPbrSwitchResponsePayload
    Note right of FM: num_drts=1 ✓<br/>Can now program DRT[0]

    Note over FM,PBR: ── Step 2: Assign PID to GFD port ──
    FM->>MGR: configure_pid_assignment(pid=0x010, target_id=1)
    MGR->>EXE: MCTP CCI Request [opcode=0x5704]
    EXE->>PBR: assign_pid(0x010, target_id=1, instance_id=0)
    Note right of PBR: _pid_assignments[0x010] = PidAssignment(pid=0x010, target=1)
    PBR-->>EXE: CCI_RETURN_CODE.SUCCESS
    EXE-->>MGR: MCTP CCI Response [SUCCESS]
    MGR-->>FM: (SUCCESS, None)

    Note over FM,PBR: ── Step 3: Program DRT routing entry ──
    FM->>MGR: set_drt(drt_index=0, start=0x010, entries=[DrtEntry(PHYSICAL_PORT, 1)])
    MGR->>EXE: MCTP CCI Request [opcode=0x5709]
    EXE->>PBR: set_drt(0, 0x010, [DrtEntry(PHYSICAL_PORT, 1)])
    Note right of PBR: _drt_tables[0].entries[0x010] = DrtEntry(PHYSICAL_PORT, 1)
    PBR-->>EXE: CCI_RETURN_CODE.SUCCESS
    EXE-->>MGR: MCTP CCI Response [SUCCESS]
    MGR-->>FM: (SUCCESS, None)

    Note over FM,PBR: ── Step 4: Verify DRT entry ──
    FM->>MGR: get_drt(drt_index=0, start=0x010, num_entries=1)
    MGR->>EXE: MCTP CCI Request [opcode=0x5708]
    EXE->>PBR: get_drt(0, 0x010, 1)
    PBR-->>EXE: ([DrtEntry(PHYSICAL_PORT, 1)], rgt_index=0)
    EXE-->>MGR: MCTP CCI Response [SUCCESS + payload]
    MGR-->>FM: GetDrtResponsePayload{entries=[DrtEntry(PHYSICAL_PORT,1)]}
    Note right of FM: DRT verified ✓

    Note over FM,PBR: ── Step 5: Check binding (pre-bind) ──
    FM->>MGR: get_pid_binding(target_vcs=0, target_vppb=0)
    MGR->>EXE: MCTP CCI Request [opcode=0x5705]
    EXE->>PBR: get_pid_binding(vcs_id=0, vppb_id=0)
    PBR-->>EXE: None (no binding exists yet)
    EXE-->>MGR: Response{pid=0xFFF}
    MGR-->>FM: GetPidBindingResponsePayload{pid=0xFFF}
    Note right of FM: 0xFFF = PID_UNASSIGNED ✓<br/>Slot is free for binding

    Note over FM,PBR: ── Step 6: Bind PID to VCS/vPPB slot ──
    FM->>MGR: configure_pid_binding(BIND, vcs=0, vppb=0, pid=0x010)
    MGR->>EXE: MCTP CCI Request [opcode=0x5706]
    EXE->>PBR: configure_pid_binding(BIND, 0, 0, 0x010, HmatInfo())
    Note right of PBR: _pid_bindings[(0,0)] = PidBinding(pid=0x010)
    PBR-->>EXE: CCI_RETURN_CODE.SUCCESS
    EXE-->>MGR: CCI Response [BACKGROUND_COMMAND_STARTED]
    MGR-->>FM: (BACKGROUND_COMMAND_STARTED, None)
    Note right of FM: Background command accepted ✓<br/>Poll for completion

    Note over FM,PBR: ── Step 7: Verify binding (post-bind) ──
    FM->>MGR: get_pid_binding(target_vcs=0, target_vppb=0)
    MGR->>EXE: MCTP CCI Request [opcode=0x5705]
    EXE->>PBR: get_pid_binding(vcs_id=0, vppb_id=0)
    PBR-->>EXE: PidBinding{pid=0x010, hmat=HmatInfo()}
    EXE-->>MGR: Response{pid=0x010}
    MGR-->>FM: GetPidBindingResponsePayload{pid=0x010}
    Note right of FM: pid=0x010 ≠ 0xFFF → Bound ✓

    Note over FM,PBR: ── Step 8: (Optional) Clear PID assignment ──
    FM->>MGR: configure_pid_assignment(CLEAR, pid=0x010, target_id=1)
    MGR->>EXE: MCTP CCI Request [opcode=0x5704, op=1]
    EXE->>PBR: clear_pid(0x010, 1, 0)
    Note right of PBR: del _pid_assignments[0x010]
    PBR-->>EXE: CCI_RETURN_CODE.SUCCESS
    EXE-->>MGR: MCTP CCI Response [SUCCESS]
    MGR-->>FM: (SUCCESS, None)
```

---

## 2. Data Plane Packet Routing

How a TLP from the Host CPU reaches the GFD via PBR fabric routing.

```mermaid
sequenceDiagram
    autonumber
    participant HOST as Host CPU<br/>(USP Ingress)
    participant RTR  as PbrSwitchRouter<br/>(Data Plane Engine)
    participant HDM  as PbrHdmDecoderManager<br/>(Address→DPID)
    participant DRT  as PbrSwitchManager<br/>(DRT Lookup)
    participant GFD  as GFD<br/>(Port 1 Egress)

    Note over HOST,GFD: Host performs memory write to address 0x1000_0000

    HOST->>RTR: HBR TLP MemWr(addr=0x1000_0000, data=[...])
    Note right of RTR: Ingress port = 0 (USP)<br/>Packet type = HBR (non-PBR)

    RTR->>HDM: resolve_address(0x1000_0000)
    Note right of HDM: Scan HDM decoder ranges:<br/>range[0x1000_0000..0x1FFF_FFFF] → DPID=0x010
    HDM-->>RTR: dpid = 0x010

    RTR->>RTR: encapsulate_pbr(spid=0x000, dpid=0x010, inner=TLP)
    Note right of RTR: PBR Header prepended:<br/>SPID=0x000, DPID=0x010

    RTR->>DRT: get_drt(drt_index=0, dpid=0x010)
    Note right of DRT: entries[0x010] = DrtEntry(PHYSICAL_PORT, 1)
    DRT-->>RTR: DrtEntry(type=PHYSICAL_PORT, routing_target=1)

    RTR->>RTR: strip_pbr_header(packet) → original TLP
    Note right of RTR: PBR header removed before sending to endpoint

    RTR->>GFD: MemWr TLP → Port 1 egress queue → TCP socket
    Note right of GFD: GFD receives raw CXL MemWr<br/>Processes via CxlGfdDevice
    GFD-->>RTR: CplD (Completion with Data) or Cpl
    RTR-->>HOST: Completion forwarded to USP
```

---

## 3. MCTP CCI Request/Response — Full Transport Flow

End-to-end bytes on the wire from API call to response.

```mermaid
sequenceDiagram
    autonumber
    participant APP  as Application<br/>Test / FM Socket.IO
    participant API  as MctpCciApiClient<br/>(FM side)
    participant MGR  as MctpConnectionManager<br/>(FM TCP Server)
    participant PROC1 as MctpPacketProcessor<br/>(CONTROLLER type)
    participant TCP  as TCP Socket<br/>(127.0.0.1:ephemeral)
    participant PROC2 as MctpPacketProcessor<br/>(ENDPOINT type)
    participant CLI  as MctpConnectionClient<br/>(Switch side)
    participant EXE  as MctpCciExecutor
    participant CMD  as IdentifyPbrSwitchCommand

    APP->>API: await api.identify_pbr_switch()

    Note over API: Allocate message tag=N<br/>Build CciMessagePacket [opcode=0x5700]
    API->>MGR: controller_to_ep.put(CciPayloadPacket)
    Note over MGR,PROC1: MctpConnectionManager._switch_port<br/>packet_processor reads from controller_to_ep

    PROC1->>TCP: write_bytes(serialized MCTP+CCI packet)
    Note over TCP: Bytes: [MCTP hdr][CCI hdr][opcode=5700]

    TCP->>PROC2: read_bytes() → deserialized packet
    PROC2->>CLI: controller_to_ep.put(CciPayloadPacket)
    CLI->>EXE: _mctp_connection.controller_to_ep.get()

    EXE->>EXE: extract opcode=0x5700 from CCI header
    EXE->>CMD: _execute(CciRequest{opcode=0x5700, payload=b''})
    CMD-->>EXE: CciResponse{payload=IdentifyPbrSwitchResponsePayload.dump()}

    EXE->>CLI: ep_to_controller.put(response_packet)
    PROC2->>TCP: write_bytes(response)
    TCP->>PROC1: read_bytes()
    PROC1->>MGR: ep_to_controller.put(response_packet)

    Note over API: _process_incoming_packets() dequeues<br/>Notifies _condition (tag=N found)
    MGR-->>API: ep_to_controller.get() → CciMessagePacket
    API->>API: _condition.notify_all()
    API-->>APP: (CCI_RETURN_CODE.SUCCESS, IdentifyPbrSwitchResponsePayload)
```

---

## 4. RunnableComponent Lifecycle

Every async component (`MctpConnectionManager`, `MctpCciExecutor`, etc.) follows this lifecycle.

```mermaid
sequenceDiagram
    autonumber
    participant TEST as Test / Caller
    participant COMP as RunnableComponent
    participant LOOP as asyncio Event Loop

    TEST->>COMP: task = await comp.run_wait_ready()
    Note over COMP: Creates asyncio.Task for run()
    LOOP->>COMP: schedules _run() coroutine

    COMP->>COMP: _change_status_to_running()
    Note over COMP: _condition.notify_all()<br/>_status = RUNNING

    COMP-->>TEST: task handle returned
    Note right of TEST: Component is now RUNNING<br/>Test can send commands

    TEST->>TEST: ... send CCI commands via harness.call() ...

    TEST->>COMP: await comp.stop()
    Note over COMP: _stop() called<br/>Signals internal queues with None sentinel
    COMP->>COMP: _change_status_to_stopped()
    COMP-->>TEST: stop() returns
```

---

## 5. Test Harness Architecture (daemon-thread pattern)

How the pytest test harness avoids Windows IOCP deadlocks.

```mermaid
sequenceDiagram
    autonumber
    participant TEST as pytest Test<br/>(sync def test_*)
    participant FIX  as @pytest.fixture<br/>harness_with_targets
    participant HARN as PbrLiveSwitchHarness
    participant THR  as Daemon Thread<br/>(asyncio loop)
    participant COMP as Async Components<br/>(MCTP + PBR stack)

    TEST->>FIX: fixture setup
    FIX->>HARN: h = PbrLiveSwitchHarness(pid_targets=[...])
    FIX->>HARN: h.start()
    HARN->>THR: threading.Thread(target=_thread_main, daemon=True).start()
    THR->>COMP: asyncio.new_event_loop().run_until_complete(_start_components())
    COMP-->>THR: all components RUNNING
    THR-->>HARN: _ready_event.set()
    HARN-->>FIX: ready (within 10s timeout)
    FIX-->>TEST: yield h

    TEST->>HARN: rc, resp = h.call(h.api.identify_pbr_switch())
    Note over HARN: asyncio.run_coroutine_threadsafe(coro, self._loop)
    HARN->>COMP: coroutine submitted to daemon thread's event loop
    COMP-->>HARN: future.result(timeout=15.0)
    HARN-->>TEST: (CCI_RETURN_CODE.SUCCESS, payload)

    Note over TEST,COMP: Test assertions...

    TEST->>FIX: fixture teardown (yield ends)
    Note over THR: Daemon thread killed by OS<br/>TCP sockets reclaimed
    Note right of TEST: No asyncio.gather() needed ✓<br/>No IOCP deadlock on Windows ✓
```
