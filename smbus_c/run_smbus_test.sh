#!/bin/bash
##
## run_smbus_test.sh — Full integration test
##
## Process layout (4 separate processes):
##
##   ┌─────────────────────────────────────────────────────────────┐
##   │  T1: Python FM+Switch  (run_pbr_env.py, FM on TCP:8300)    │
##   │  T2: C adapter         (two Unix sockets ↔ FM TCP:8300)    │
##   │  T3: C smbus_master    (connects to master socket, prints) │
##   │  T4: C smbus_slave     (connects to slave socket, sends)   │
##   └─────────────────────────────────────────────────────────────┘
##
## Usage:
##   cd opencis-core/smbus_c
##   bash run_smbus_test.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"

# Socket paths
SLAVE_SOCK="/tmp/smbus_slave.sock"
MASTER_SOCK="/tmp/smbus_master.sock"
BRIDGE_SOCK="/tmp/smbus_bridge.sock"   # Python-side bridge socket
FM_PORT=8300

# Colours
BOLD=$'\033[1m'; CYAN=$'\033[96m'; GREEN=$'\033[92m'
YELLOW=$'\033[93m'; RED=$'\033[91m'; RESET=$'\033[0m'

MASTER_LOG="/tmp/smbus_master_output.txt"

cleanup() {
    echo ""
    echo "${BOLD}Cleaning up...${RESET}"
    kill "$ADAPTER_PID" 2>/dev/null && echo "  Stopped C adapter"
    kill "$MASTER_PID"  2>/dev/null && echo "  Stopped C master"
    kill "$PY_PID"      2>/dev/null && echo "  Stopped Python FM"
    rm -f "$SLAVE_SOCK" "$MASTER_SOCK" "$BRIDGE_SOCK" 2>/dev/null
}
trap cleanup EXIT

echo "${BOLD}${CYAN}"
echo "╔══════════════════════════════════════════════════════════╗"
echo "║  SMBus-MCTP Full-Stack Integration Test                 ║"
echo "║  Slave → Adapter → FM+Switch → Master                   ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo "${RESET}"

## ── Step 1: Build ──────────────────────────────────────────────────────
echo "${BOLD}── Step 1: Build C binaries ──────────────────────────────${RESET}"
cd "$SCRIPT_DIR"
make clean -s
make all
echo "${GREEN}Build OK${RESET}"

## ── Step 2: C unit tests ──────────────────────────────────────────────
echo ""
echo "${BOLD}── Step 2: C unit tests (mctp_packet.h) ─────────────────${RESET}"
./test_mctp_packet
echo "${GREEN}Unit tests passed${RESET}"

## ── Step 3: Start Python FM+Switch ────────────────────────────────────
echo ""
echo "${BOLD}── Step 3: Start Python PBR environment ─────────────────${RESET}"
cd "$REPO_DIR"

python run_pbr_env.py \
    --smbus-bridge "$BRIDGE_SOCK" \
    --smbus-fm-port "$FM_PORT" &
PY_PID=$!
echo "  Python PID: $PY_PID"

# Wait for bridge socket (signals FM + Python bridge are ready)
echo "  Waiting for FM to start..."
WAIT=0
while [ ! -S "$BRIDGE_SOCK" ] && [ $WAIT -lt 30 ]; do
    sleep 1; WAIT=$((WAIT+1)); echo -n "."; done
echo ""
[ -S "$BRIDGE_SOCK" ] || { echo "${RED}FM did not start in 30s${RESET}"; exit 1; }
echo "${GREEN}Python FM ready${RESET}"

## ── Step 4: Start C adapter ────────────────────────────────────────────
echo ""
echo "${BOLD}── Step 4: Start C adapter (two-socket mode) ────────────${RESET}"
cd "$SCRIPT_DIR"
./smbus_mctp_adapter "$SLAVE_SOCK" "$MASTER_SOCK" 127.0.0.1 "$FM_PORT" -v &
ADAPTER_PID=$!
sleep 1   # let adapter bind both sockets
[ -S "$MASTER_SOCK" ] || { echo "${RED}Adapter sockets not created${RESET}"; exit 1; }
echo "${GREEN}Adapter ready (slave: $SLAVE_SOCK, master: $MASTER_SOCK)${RESET}"

## ── Step 5: Start SMBus Master (FIRST — must be ready before slave) ───
echo ""
echo "${BOLD}── Step 5: Start SMBus Master (receives responses) ───────${RESET}"
./smbus_master "$MASTER_SOCK" > "$MASTER_LOG" 2>&1 &
MASTER_PID=$!
sleep 0.5   # let master connect to adapter
echo "${GREEN}Master listening (PID $MASTER_PID)${RESET}"
echo "  Output will be shown after slave completes."

## ── Step 6: Run SMBus Slave (sends CCI commands) ──────────────────────
echo ""
echo "${BOLD}── Step 6: Run SMBus Slave (sends 9 CCI commands) ────────${RESET}"
set +e
./smbus_slave "$SLAVE_SOCK"
SLAVE_RC=$?
set -e

## ── Step 7: Wait for master to finish receiving ────────────────────────
echo ""
echo "${BOLD}── Step 7: Collecting master output ──────────────────────${RESET}"
# Give master 3s to receive and print all responses
sleep 3
kill "$MASTER_PID" 2>/dev/null
wait "$MASTER_PID" 2>/dev/null || true

## ── Step 8: Print master output ────────────────────────────────────────
echo ""
echo "${BOLD}${CYAN}══════ SMBus Master Response Output ══════${RESET}"
cat "$MASTER_LOG"
echo "${BOLD}${CYAN}══════════════════════════════════════════${RESET}"

## ── Step 9: Result ─────────────────────────────────────────────────────
echo ""
if [ $SLAVE_RC -eq 0 ]; then
    echo "${BOLD}${GREEN}"
    echo "╔══════════════════════════════════════════════╗"
    echo "║  ✓  PASS — All integration tests succeeded  ║"
    echo "╚══════════════════════════════════════════════╝"
    echo "${RESET}"
else
    echo "${BOLD}${RED}"
    echo "╔══════════════════════════════════════════════╗"
    echo "║  ✗  FAIL — slave exited with code $SLAVE_RC           ║"
    echo "╚══════════════════════════════════════════════╝"
    echo "${RESET}"
fi

exit $SLAVE_RC
