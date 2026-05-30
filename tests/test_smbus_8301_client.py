#!/usr/bin/env python3
"""
tests/test_smbus_8301_client.py
================================
Standalone integration test client for FmSmbusMctpServer (port 8301).

Simulates a QEMU SMBus Slave sending CCI commands and a SMBus Master
receiving and validating the responses — exactly as it would happen
in a real QEMU host setup.

Run in a SEPARATE terminal while FM+Switch is already running:

    Terminal 1:  python run_pbr_env.py        (starts FM + Switch)
    Terminal 2:  python tests/test_smbus_8301_client.py

Options:
    --host   FM host  (default: 127.0.0.1)
    --port   SMBus server port  (default: 8301)
    --pec    Enable PEC verification on received response (default: off)
    --stop-on-error  Stop on first failure (default: continue)
"""

import sys
import socket
import struct
import argparse
import time

# ── Allow running without installing opencis ──────────────────────────────────
sys.path.insert(0, __file__.rsplit("tests", 1)[0])

# ── Framing helpers (inline so test runs with zero dependencies) ──────────────

SMBUS_MCTP_CMD   = 0x0F
MCTP_HDR_VER     = 0x01
MCTP_MSG_TYPE    = 0x7E   # CXL FM API
CCI_MSG_HDR_SIZE = 12

CCI_RETURN_CODE = {
    0x0000: "SUCCESS",
    0x0001: "BACKGROUND_COMMAND_STARTED",
    0x0002: "INVALID_INPUT",
    0x0003: "UNSUPPORTED",
    0x0004: "INTERNAL_ERROR",
    0x0005: "RETRY_REQUIRED",
    0x0006: "BUSY",
}

OPCODE_NAMES = {
    0x5700: "IDENTIFY_PBR_SWITCH",
    0x5704: "CONFIGURE_PID_ASSIGNMENT",
    0x5705: "GET_PID_BINDING",
    0x5706: "CONFIGURE_PID_BINDING",
    0x5708: "GET_DRT",
    0x5709: "SET_DRT",
    0x5800: "IDENTIFY_GAE",
}

# Colours
BOLD   = "\033[1m"
CYAN   = "\033[96m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
DIM    = "\033[2m"
RESET  = "\033[0m"


# ── CRC-8 PEC ────────────────────────────────────────────────────────────────

def crc8(data: bytes) -> int:
    crc = 0
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = ((crc << 1) ^ 0x07) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc


# ── Frame builder ─────────────────────────────────────────────────────────────

def build_smbus_request(
    opcode: int,
    cci_payload: bytes = b"",
    cci_tag: int = 0,
    msg_tag: int = 0,
    fm_i2c_addr: int = 0x10,
    dev_i2c_addr: int = 0x20,
    fm_eid: int = 0x08,
    dev_eid: int = 0x09,
) -> bytes:
    """
    Build a complete SMBus+MCTP request frame (DSP0237) for a CCI command.

    Frame layout:
      [0]  dest_slave_addr = fm_i2c_addr << 1 | 0   (write)
      [1]  command_code    = 0x0F
      [2]  byte_count      = total - 3 - 1 (PEC)
      [3]  src_slave_addr  = dev_i2c_addr << 1 | 1  (read bit)
      [4]  hdr_ver         = 0x01
      [5]  dest_eid        = fm_eid
      [6]  src_eid         = dev_eid
      [7]  flags           = SOM|EOM|TO=1|msg_tag
      [8]  msg_type        = 0x7E  (CXL FM API)
      [9..20]  CCI message header (12 bytes)
      [21+]    CCI payload
      [last]   PEC
    """
    # CCI message header (12 bytes)
    plen = len(cci_payload)
    cci_hdr = bytearray(12)
    cci_hdr[0]  = 0x00                      # message_category = REQUEST
    cci_hdr[1]  = cci_tag & 0xFF            # message_tag
    cci_hdr[2]  = 0x00                      # reserved
    cci_hdr[3]  = opcode & 0xFF             # opcode low
    cci_hdr[4]  = (opcode >> 8) & 0xFF     # opcode high
    cci_hdr[5]  = plen & 0xFF
    cci_hdr[6]  = (plen >> 8) & 0xFF
    cci_hdr[7]  = (plen >> 16) & 0x1F
    cci_hdr[8]  = 0x00                      # return_code (0 in request)
    cci_hdr[9]  = 0x00
    cci_hdr[10] = 0x00
    cci_hdr[11] = 0x00

    cci_msg = bytes(cci_hdr) + cci_payload

    # MCTP header flags: SOM=1, EOM=1, PktSeq=0, TO=1 (tag owner), msg_tag
    flags = 0xC0 | 0x08 | (msg_tag & 0x7)   # SOM|EOM|TO

    # Build frame body (byte[3] onwards, before PEC)
    body = bytes([
        (dev_i2c_addr << 1) | 0x01,   # src_slave_addr
        MCTP_HDR_VER,                  # hdr_ver
        fm_eid,                        # dest_eid
        dev_eid,                       # src_eid
        flags,                         # flags+tag
        MCTP_MSG_TYPE,                 # msg_type (CXL FM API)
    ]) + cci_msg

    dest_addr  = (fm_i2c_addr << 1) & 0xFE   # write direction
    byte_count = len(body)

    frame = bytes([dest_addr, SMBUS_MCTP_CMD, byte_count]) + body
    frame += bytes([crc8(frame)])
    return frame


# ── Response parser ───────────────────────────────────────────────────────────

def parse_smbus_response(raw: bytes, verify_pec: bool = False) -> dict:
    """
    Parse an SMBus+MCTP response frame.

    Response layout:
      [0]   byte_count
      [1]   fm_src_addr
      [2]   hdr_ver
      [3]   dest_eid
      [4]   src_eid
      [5]   flags
      [6]   msg_type
      [7..18]  CCI response header (12 bytes)
      [19+]    CCI response payload
      [last]   PEC
    """
    if len(raw) < 20:  # minimum: 7 hdr + 12 cci_hdr + 1 pec
        raise ValueError(f"Response too short: {len(raw)} bytes")

    byte_count   = raw[0]
    fm_src_addr  = raw[1]
    hdr_ver      = raw[2]
    dest_eid     = raw[3]
    src_eid      = raw[4]
    flags        = raw[5]
    msg_type     = raw[6] & 0x7F
    msg_tag      = flags & 0x7
    pec          = raw[-1]
    pec_computed = crc8(raw[:-1])
    pec_ok       = (pec == pec_computed)

    if verify_pec and not pec_ok:
        raise ValueError(f"Response PEC bad: got 0x{pec:02X}, computed 0x{pec_computed:02X}")

    # CCI response header at byte[7..18]
    cci_hdr = raw[7:19]
    category    = cci_hdr[0] & 0x0F   # should be 1 (RESPONSE)
    cci_tag     = cci_hdr[1]
    opcode      = int.from_bytes(cci_hdr[3:5], "little")
    plen_low    = int.from_bytes(cci_hdr[5:7], "little")
    plen_high   = cci_hdr[7] & 0x1F
    background  = (cci_hdr[7] >> 7) & 1
    payload_len = plen_low | (plen_high << 16)
    return_code = int.from_bytes(cci_hdr[8:10], "little")

    cci_payload = raw[19 : 19 + payload_len]

    return {
        "byte_count":   byte_count,
        "fm_src_addr":  fm_src_addr,
        "hdr_ver":      hdr_ver,
        "dest_eid":     dest_eid,
        "src_eid":      src_eid,
        "msg_tag":      msg_tag,
        "msg_type":     msg_type,
        "pec":          pec,
        "pec_ok":       pec_ok,
        "category":     category,
        "cci_tag":      cci_tag,
        "opcode":       opcode,
        "return_code":  return_code,
        "background":   background,
        "cci_payload":  cci_payload,
    }


# ── Hex dump ──────────────────────────────────────────────────────────────────

def hex_dump(data: bytes, indent: str = "    ") -> str:
    if not data:
        return f"{indent}(empty)"
    lines = []
    for i in range(0, len(data), 16):
        chunk = data[i:i+16]
        h = " ".join(f"{b:02X}" for b in chunk)
        a = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append(f"{indent}{i:04X}  {h:<47}  |{a}|")
    return "\n".join(lines)


# ── Send / receive one CCI transaction ───────────────────────────────────────

def do_transaction(
    sock: socket.socket,
    opcode: int,
    cci_payload: bytes,
    cci_tag: int,
    msg_tag: int,
    verify_pec: bool,
) -> dict:
    """Send one SMBus+MCTP request and receive the response."""
    frame = build_smbus_request(opcode, cci_payload, cci_tag, msg_tag)
    sock.sendall(frame)

    # Read response: first byte = byte_count
    bc_byte = _recv_exact(sock, 1)
    byte_count = bc_byte[0]
    rest = _recv_exact(sock, byte_count + 1)   # body + PEC
    raw_resp = bc_byte + rest

    return parse_smbus_response(raw_resp, verify_pec=verify_pec)


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("Server closed connection")
        buf += chunk
    return buf


# ── Print helpers ─────────────────────────────────────────────────────────────

def print_response(seq: int, opcode: int, resp: dict) -> None:
    opname = OPCODE_NAMES.get(opcode, f"0x{opcode:04X}")
    rc     = resp["return_code"]
    rcname = CCI_RETURN_CODE.get(rc, f"0x{rc:04X}")

    if rc == 0:
        rc_str = f"{GREEN}{rcname}{RESET}"
        status = f"{GREEN}✓ PASS{RESET}"
    elif rc == 1:
        rc_str = f"{YELLOW}{rcname}{RESET}"
        status = f"{YELLOW}✓ PASS (background){RESET}"
    else:
        rc_str = f"{RED}{rcname}{RESET}"
        status = f"{RED}✗ FAIL{RESET}"

    print(f"\n{BOLD}  ┌─ Response #{seq} ─ {opname} ──────────────────────────────{RESET}")
    print(f"  │  opcode      : {BOLD}0x{opcode:04X}{RESET}  ({opname})")
    print(f"  │  return_code : {rc_str}")
    print(f"  │  background  : {resp['background']}")
    print(f"  │  cci_tag     : {resp['cci_tag']}")
    print(f"  │  msg_tag     : {resp['msg_tag']}")
    print(f"  │  src_eid     : 0x{resp['src_eid']:02X}  (FM)")
    print(f"  │  dest_eid    : 0x{resp['dest_eid']:02X}  (device)")
    pec_str = f"{GREEN}OK{RESET}" if resp['pec_ok'] else f"{RED}BAD{RESET}"
    print(f"  │  pec         : 0x{resp['pec']:02X}  [{pec_str}]")
    print(f"  │  payload     : {len(resp['cci_payload'])} bytes")
    if resp["cci_payload"]:
        print(hex_dump(resp["cci_payload"], "  │    "))
    print(f"  └─ {status}")


# ── CCI command payload builders ──────────────────────────────────────────────

def payload_configure_pid_assignment(pid: int = 0x010, target_id: int = 1) -> bytes:
    """ConfigurePidAssignment: operation=SET, 1 entry, pid→target_id"""
    return struct.pack("<BBHH", 0, 0, 1, 0) + struct.pack("<HH", pid, target_id)


def payload_get_pid_binding(vcs_id: int = 0, vppb_id: int = 0) -> bytes:
    return struct.pack("<BB", vcs_id, vppb_id)


def payload_set_drt(pid: int = 0x010, port: int = 1) -> bytes:
    """SetDrt: 1 entry, PHYSICAL_PORT → port"""
    return struct.pack("<HBB", pid, 1, 0) + struct.pack("<BBH", 0, 0, port)


def payload_get_drt(pid: int = 0x010) -> bytes:
    return struct.pack("<H", pid)


def payload_configure_pid_binding(
    vcs_id: int = 0, vppb_id: int = 0, pid: int = 0x010, bind: bool = True
) -> bytes:
    op = 0 if bind else 1
    return struct.pack("<BBBBBH", op, vcs_id, vppb_id, 0, 0, pid)


# ── Main test sequence ────────────────────────────────────────────────────────

TESTS = [
    # (description, opcode, payload_fn_or_bytes)
    ("IDENTIFY_PBR_SWITCH",      0x5700, b""),
    ("CONFIGURE_PID_ASSIGNMENT", 0x5704, payload_configure_pid_assignment()),
    ("GET_PID_BINDING (before)", 0x5705, payload_get_pid_binding()),
    ("SET_DRT",                  0x5709, payload_set_drt()),
    ("GET_DRT",                  0x5708, payload_get_drt()),
    ("CONFIGURE_PID_BINDING",    0x5706, payload_configure_pid_binding()),
    ("GET_PID_BINDING (after)",  0x5705, payload_get_pid_binding()),
    ("IDENTIFY_GAE",             0x5800, b""),
]


def run_tests(host: str, port: int, verify_pec: bool, stop_on_error: bool) -> int:
    print(f"\n{BOLD}{CYAN}")
    print("╔══════════════════════════════════════════════════════════════╗")
    print("║  FmSmbusMctpServer Integration Test Client                  ║")
    print(f"║  Target: {host}:{port:<52}║")
    print("╚══════════════════════════════════════════════════════════════╝")
    print(RESET)

    print(f"Connecting to {host}:{port} ...", end=" ", flush=True)
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(10)
        sock.connect((host, port))
        print(f"{GREEN}OK{RESET}")
    except ConnectionRefusedError:
        print(f"{RED}REFUSED{RESET}")
        print(f"\n  {RED}Is the FM running?{RESET}  Start it with:")
        print("    python run_pbr_env.py\n")
        return 1
    except Exception as e:
        print(f"{RED}{e}{RESET}")
        return 1

    passed = failed = 0

    for seq, (desc, opcode, payload) in enumerate(TESTS, start=1):
        opname = OPCODE_NAMES.get(opcode, f"0x{opcode:04X}")
        print(f"\n{BOLD}── Test {seq}/{len(TESTS)}: {desc} ──────────────────────────────{RESET}")

        # Show what we are sending
        req_frame = build_smbus_request(opcode, payload, cci_tag=seq, msg_tag=seq % 8)
        print(f"{DIM}  TX frame ({len(req_frame)} bytes):{RESET}")
        print(hex_dump(req_frame, "    "))

        try:
            resp = do_transaction(
                sock, opcode, payload,
                cci_tag=seq, msg_tag=seq % 8,
                verify_pec=verify_pec,
            )
        except Exception as exc:
            print(f"{RED}  Error: {exc}{RESET}")
            failed += 1
            if stop_on_error:
                break
            continue

        print_response(seq, opcode, resp)

        rc = resp["return_code"]
        if rc == 0 or rc == 1:  # SUCCESS or BACKGROUND
            passed += 1
        else:
            failed += 1
            if stop_on_error:
                break

        time.sleep(0.05)  # small gap between commands

    sock.close()

    # ── Summary ───────────────────────────────────────────────────────────────
    total = passed + failed
    print(f"\n{BOLD}{CYAN}")
    print("╔══════════════════════════════════════════════════════════════╗")
    print(f"║  Results: {passed}/{total} tests passed"
          + " " * (50 - len(f"{passed}/{total} tests passed")) + "║")
    if failed == 0:
        print("║  ✓  ALL TESTS PASSED                                        ║")
    else:
        print(f"║  ✗  {failed} TEST(S) FAILED                                       ║")
    print("╚══════════════════════════════════════════════════════════════╝")
    print(RESET)

    return 0 if failed == 0 else 1


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="SMBus+MCTP CCI test client for FmSmbusMctpServer (port 8301)"
    )
    parser.add_argument("--host",          default="127.0.0.1", help="FM host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8301,        help="SMBus server port (default: 8301)")
    parser.add_argument("--pec",  action="store_true",           help="Verify PEC on response")
    parser.add_argument("--stop-on-error", action="store_true",  help="Stop on first failure")
    args = parser.parse_args()

    sys.exit(run_tests(args.host, args.port, args.pec, args.stop_on_error))


if __name__ == "__main__":
    main()
