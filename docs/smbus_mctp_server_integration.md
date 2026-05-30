# SMBus+MCTP Integration Guide — Connecting QEMU Host to FmSmbusMctpServer

**Version:** 1.0  
**Date:** May 2026  
**Branch:** `v0.5-dev`  
**Spec reference:** DMTF DSP0237 v1.2.0 (MCTP over SMBus/I2C)

---

## Overview

This guide explains how to integrate a QEMU SMBus Slave/Master pair with the
`FmSmbusMctpServer` running on TCP port **8301** inside the opencis FM process.

```
QEMU Host Process
┌──────────────────────────────────────────────────────────────────────┐
│                                                                      │
│  SMBus Slave (CXL device emulation)                                  │
│   └─ sends CCI commands as SMBus+MCTP frames → TCP:8301             │
│                                                                      │
│  SMBus Master (Host controller emulation)                            │
│   └─ receives SMBus+MCTP response frames ← TCP:8301                 │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
                              │ TCP socket
                              ▼ port 8301
┌──────────────────────────────────────────────────────────────────────┐
│  opencis FM (run_pbr_env.py)                                         │
│                                                                      │
│  FmSmbusMctpServer (port 8301)                                       │
│   ├─ Parses DSP0237 SMBus frame                                      │
│   ├─ Extracts CCI opcode + payload                                   │
│   ├─ Forwards to switch via MctpCciApiClient (port 8100)            │
│   ├─ Gets (return_code, response_payload) from switch                │
│   └─ Wraps in DSP0237 response frame → sends to QEMU Master         │
│                                                                      │
│  CxlSwitch + PbrSwitchManager (port 8100)                           │
│   └─ executes actual CCI command, returns result                     │
└──────────────────────────────────────────────────────────────────────┘
```

---

## Port Map

| Port | Component | Description |
|------|-----------|-------------|
| 8100 | `MctpConnectionManager` | Switch ↔ FM internal MCTP |
| 8200 | `FabricManagerSocketIoServer` | FM CLI (SocketIO) |
| **8300** | `FmMctpCciServer` | External MCTP (opencis CciPayloadPacket format) |
| **8301** | `FmSmbusMctpServer` | **QEMU SMBus Slave/Master (DSP0237 format)** |
| 8700 | `ShortMsgConn` | Host FM connection |

---

## Packet Wire Format (DSP0237)

### REQUEST frame  (QEMU SMBus Slave → FM port 8301)

```
Byte  0: dest_slave_addr  = FM_I2C_ADDR << 1          e.g. 0x20 for addr 0x10
Byte  1: command_code     = 0x0F                        (MCTP over SMBus, fixed)
Byte  2: byte_count       = total_frame_len - 3 - 1    (excludes first 3 bytes + PEC)
Byte  3: src_slave_addr   = DEV_I2C_ADDR << 1 | 0x01   e.g. 0x41 for addr 0x20
Byte  4: hdr_ver          = 0x01                        (MCTP version, fixed)
Byte  5: dest_eid         = FM_EID                      e.g. 0x08
Byte  6: src_eid          = DEVICE_EID                  e.g. 0x09
Byte  7: flags            = SOM(1)|EOM(1)|PktSeq(2)|TO(1)|MsgTag(3)
                            = 0xC8 | msg_tag  (SOM=1,EOM=1,TO=1,tag)
Byte  8: msg_type         = 0x7E                        (CXL FM API, no IC bit)
─── CCI Message Header (12 bytes) ───────────────────────────────────
Byte  9: message_category[3:0] | rsvd[7:4]  = 0x00     (REQUEST=0)
Byte 10: message_tag                          = 0x00..0xFF
Byte 11: reserved                             = 0x00
Byte 12: opcode_low                           e.g. 0x00 for IDENTIFY_PBR_SWITCH
Byte 13: opcode_high                          e.g. 0x57 for IDENTIFY_PBR_SWITCH
Byte 14: payload_length_low_low               = 0x00 (if no payload)
Byte 15: payload_length_low_high              = 0x00
Byte 16: payload_length_high[4:0]|rsvd|bg    = 0x00
Byte 17: return_code_low                      = 0x00 (in request)
Byte 18: return_code_high                     = 0x00
Byte 19: vendor_status_low                    = 0x00
Byte 20: vendor_status_high                   = 0x00
─── CCI Payload (0..N bytes) ────────────────────────────────────────
Bytes 21..: CCI command payload (if any)
─── PEC ─────────────────────────────────────────────────────────────
Last byte: PEC = CRC-8 over all preceding bytes (polynomial 0x07)
```

**Minimum frame size (no CCI payload): 22 bytes**

### RESPONSE frame  (FM port 8301 → QEMU SMBus Master)

```
Byte  0: byte_count       = total_frame_len - 1 - 1    (excludes byte_count + PEC)
Byte  1: fm_src_addr      = FM_I2C_ADDR << 1 | 0x01    e.g. 0x21
Byte  2: hdr_ver          = 0x01
Byte  3: dest_eid         = DEVICE_EID                  (swapped from request)
Byte  4: src_eid          = FM_EID
Byte  5: flags            = SOM(1)|EOM(1)|PktSeq(2)|TO=0|MsgTag(3)
                            = 0xC0 | msg_tag  (same tag as request)
Byte  6: msg_type         = 0x7E                        (same as request)
─── CCI Response Header (12 bytes) ──────────────────────────────────
Byte  7: message_category = 0x01                        (RESPONSE=1)
Byte  8: message_tag                                    (same as request)
Byte  9: reserved         = 0x00
Byte 10: opcode_low                                     (echoed from request)
Byte 11: opcode_high
Byte 12: resp_payload_length_low
Byte 13: resp_payload_length_high
Byte 14: resp_payload_length_high2 | background_bit
Byte 15: return_code_low                                (0=SUCCESS, 1=BG, 2=INVALID...)
Byte 16: return_code_high
Byte 17: vendor_status_low
Byte 18: vendor_status_high
─── CCI Response Payload ────────────────────────────────────────────
Bytes 19..: response data from switch
─── PEC ─────────────────────────────────────────────────────────────
Last byte: PEC = CRC-8 over all preceding bytes
```

---

## CRC-8 PEC Calculation

The PEC uses CRC-8 with polynomial **0x07** (x⁸ + x² + x + 1):

```c
/* C implementation */
uint8_t crc8_smbus(const uint8_t *data, size_t len) {
    uint8_t crc = 0;
    for (size_t i = 0; i < len; i++) {
        crc ^= data[i];
        for (int j = 0; j < 8; j++) {
            if (crc & 0x80)
                crc = (crc << 1) ^ 0x07;
            else
                crc <<= 1;
        }
    }
    return crc;
}
```

```python
# Python implementation
def crc8_smbus(data: bytes) -> int:
    crc = 0
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = ((crc << 1) ^ 0x07) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc
```

---

## Step-by-Step Integration

### Step 1 — Start the FM and Switch

```bash
# Terminal 1: start the full PBR environment
cd /workspace/opencis-core
python run_pbr_env.py

# You should see these lines in the log:
# FM MCTP CCI server (port 8300) bridged to FM CLI path via shared MctpCciApiClient
# FM SMBus+MCTP server (port 8301, i2c_addr=0x10) bridged to FM CLI path via shared MctpCciApiClient
```

### Step 2 — Verify port 8301 is open

```bash
# From QEMU host
nc -zv 127.0.0.1 8301
# Expected: Connection to 127.0.0.1 8301 port [tcp/*] succeeded!
```

### Step 3 — Run the standalone test client

```bash
# Terminal 2: standalone test (simulates QEMU SMBus Slave)
cd /workspace/opencis-core
python tests/test_smbus_8301_client.py

# Options:
python tests/test_smbus_8301_client.py --host 127.0.0.1 --port 8301
python tests/test_smbus_8301_client.py --pec              # verify PEC on responses
python tests/test_smbus_8301_client.py --stop-on-error    # stop on first failure
```

---

## Integrating from QEMU C Code

### Frame builder (`smbus_mctp_client.c`)

```c
#include <stdint.h>
#include <string.h>

#define SMBUS_MCTP_CMD   0x0F
#define MCTP_HDR_VER     0x01
#define MCTP_MSG_TYPE    0x7E   /* CXL FM API */
#define CCI_HDR_SIZE     12

/* CRC-8 PEC (polynomial 0x07) */
static uint8_t crc8_smbus(const uint8_t *data, size_t len) {
    uint8_t crc = 0;
    for (size_t i = 0; i < len; i++) {
        crc ^= data[i];
        for (int j = 0; j < 8; j++)
            crc = (crc & 0x80) ? (crc << 1) ^ 0x07 : crc << 1;
    }
    return crc;
}

/*
 * build_smbus_mctp_request() — build a DSP0237 request frame.
 *
 * @buf        output buffer (must be >= cci_payload_len + 22 bytes)
 * @opcode     CCI command opcode (e.g. 0x5700 = IDENTIFY_PBR_SWITCH)
 * @cci_payload  CCI command payload bytes (NULL if none)
 * @payload_len  length of cci_payload
 * @cci_tag    CCI message tag (0..255)
 * @msg_tag    MCTP message tag (0..7)
 * @fm_addr    FM 7-bit I2C address (default 0x10)
 * @dev_addr   device 7-bit I2C address (default 0x20)
 * @fm_eid     FM endpoint ID (default 0x08)
 * @dev_eid    device endpoint ID (default 0x09)
 *
 * returns total frame length
 */
int build_smbus_mctp_request(
    uint8_t *buf,
    uint16_t opcode,
    const uint8_t *cci_payload, uint16_t payload_len,
    uint8_t cci_tag, uint8_t msg_tag,
    uint8_t fm_addr, uint8_t dev_addr,
    uint8_t fm_eid, uint8_t dev_eid)
{
    /* CCI message header (12 bytes) */
    uint8_t cci_hdr[CCI_HDR_SIZE] = {0};
    cci_hdr[0] = 0x00;                  /* category = REQUEST */
    cci_hdr[1] = cci_tag;
    cci_hdr[2] = 0x00;                  /* reserved */
    cci_hdr[3] = (uint8_t)(opcode);     /* opcode LE */
    cci_hdr[4] = (uint8_t)(opcode >> 8);
    cci_hdr[5] = (uint8_t)(payload_len);
    cci_hdr[6] = (uint8_t)(payload_len >> 8);
    /* cci_hdr[7..11] = 0 */

    /* MCTP flags: SOM=1, EOM=1, TO=1 (tag owner), msg_tag */
    uint8_t flags = 0xC8 | (msg_tag & 0x07);

    /* Build body (everything from src_slave_addr to end of CCI payload) */
    uint8_t body[256];
    int bi = 0;
    body[bi++] = (dev_addr << 1) | 0x01;  /* src_slave_addr */
    body[bi++] = MCTP_HDR_VER;
    body[bi++] = fm_eid;                   /* dest_eid */
    body[bi++] = dev_eid;                  /* src_eid */
    body[bi++] = flags;
    body[bi++] = MCTP_MSG_TYPE;
    memcpy(body + bi, cci_hdr, CCI_HDR_SIZE);
    bi += CCI_HDR_SIZE;
    if (cci_payload && payload_len > 0) {
        memcpy(body + bi, cci_payload, payload_len);
        bi += payload_len;
    }

    /* Assemble frame */
    int fi = 0;
    buf[fi++] = (fm_addr << 1) & 0xFE;   /* dest_slave_addr (write) */
    buf[fi++] = SMBUS_MCTP_CMD;            /* command_code = 0x0F */
    buf[fi++] = (uint8_t)bi;              /* byte_count */
    memcpy(buf + fi, body, bi);
    fi += bi;

    /* Append PEC */
    buf[fi] = crc8_smbus(buf, fi);
    fi++;

    return fi;  /* total frame length */
}
```

### Response parser (`smbus_mctp_client.c` continued)

```c
typedef struct {
    uint8_t  byte_count;
    uint8_t  fm_src_addr;
    uint8_t  dest_eid;
    uint8_t  src_eid;
    uint8_t  msg_tag;
    uint8_t  msg_type;
    uint8_t  pec;
    int      pec_ok;
    /* CCI response fields */
    uint16_t opcode;
    uint8_t  cci_tag;
    uint16_t return_code;
    int      background;
    uint8_t  payload[256];
    uint16_t payload_len;
} SmbusMctpResponse;

int parse_smbus_mctp_response(const uint8_t *buf, int len, SmbusMctpResponse *r) {
    if (len < 20) return -1;  /* too short */

    r->byte_count   = buf[0];
    r->fm_src_addr  = buf[1];
    /* buf[2] = hdr_ver */
    r->dest_eid     = buf[3];
    r->src_eid      = buf[4];
    r->msg_tag      = buf[5] & 0x07;
    r->msg_type     = buf[6] & 0x7F;
    r->pec          = buf[len - 1];
    r->pec_ok       = (crc8_smbus(buf, len - 1) == r->pec);

    /* CCI response header starts at buf[7] */
    const uint8_t *cci = buf + 7;
    r->opcode       = (uint16_t)(cci[3]) | ((uint16_t)(cci[4]) << 8);
    r->cci_tag      = cci[1];
    r->return_code  = (uint16_t)(cci[8]) | ((uint16_t)(cci[9]) << 8);
    r->background   = (cci[7] >> 7) & 1;
    r->payload_len  = (uint16_t)(cci[5]) | ((uint16_t)(cci[6]) << 8);

    if (r->payload_len > 0 && r->payload_len <= sizeof(r->payload)) {
        memcpy(r->payload, buf + 19, r->payload_len);
    }
    return 0;
}
```

### TCP client wrapper

```c
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <arpa/inet.h>

#define FM_HOST  "127.0.0.1"
#define FM_PORT  8301

/* Connect to FmSmbusMctpServer */
int smbus_connect(void) {
    int fd = socket(AF_INET, SOCK_STREAM, 0);
    if (fd < 0) return -1;

    struct sockaddr_in addr = {
        .sin_family = AF_INET,
        .sin_port   = htons(FM_PORT),
    };
    inet_pton(AF_INET, FM_HOST, &addr.sin_addr);

    if (connect(fd, (struct sockaddr *)&addr, sizeof(addr)) < 0) {
        close(fd);
        return -1;
    }
    return fd;
}

/* Send one request, receive one response */
int smbus_transaction(
    int fd,
    uint16_t opcode,
    const uint8_t *req_payload, uint16_t req_len,
    SmbusMctpResponse *resp,
    uint8_t cci_tag, uint8_t msg_tag)
{
    uint8_t frame[512];
    int flen = build_smbus_mctp_request(
        frame, opcode, req_payload, req_len,
        cci_tag, msg_tag,
        0x10, 0x20,   /* FM addr=0x10, dev addr=0x20 */
        0x08, 0x09    /* FM EID=0x08, dev EID=0x09   */
    );

    if (write(fd, frame, flen) != flen) return -1;

    /* Read response: first byte = byte_count */
    uint8_t bc;
    if (read(fd, &bc, 1) != 1) return -1;

    uint8_t rest[512];
    int to_read = bc + 1;  /* body + PEC */
    int got = 0;
    while (got < to_read) {
        int n = read(fd, rest + got, to_read - got);
        if (n <= 0) return -1;
        got += n;
    }

    uint8_t resp_buf[512];
    resp_buf[0] = bc;
    memcpy(resp_buf + 1, rest, got);
    return parse_smbus_mctp_response(resp_buf, 1 + got, resp);
}
```

### Full example — IDENTIFY_PBR_SWITCH

```c
int main(void) {
    int fd = smbus_connect();
    if (fd < 0) {
        fprintf(stderr, "Cannot connect to FM port 8301\n");
        return 1;
    }
    printf("Connected to FM SMBus+MCTP server\n");

    SmbusMctpResponse resp;
    int rc = smbus_transaction(
        fd,
        0x5700,    /* IDENTIFY_PBR_SWITCH */
        NULL, 0,   /* no CCI payload */
        &resp,
        1, 1       /* cci_tag=1, msg_tag=1 */
    );

    if (rc < 0) {
        fprintf(stderr, "Transaction failed\n");
        close(fd);
        return 1;
    }

    printf("opcode      : 0x%04X\n", resp.opcode);
    printf("return_code : 0x%04X (%s)\n",
           resp.return_code,
           resp.return_code == 0 ? "SUCCESS" :
           resp.return_code == 1 ? "BACKGROUND" : "ERROR");
    printf("pec         : 0x%02X (%s)\n",
           resp.pec, resp.pec_ok ? "OK" : "BAD");
    printf("payload_len : %u bytes\n", resp.payload_len);

    close(fd);
    return resp.return_code == 0 ? 0 : 1;
}
```

---

## QEMU Device Model Integration

If you are building a QEMU device model (`smbus_cxl_ep.c`) that talks
to the FM over TCP, here is the recommended architecture:

```
QEMU device model
├── smbus_cxl_ep_write_data()   ← called by QEMU SMBus Master
│   └─ build_smbus_mctp_request()
│   └─ send to TCP:8301
│
├── smbus_cxl_ep_read_byte()    ← called by QEMU SMBus Master (reads response)
│   └─ recv response bytes one at a time (or buffer full response)
│
└── smbus_cxl_ep_realize()      ← device init
    └─ smbus_connect()           ← open persistent TCP connection to FM
```

**Connection lifecycle:**
- Open one persistent TCP connection per CXL device instance on `realize()`
- Reuse the connection for all CCI transactions (the server handles one
  complete request/response per TCP read/write cycle)
- Close the connection on `unrealize()`

---

## Supported CCI Commands

| Opcode | Command | Payload | Response |
|--------|---------|---------|----------|
| `0x5700` | `IDENTIFY_PBR_SWITCH` | none | switch capabilities |
| `0x5704` | `CONFIGURE_PID_ASSIGNMENT` | pid+target entries | SUCCESS |
| `0x5705` | `GET_PID_BINDING` | vcs_id, vppb_id | binding info |
| `0x5706` | `CONFIGURE_PID_BINDING` | op+vcs+vppb+pid | BACKGROUND |
| `0x5708` | `GET_DRT` | pid | DRT entry |
| `0x5709` | `SET_DRT` | pid+entry | SUCCESS |
| `0x5800` | `IDENTIFY_GAE` | none | GAE capabilities |

---

## What FmSmbusMctpServer Prints on Receipt

Every packet received on port 8301 is printed to stdout **before execution**:

```
════════════════════════════════════════════════════════════
  SMBus+MCTP RX  [22 bytes]  port 8301
════════════════════════════════════════════════════════════
  Raw bytes:
    0000  20 0F 12 21 01 08 09 C9 7E 00 01 00 00 57 00 00  | !.....~....W..
    0010  00 00 00 00 00 XX                                |......|
  ── SMBus Header ──────────────────────────────────────
    dest_slave_addr : 0x20  (i2c addr 0x10, dir=WRITE)
    command_code    : 0x0F  (MCTP)
    byte_count      : 18
    src_slave_addr  : 0x21  (i2c addr 0x10)
  ── MCTP Transport Header ─────────────────────────────
    hdr_ver         : 0x01
    dest_eid        : 0x08
    src_eid         : 0x09
    SOM             : 1
    EOM             : 1
    msg_tag         : 1
  ── MCTP Message Type ─────────────────────────────────
    IC              : 0
    msg_type        : 0x7E  (CXL_FM_API)
  ── CCI Message Header ────────────────────────────────
    message_category: 0  (REQUEST)
    message_tag     : 1
    command_opcode  : 0x5700  (IDENTIFY_PBR_SWITCH)
    payload_length  : 0 bytes
  ── PEC (CRC-8) ───────────────────────────────────────
    pec             : 0xXX  [OK]
────────────────────────────────────────────────────────────

  → TX response: opcode=0x5700 rc=SUCCESS bg=False payload=4B frame=25B
```

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `Connection refused` on port 8301 | FM not running | Start `python run_pbr_env.py` first |
| `Parse ERROR: Bad SMBus command code` | Byte[1] ≠ 0x0F | Set command_code = 0x0F in frame |
| `Parse ERROR: SMBus request too short` | Frame < 22 bytes | Add missing CCI header bytes |
| `return_code = UNSUPPORTED (0x0003)` | Switch not connected yet | Wait for FM to finish startup |
| `return_code = INVALID_INPUT (0x0002)` | Bad CCI payload | Check payload format for opcode |
| Response PEC bad | Wrong byte_count in response | FM bug — report with tcpdump hex |
| Switch logs show `garbage opcode` | packet_reader partial read | Update to latest `v0.5-dev` (fix applied) |
| Server hangs after bad packet | queue deadlock | Update to latest `v0.5-dev` (fix applied) |

---

## Files Reference

| File | Purpose |
|------|---------|
| [`opencis/cxl/component/mctp/smbus_mctp_framing.py`](../opencis/cxl/component/mctp/smbus_mctp_framing.py) | DSP0237 frame parser + builder + CRC-8 |
| [`opencis/cxl/component/mctp/fm_smbus_mctp_server.py`](../opencis/cxl/component/mctp/fm_smbus_mctp_server.py) | `FmSmbusMctpServer` class (port 8301) |
| [`opencis/apps/fabric_manager.py`](../opencis/apps/fabric_manager.py) | Wires both servers into `CxlFabricManager` |
| [`opencis/cxl/component/mctp/mctp_packet_reader.py`](../opencis/cxl/component/mctp/mctp_packet_reader.py) | Bug fix: `readexactly()` + size=0 guard |
| [`opencis/cxl/component/mctp/mctp_packet_processor.py`](../opencis/cxl/component/mctp/mctp_packet_processor.py) | Bug fix: queue deadlock unblock |
| [`tests/test_smbus_8301_client.py`](../tests/test_smbus_8301_client.py) | Standalone integration test client |
