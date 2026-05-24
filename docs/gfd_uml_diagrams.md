# GFD / PBR — UML Class & State Diagrams

**Project:** opencis-core CXL 4.0 PBR Simulator  
**Date:** May 2026

---

## 1. UML Class Diagram

```mermaid
classDiagram
    direction TB

    %% ─── Base Infrastructure ────────────────────────────────────────────
    class RunnableComponent {
        <<abstract>>
        +_status: COMPONENT_STATUS
        +_condition: asyncio.Condition
        +_label: str
        +run() Task
        +run_wait_ready() Task
        +stop() None
        +wait_for_ready() None
        #_run()* None
        #_stop()* None
        #_change_status_to_running() None
        #_change_status_to_stopped() None
    }

    class ServerComponent {
        -_host: str
        -_port: int
        -_handle_client: Callable
        -_stop_callback: Callable
        -_server_task: Task
        -_clients: set
        +get_port() int
        #_run() None
        #_stop() None
        +_create_server() asyncio.Server
    }

    %% ─── MCTP Transport Layer ──────────────────────────────────────────
    class MctpConnectionManager {
        -_host: str
        -_port: int
        -_switch_port: MctpPort
        -_server_component: ServerComponent
        +get_mctp_connection() MctpConnection
        #_run() None
        #_stop() None
        #_handle_client(reader, writer) None
    }

    class MctpConnectionClient {
        -_host: str
        -_port: int
        -_auto_reconnect: bool
        -_mctp_connection: MctpConnection
        -_packet_processor: MctpPacketProcessor
        +get_mctp_connection() MctpConnection
        #_run() None
        #_stop() None
    }

    class MctpPacketProcessor {
        -_reader: asyncio.StreamReader
        -_writer: asyncio.StreamWriter
        -_mctp_connection: MctpConnection
        -_type: MCTP_PACKET_PROCESSOR_TYPE
        #_run() None
        #_stop() None
        -_process_incoming_packets() None
        -_process_outgoing_packets() None
    }

    class MctpConnection {
        +controller_to_ep: asyncio.Queue
        +ep_to_controller: asyncio.Queue
    }

    %% ─── CCI Executor (Switch side) ─────────────────────────────────────
    class MctpCciExecutor {
        -_mctp_connection: MctpConnection
        -_cci_executor: CciExecutor
        -_downstream_port_connections: dict
        +register_cci_commands(commands) None
        #_run() None
        #_stop() None
        -_process_incoming_requests() None
        -_process_outcoming_responses() None
    }

    class CciExecutor {
        -_commands: Dict~int, CciCommand~
        +register_command(cmd) None
        +execute(request) CciResponse
    }

    %% ─── CCI API Client (FM side) ────────────────────────────────────────
    class MctpCciApiClient {
        -_mctp_connection: MctpConnection
        -_tag: int
        -_responses: Dict~int, CciMessagePacket~
        -_condition: asyncio.Condition
        +identify_pbr_switch() tuple
        +configure_pid_assignment(req) tuple
        +get_pid_binding(req) tuple
        +configure_pid_binding(req) tuple
        +get_drt(req) tuple
        +set_drt(req) tuple
        #_run() None
        #_stop() None
        -_send_request(req) CciMessagePacket
        -_get_response(tag) CciMessagePacket
    }

    %% ─── PBR State Machine ──────────────────────────────────────────────
    class PbrSwitchManager {
        -_label: str
        -_switch_info: PbrSwitchInfo
        -_drt_tables: List~DrtTable~
        -_pid_targets: List~PidTarget~
        -_pid_assignments: Dict~int, PidAssignment~
        -_pid_bindings: Dict~tuple, PidBinding~
        +get_identify_info() PbrSwitchInfo
        +assign_pid(pid, target_id, instance_id) CCI_RETURN_CODE
        +clear_pid(pid, target_id, instance_id) CCI_RETURN_CODE
        +get_drt(drt_index, start, num) tuple
        +set_drt(drt_index, start, entries) CCI_RETURN_CODE
        +get_pid_binding(vcs_id, vppb_id) PidBinding
        +configure_pid_binding(op, vcs, vppb, pid, hmat) CCI_RETURN_CODE
    }

    class PbrSwitchInfo {
        +gae_support_map: int
        +num_drts: int
        +num_rgts: int
        +random_supported: bool
        +congestion_avoidance_supported: bool
        +routing_caps_byte() int
    }

    class DrtTable {
        +associated_rgt_index: int
        +entries: List~DrtEntry~
    }

    class DrtEntry {
        +entry_type: DrtEntryType
        +routing_target: int
        +dump() bytes
        +parse(data, offset)$ DrtEntry
    }

    class DrtEntryType {
        <<enumeration>>
        INVALID = 0
        PHYSICAL_PORT = 1
        RGT_INDEX = 2
        RESERVED = 3
    }

    %% ─── Data Plane ─────────────────────────────────────────────────────
    class PbrSwitchRouter {
        -_upstream_fifos: dict
        -_downstream_fifos: dict
        -_pbr_manager: PbrSwitchManager
        -_hdm_decoder: PbrHdmDecoderManager
        #_run() None
        -_route_packet(ingress_port, packet) None
        -_encapsulate_pbr(spid, dpid, pkt) PbrPacket
    }

    class PbrHdmDecoderManager {
        -_ranges: List~HdmRange~
        +resolve_address(addr) int
    }

    %% ─── CCI Commands ────────────────────────────────────────────────────
    class CciForegroundCommand {
        <<abstract>>
        +OPCODE: int
        #_execute(request)* CciResponse
        +create_cci_request()$ CciRequest
    }

    class CciBackgroundCommand {
        <<abstract>>
        +OPCODE: int
        #_execute(request, callback)* CciResponse
        +create_cci_request()$ CciRequest
    }

    class IdentifyPbrSwitchCommand {
        +OPCODE = 0x5700
        -_pbr_switch_manager: PbrSwitchManager
        #_execute(request) CciResponse
        +parse_response_payload(data)$ IdentifyPbrSwitchResponsePayload
    }

    class ConfigurePidAssignmentCommand {
        +OPCODE = 0x5704
        -_pbr_switch_manager: PbrSwitchManager
        #_execute(request) CciResponse
    }

    class GetPidBindingCommand {
        +OPCODE = 0x5705
        -_pbr_switch_manager: PbrSwitchManager
        #_execute(request) CciResponse
        +parse_response_payload(data)$ GetPidBindingResponsePayload
    }

    class ConfigurePidBindingCommand {
        +OPCODE = 0x5706
        -_pbr_switch_manager: PbrSwitchManager
        #_execute(request, callback) CciResponse
    }

    class GetDrtCommand {
        +OPCODE = 0x5708
        -_pbr_switch_manager: PbrSwitchManager
        #_execute(request) CciResponse
        +parse_response_payload(data)$ GetDrtResponsePayload
    }

    class SetDrtCommand {
        +OPCODE = 0x5709
        -_pbr_switch_manager: PbrSwitchManager
        #_execute(request) CciResponse
    }

    %% ─── Inheritance ─────────────────────────────────────────────────────
    RunnableComponent <|-- ServerComponent
    RunnableComponent <|-- MctpConnectionManager
    RunnableComponent <|-- MctpConnectionClient
    RunnableComponent <|-- MctpPacketProcessor
    RunnableComponent <|-- MctpCciExecutor
    RunnableComponent <|-- MctpCciApiClient
    RunnableComponent <|-- PbrSwitchRouter

    CciForegroundCommand <|-- IdentifyPbrSwitchCommand
    CciForegroundCommand <|-- ConfigurePidAssignmentCommand
    CciForegroundCommand <|-- GetPidBindingCommand
    CciForegroundCommand <|-- GetDrtCommand
    CciForegroundCommand <|-- SetDrtCommand
    CciBackgroundCommand <|-- ConfigurePidBindingCommand

    %% ─── Associations ────────────────────────────────────────────────────
    MctpConnectionManager *-- ServerComponent : contains
    MctpConnectionManager *-- MctpConnection  : owns _switch_port.mctp_connection
    MctpConnectionClient  *-- MctpConnection  : owns _mctp_connection
    MctpConnectionClient  *-- MctpPacketProcessor : creates per connection
    MctpCciExecutor       o-- MctpConnection  : uses (switch-side)
    MctpCciExecutor       *-- CciExecutor     : contains
    MctpCciApiClient      o-- MctpConnection  : uses (fm-side)
    CciExecutor           o-- CciForegroundCommand : dispatches to
    CciExecutor           o-- CciBackgroundCommand : dispatches to
    IdentifyPbrSwitchCommand     o-- PbrSwitchManager : queries
    ConfigurePidAssignmentCommand o-- PbrSwitchManager : mutates
    GetPidBindingCommand         o-- PbrSwitchManager : queries
    ConfigurePidBindingCommand   o-- PbrSwitchManager : mutates
    GetDrtCommand                o-- PbrSwitchManager : queries
    SetDrtCommand                o-- PbrSwitchManager : mutates
    PbrSwitchRouter       o-- PbrSwitchManager      : queries DRT
    PbrSwitchRouter       o-- PbrHdmDecoderManager  : resolves addresses
    PbrSwitchManager      *-- PbrSwitchInfo : owns
    PbrSwitchManager      *-- DrtTable      : owns 1..N
    DrtTable              *-- DrtEntry      : contains 4096
    DrtEntry              o-- DrtEntryType  : uses
```

---

## 2. PbrSwitchManager State Machine

```mermaid
stateDiagram-v2
    direction LR

    [*] --> INIT : PbrSwitchManager()

    INIT --> PORT_CONFIGURED : ConfigurePidAssignment(ASSIGN)\nassign_pid(pid, target_id) → SUCCESS
    PORT_CONFIGURED --> INIT : ConfigurePidAssignment(CLEAR)\nclear_pid(pid) → SUCCESS

    PORT_CONFIGURED --> DRT_PROGRAMMED : SetDrt(drt_index, start, entries)\nset_drt() → SUCCESS
    DRT_PROGRAMMED --> PORT_CONFIGURED : SetDrt(INVALID entry)\nor new assign clears port

    DRT_PROGRAMMED --> BINDING_ACTIVE : ConfigurePidBinding(BIND)\nconfigure_pid_binding(BIND) → SUCCESS
    BINDING_ACTIVE --> DRT_PROGRAMMED : ConfigurePidBinding(UNBIND)\nconfigure_pid_binding(UNBIND) → SUCCESS

    note right of INIT
        _pid_assignments = {}
        _pid_bindings = {}
        _drt_tables[*].entries all = INVALID
    end note

    note right of PORT_CONFIGURED
        _pid_assignments[pid] = PidAssignment
        DRT entries still INVALID
        Packets dropped (no routing)
    end note

    note right of DRT_PROGRAMMED
        _drt_tables[0].entries[pid] = DrtEntry(PHYSICAL_PORT, port)
        Routing active for data plane
        No VCS/vPPB binding yet
    end note

    note right of BINDING_ACTIVE
        _pid_bindings[(vcs,vppb)] = PidBinding(pid, hmat)
        Fully commissioned
        Host can route to this port
    end note
```

---

## 3. RunnableComponent Lifecycle

```mermaid
stateDiagram-v2
    direction LR

    [*] --> CREATED : __init__()
    CREATED --> RUNNING : run_wait_ready()\n_change_status_to_running()

    RUNNING --> RUNNING : Normal operation\n(processing packets/requests)

    RUNNING --> STOPPED : stop()\n_change_status_to_stopped()

    STOPPED --> [*]

    note right of CREATED
        _condition = asyncio.Condition()
        _status = COMPONENT_STATUS.CREATED
    end note

    note right of RUNNING
        _status = COMPONENT_STATUS.RUNNING
        _condition notified
        wait_for_ready() returns
    end note

    note right of STOPPED
        _status = COMPONENT_STATUS.STOPPED
        All internal tasks completed
        Queues flushed
    end note
```

---

## 4. ConfigurePidBinding — Background Command Progress

```mermaid
stateDiagram-v2
    direction TB

    [*] --> PARSING : _execute() called
    PARSING --> VALIDATED : ConfigurePidBindingRequestPayload.parse()\noperation, target_vcs, target_vppb, pid extracted

    VALIDATED --> PROGRESS_10 : await callback(10)
    PROGRESS_10 --> EXECUTING : Build HmatInfo\nDetermine PidBindingOperation

    EXECUTING --> PROGRESS_50 : await callback(50)
    PROGRESS_50 --> STATE_UPDATED : pbr_manager.configure_pid_binding()\n_pid_bindings[(vcs,vppb)] = PidBinding(pid)

    STATE_UPDATED --> PROGRESS_100 : await callback(100)
    PROGRESS_100 --> [*] : CciResponse(SUCCESS)

    VALIDATED --> [*] : Parse failure\nCciResponse(INVALID_INPUT)
    STATE_UPDATED --> [*] : UNBIND on unbound slot\nCciResponse(INVALID_INPUT)
```

---

## 5. Full System Architecture Diagram

```mermaid
graph TB
    subgraph FM["🧠 Fabric Manager Side"]
        direction TB
        APP["Application / Test\n(MctpCciApiClient.identify_pbr_switch())"]
        API["MctpCciApiClient\n• controller_to_ep.put(request)\n• ep_to_controller.get() → response\n• _condition.notify_all()"]
        MGRSRV["MctpConnectionManager\n• TCP Server :0 (ephemeral)\n• Owns MctpPort + MctpConnection"]
        PROC1["MctpPacketProcessor\n(CONTROLLER type)\n• Serializes CCI → TCP bytes\n• Deserializes TCP bytes → CCI"]
    end

    subgraph NET["🌐 TCP Network"]
        TCP["127.0.0.1 : port\nRaw bytes: MCTP + CCI headers"]
    end

    subgraph SW["🔀 Switch Side"]
        direction TB
        CLI["MctpConnectionClient\n• TCP Client\n• auto_reconnect=False\n• Owns MctpConnection"]
        PROC2["MctpPacketProcessor\n(ENDPOINT type)\n• Deserializes bytes → CCI\n• Serializes CCI → bytes"]
        EXE["MctpCciExecutor\n• Dispatches opcode → command\n• _process_incoming_requests()\n• _process_outcoming_responses()"]
        PBRMGR["PbrSwitchManager\n• _pid_targets: List[PidTarget]\n• _pid_assignments: Dict[pid→PidAssignment]\n• _drt_tables: List[DrtTable]\n• _pid_bindings: Dict[(vcs,vppb)→PidBinding]"]
        subgraph CMDS["CCI Commands"]
            C1["IdentifyPbrSwitchCommand\nopcode=0x5700"]
            C2["ConfigurePidAssignmentCommand\nopcode=0x5704"]
            C3["GetPidBindingCommand\nopcode=0x5705"]
            C4["ConfigurePidBindingCommand\nopcode=0x5706 (BG)"]
            C5["GetDrtCommand\nopcode=0x5708"]
            C6["SetDrtCommand\nopcode=0x5709"]
        end
    end

    subgraph DP["⚡ Data Plane"]
        RTR["PbrSwitchRouter\n• Route TLPs USP↔DSP\n• Encapsulate/strip PBR headers"]
        HDM["PbrHdmDecoderManager\n• addr → DPID resolution"]
    end

    subgraph GFD["📦 GFD Device"]
        GFDD["CxlGfdDevice\n• BAR-0: 256B MMIO\n• CCI mailbox\n• Status register"]
    end

    APP --> API
    API <-->|"controller_to_ep\nep_to_controller\n(asyncio.Queue)"| MGRSRV
    MGRSRV <--> PROC1
    PROC1 <-->|"TCP bytes"| TCP
    TCP <-->|"TCP bytes"| PROC2
    PROC2 <--> CLI
    CLI <-->|"controller_to_ep\nep_to_controller\n(asyncio.Queue)"| EXE
    EXE --> C1 & C2 & C3 & C4 & C5 & C6
    C1 & C2 & C3 & C4 & C5 & C6 --> PBRMGR
    RTR --> PBRMGR
    RTR --> HDM
    RTR <-->|"asyncio.Queue\n(FIFOs)"| GFD

    style FM fill:#1a3a5c,stroke:#4a9eff,color:#fff
    style NET fill:#2d2d2d,stroke:#888,color:#ddd
    style SW fill:#1a4a2a,stroke:#4aff88,color:#fff
    style DP fill:#3a1a4a,stroke:#aa4aff,color:#fff
    style GFD fill:#4a2a1a,stroke:#ff884a,color:#fff
```
