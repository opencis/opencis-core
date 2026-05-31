# PBR & GFD Test Framework Guide

To ensure the CXL Port-Based Routing (PBR) and Generic Fabric Device (GFD) work flawlessly, the simulation uses three distinct layers of testing. This document explains how each test type is implemented and traces the exact code flow.

---

## 1. Important Files to Understand

Before diving into the test layers, here is a quick map of the 4 most important files that make testing possible:

1.  **`tests/test_pbr_switch_command_set.py` (The Unit Test Suite):** Contains 45+ tests that pass raw byte-arrays directly into the switch's command handlers. It proves the configuration logic works perfectly without the overhead of networking or sockets.
2.  **`tests/test_pbr_data_plane.py` (The Routing Test Suite):** Contains integration tests that inject fake memory-write packets into the router's input queues to prove that Address translation, PBR encapsulation, and the Routing Tables (DRT) work.
3.  **`run_pbr_env.py` (The Live Environment Script):** Acts like a "Docker Compose" for the simulation. It spins up the Fabric Manager, the Switch, the SLD, and the GFD concurrently on different TCP ports so they can talk to each other in real-time.
4.  **`pbr_fm_cli.py` (The User Interface):** Connects to the FM using a web-socket (Socket.IO) and translates human clicks (`[1]`, `[2]`, etc.) into JSON commands that the FM understands.

---

## 2. Layer 1: CCI Unit Tests (Control Plane)

**File:** `tests/test_pbr_switch_command_set.py`
**Goal:** Verify that the Switch correctly parses and executes the 6 PBR commands defined in the CXL 4.0 spec.

### How it is Implemented
These tests do **not** spin up network sockets. They instantiate the `PbrSwitchManager` (the central brain of the switch) and call the command handlers directly in-memory.

### Code Flow Example: Testing "Assign PID"
Let's trace `test_configure_pid_assignment_valid`:

1.  **Setup:** The test creates a dummy `PbrSwitchManager` pre-populated with some available targets (e.g., Physical Port 2).
2.  **Create Command:** It instantiates the `ConfigurePidAssignmentCommand` class, injecting the dummy switch manager.
3.  **Construct Payload:** It builds a raw byte-array representing the CXL Spec payload (e.g., Operation=0, PID=0x200, Target=2).
4.  **Execute:** The test calls `await command._execute(request)`.
5.  **Inside the Handler:** The command parses the bytes, validates the data, and calls `pbr_manager.assign_pid(0x200, 2)`.
6.  **Assertion:** The test inspects the `PbrSwitchManager` to assert that it now contains a record linking PID `0x200` to Port `2`, and that the return code was `SUCCESS`.

---

## 3. Layer 2: Data-Plane Integration Tests

**File:** `tests/test_pbr_data_plane.py`
**Goal:** Verify that a standard Host memory write packet is successfully encapsulated into a PBR packet, routed through the switch, and decapsulated at the egress port.

### How it is Implemented
These tests isolate the **Router Engine**. We bypass the TCP sockets entirely. We instantiate the `PbrSwitchRouter`, manually push a packet into the ingress queue, and check if it pops out the correct egress queue.

### Code Flow Example: Testing "Data Plane Routing"
Let's trace `test_pbr_end_to_end_address_routing`:

1.  **Program HDM Decoder:** We tell the `PbrHdmDecoderManager`: *"Any traffic destined for memory address `0x1500` should go to DPID `0x200`."*
2.  **Program DRT:** We tell the `PbrSwitchManager`: *"Any traffic for DPID `0x200` should route to Physical Port 2."*
3.  **Start Router:** We start the `PbrSwitchRouter` background tasks.
4.  **Inject Packet:** The test creates a fake PCIe memory write packet (HBR TLP) aimed at address `0x1500`. It manually drops this packet into the FIFO queue for Port 0 (Upstream Port).
5.  **The Router Engine Runs:**
    *   The router reads Port 0's queue.
    *   It sees address `0x1500`. It asks the HDM Decoder for the DPID (`0x200`).
    *   It wraps the packet in a `PbrHeader` (encapsulation).
    *   It checks the DRT for `0x200`, which says "Send to Port 2".
    *   It strips the `PbrHeader` (decapsulation).
    *   It drops the original packet into Port 2's outgoing FIFO queue.
6.  **Assertion:** The test reads from Port 2's outgoing FIFO queue and verifies that the packet that arrived is exactly the same packet we injected at Port 0.

---

## 4. Layer 3: Interactive End-to-End Test

**Files:** `run_pbr_env.py` and `pbr_fm_cli.py`
**Goal:** Verify the entire system works concurrently over real network sockets.

### How it is Implemented
`run_pbr_env.py` spins up the FM, the Switch, the SLD, and the GFD using `asyncio.gather()`. They all communicate over real `127.0.0.1` TCP sockets. `pbr_fm_cli.py` acts as the user interface, communicating via HTTP/Socket.IO to the FM.

### Detailed Breakdown of Each CLI Test Case

Here is what happens under the hood for each option in the CLI menu, what you should expect to see, and *why* it passes.

#### `[1] Identify PBR Switch`
*   **What it does:** Asks the switch for its PBR capabilities.
*   **Code Flow:** CLI -> Socket.IO -> FM -> MCTP Packet (0x5700) -> Switch.
*   **Expected Output:** `GAE Support Map : 0x00`, `Num DRTs : 1`.
*   **Why it passes:** The `CxlSwitchConfig` was initialized with `enable_pbr=True`, which registers the PBR commands and sets up 1 DPID Routing Table (DRT).

#### `[2] Assign PID 0x100 (SLD)` & `[3] Assign PID 0x200 (GFD)`
*   **What it does:** Assigns the numeric ID `0x100` to Physical Port 1 (where the SLD is plugged in) and `0x200` to Port 2 (GFD).
*   **Code Flow:** FM sends `ConfigurePidAssignmentCommand` (0x5704). The switch's `PbrSwitchManager` updates its internal `_pid_assignments` dictionary.
*   **Expected Output:** `PID 0x100 → target_id=1 assigned successfully`.
*   **Why it passes:** The switch successfully stored the mapping in memory without any conflicts.

#### `[4] Set DRT for SLD` & `[5] Set DRT for GFD`
*   **What it does:** Programs the DPID Routing Table (DRT) so the router knows where to send packets.
*   **Code Flow:** FM sends `SetDrtCommand` (0x5709). The switch updates its DRT array at index `0x100` to point to `PHYSICAL_PORT 1`.
*   **Expected Output:** `DRT[0][0x100] → Physical Port 1 programmed`.
*   **Why it passes:** The DRT table has enough capacity, and the requested physical port is a valid Downstream Port.

#### `[6] Get DRT (SLD)` & `[7] Get DRT (GFD)`
*   **What it does:** Reads back the routing table to verify it was programmed correctly.
*   **Code Flow:** FM sends `GetDrtCommand` (0x5708). The switch reads the DRT array and returns the entry.
*   **Expected Output:** `Entry[0x100] type=PHYSICAL_PORT target=1`.
*   **Why it passes:** It matches the exact data we wrote in step `[4]`.

#### `[8] Get PID Binding` & `[9] Configure PID Binding` (In-Depth)
*   **What it does:** The CXL specification allows PIDs to be "bound" to Virtual CXL Switches (VCS) or Virtual PCI-to-PCI Bridges (vPPB). This allows a physical port (which has a PID) to be mapped into the host's virtual PCIe hierarchy so the OS can see it.
*   **The Background Command Pattern:** According to the CXL 4.0 specification (§7.7.13.7), binding a PID requires the switch to perform actual link-state transitions (e.g., dropping the PCIe link to Hot Reset, detecting it again, and bringing it back to L0). This takes time. Therefore, `Configure PID Binding` (0x5706) is mandated to be a **Background Command**.
*   **Code Flow (The tricky part):** 
    1.  The FM Client (`pbr_fm_cli.py`) sends the `ConfigurePidBinding` request via Socket.IO.
    2.  The FM translates it to MCTP and sends it to the switch.
    3.  The Switch receives it and *immediately* returns a special status code: `BACKGROUND_COMMAND_STARTED` (0x02), rather than `SUCCESS` (0x00). It then processes the binding in the background.
    4.  Our API client (`mctp_cci_api_client.py`) is smart enough to know this protocol rule. When it sees `BACKGROUND_COMMAND_STARTED`, it enters a `wait_for_background_operation()` loop. It repeatedly polls the switch's background status register until the switch says it's 100% done.
    5.  Once the switch finishes the background task, the client returns `SUCCESS` to the CLI.
*   **Expected Output:** `PID 0x100 bound to target PID 0x0`.
*   **Why it passes:** In our Python simulation, the background command completes almost instantly, but the *protocol rule* of returning `BACKGROUND_COMMAND_STARTED` and waiting for it is perfectly emulated. The test passes because we specifically updated `mctp_cci_api_client.py` to handle the async background pattern properly instead of treating `0x02` as a failure!

#### `[w] Mem-Write (SLD/GFD)` & `[r] Mem-Read (SLD/GFD)`
*   **What it does:** Proves the memory devices have actual backing storage.
*   **Code Flow:** The CLI opens `pbr_sld_mem.bin` or `pbr_gfd_mem.bin` directly on the host file system, writes `DEADBEEF` at offset 0, and then reads it back.
*   **Expected Output:** `Wrote DEADBEEF...` followed by `Read success: matches DEADBEEF`.
*   **Why it passes:** The binary files were successfully created by `run_pbr_env.py` at startup with 1MB of zero-filled space.

*(Note: While the CLI's `Mem-Write` currently writes directly to the binary backing files to verify the simulated device memory works, the `test_pbr_data_plane.py` test proves that the packets actually route there over the fabric!)*
