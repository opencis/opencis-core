# CXL Switch & PBR — Technical Interview Preparation

> Based on the `opencis-core` implementation of CXL 4.0 Port-Based Routing (PBR).
> Spec reference: CXL Specification Rev 4.0, §7.7.13.

---

## 🔵 CXL Fundamentals

### Q1. What is CXL and why does it matter?
CXL (Compute Express Link) is a high-speed interconnect built on the PCIe physical layer
that provides cache-coherent memory access between CPUs, GPUs, FPGAs, and memory expanders.
It matters because it breaks the memory capacity/bandwidth wall — pooled memory can be
shared across devices without cache-coherency software overhead.

---

### Q2. What are the three CXL protocol sub-layers?
| Sub-layer | Purpose |
|-----------|---------|
| **CXL.io** | PCIe-compatible, non-coherent I/O (config space, MMIO) |
| **CXL.cache** | Device-side cache coherency with host |
| **CXL.mem** | Host-initiated access to device-attached memory |

---

### Q3. What is a CXL switch? How does it differ from a PCIe switch?
A CXL switch multiplexes multiple CXL devices under one upstream port, similar to a PCIe
switch. Unlike PCIe switches which only route CXL.io, a CXL switch must also route
CXL.cache and CXL.mem flits. In this project the switch additionally implements PBR —
an extra routing layer for fabric-scale multi-hop topologies.

---

## 🟡 PBR (Port-Based Routing) — Core Feature

### Q4. What problem does PBR solve that standard CXL switching doesn't?
Standard CXL switches use hierarchical PCIe-style routing (BDF addressing), which does
not scale beyond a single switch domain. PBR adds a **12-bit PID (Port ID)** embedded
in the TLP header so packets can be routed across multiple fabric hops without needing a
flat host address space for every device.

---

### Q5. Walk through the lifecycle of a packet in the PBR router.
1. Packet arrives at an ingress port (HBR or PBR encapsulated)
2. If **HBR**: the HDM decoder maps destination address → DPID
3. Packet is **encapsulated** with a PBR routing header (`spid`, `dpid`)
4. Router looks up `DRT[active_drt_index].entries[dpid]` → egress physical port
5. Packet is **decapsulated** back to HBR and forwarded to the egress port

---

### Q6. What is the DRT? What is it indexed by?
The **DPID Routing Table (DRT)** is a flat array of 4096 entries indexed by **DPID**
(Destination PID) — *not* by port number.

```
DRT[dpid] → { entry_type, routing_target }
```

`DRT_TABLE_SIZE = 4096` because PID is a 12-bit field (2¹² = 4096 possible values).

---

### Q7. Why doesn't assigning a PID automatically populate the DRT?
By spec design (§7.7.13.5): PID assignment (`Configure PID Assignment — 5704h`) declares
*ownership* of a PID by a target, but the actual routing path is programmed separately
by the Fabric Manager via `Set DRT (5709h)`. This decoupling lets the FM batch-program
routes and supports cases where a PID is assigned but not yet routable.

> **Test that verifies this**: `test_fm_workflow_assign_then_set_drt` — after `assign_pid`,
> `DRT[0x042]` is still `INVALID` until `set_drt` is explicitly called.

---

### Q8. What are the DRT entry types and what does each mean?
| Entry Type | Value | Meaning |
|-----------|-------|---------|
| `INVALID` | `00b` | No route — drop or error |
| `PHYSICAL_PORT` | `01b` | Route to specific physical port number |
| `RGT_INDEX` | `10b` | Indirect via Routing Group Table (multicast/group) |
| `RESERVED` | `11b` | Invalid — rejected by `set_drt()` as `INVALID_INPUT` |

---

### Q9. What is `PID_UNASSIGNED = 0xFFF`? Why that value?
`0xFFF` is the all-ones 12-bit value. The CXL spec reserves it as a sentinel meaning
"no PID is assigned here." It appears in `GetPidBindingResponsePayload` when a vPPB
has no binding. In code: `PID_UNASSIGNED == PID_MAX == 0xFFF`.

---

### Q10. What is SPID vs DPID in the PBR header?
| Field | Meaning |
|-------|---------|
| **SPID** | Source PID — identifies the originating fabric port |
| **DPID** | Destination PID — used to look up the DRT entry for routing |

---

## 🟠 CCI Commands — Implementation Details

### Q11. What is the CCI? How is it used in PBR?
The **Component Command Interface (CCI)** is the management channel between the Fabric
Manager and switch/device components. It uses a mailbox-style request/response protocol
over MMIO. PBR CCI commands (`5700h`–`5709h`) allow the FM to query switch capabilities
and program PID assignments, DRT routes, and PID bindings.

---

### Q12. List all PBR CCI opcodes and their purpose.
| Opcode | Command | Purpose |
|--------|---------|---------|
| `5700h` | Identify PBR Switch | Query DRT/RGT counts, routing capabilities |
| `5704h` | Configure PID Assignment | Assign or clear PIDs on targets |
| `5705h` | Get PID Binding | Read VCS/vPPB → PID mapping |
| `5706h` | Configure PID Binding | Bind or unbind PID to a VCS vPPB |
| `5708h` | Get DRT | Read DRT entries |
| `5709h` | Set DRT | Program DRT routing entries |

---

### Q13. What happens if you assign the same PID to two different targets?
`assign_pid()` returns `CCI_RETURN_CODE.INVALID_INPUT`. Idempotent re-assignment
to the *same* target returns `SUCCESS`.

> **Test**: `test_assign_pid_duplicate_different_target_rejected`

---

### Q14. How does `set_drt` validate boundary conditions?
It checks both: `start_entry < 0` AND `start_entry + len(entries) > 4096`.
Writing 2 entries starting at index 4095 fails: `4095 + 2 = 4097 > 4096`.

> **Test**: `test_set_drt_exceeds_table_size`

---

### Q15. What does `num_drts` in `Identify PBR Switch` response represent?
The number of independent DRT tables the switch exposes. The implementation derives
this at call time from `len(self._drt_tables)` — not from a cached field — so the
reported value is always consistent with actual state.

---

## 🔴 Architecture & Design

### Q16. What is the Fabric Manager's role in PBR?
The FM is the orchestration (control) plane. It uses CCI to:
1. Identify PBR switch capabilities
2. Assign PIDs to physical ports
3. Program DRT routing tables
4. Bind PIDs to VCS vPPBs for edge stitching

The switch itself is passive — it executes whatever routing the FM programs.

---

### Q17. What is an HDM Decoder and how does it interact with PBR?
The **Host-managed Device Memory (HDM) Decoder** maps host physical address ranges to
target DPIDs. In `PbrHdmDecoderManager`, a committed decoder entry means:
> "Packets with addresses in `[base, base+size)` should be encapsulated with `dpid = target_ports[0]`."

This is how raw HBR address-based packets get a DPID assigned for PBR routing.

---

### Q18. What is a vPPB?
A **Virtual PCIe-to-PCIe Bridge** — a logical port inside a Virtual CXL Switch (VCS).
In PBR context, `(vcs_id, vppb_id)` is the key for a PID binding entry, enabling
fabric edge stitching between fabric domains.

---

### Q19. What is an RGT (Routing Group Table)?
The RGT supports group/multicast routing. A DRT entry of type `RGT_INDEX` points to
an RGT entry instead of a single port, allowing a packet with one DPID to be
replicated to multiple egress ports.

---

### Q20. What is HBR vs PBR packet format?
| Format | Description |
|--------|-------------|
| **HBR** | Standard CXL TLP (Host-Based Routing) — address-routed |
| **PBR** | HBR wrapped with a PBR routing header containing SPID + DPID |

At ingress the HBR packet is **encapsulated** → PBR.
At egress the PBR header is stripped (**decapsulated**) → HBR.

---

## ⚡ Quick-Fire Reference

| Topic | Answer |
|-------|--------|
| PID bit width | **12 bits** (values `0x000`–`0xFFF`) |
| DRT table size | **4096 entries** |
| Unassigned PID sentinel | **`0xFFF`** |
| Spec section for PBR | **CXL Spec Rev 4.0 §7.7.13** |
| Command to program routes | **`Set DRT — 5709h`** |
| Command to read switch caps | **`Identify PBR Switch — 5700h`** |
| HBR → PBR transition | **Encapsulation** at ingress |
| PBR → HBR transition | **Decapsulation** at egress |
| Does PID assign update DRT? | **No** — FM must call Set DRT separately |
| Max DRTs per switch | Reported by `num_drts` in Identify PBR Switch |
