##
## Makefile — SMBus-MCTP C code  (two-socket Slave + Master model)
##
## Targets:
##   make all               build everything
##   make test              build and run C unit tests
##   make clean             remove build artefacts
##

CC      := gcc
CFLAGS  := -O2 -Wall -Wextra -Wpedantic -std=c11 -I.
LDFLAGS :=

.PHONY: all test clean

all: smbus_mctp_adapter smbus_slave smbus_master test_mctp_packet

# ── Adapter (two-socket: slave sock + master sock) ──────────────────────
smbus_mctp_adapter: smbus_mctp_adapter.c smbus_mctp_adapter.h mctp_packet.h
	$(CC) $(CFLAGS) -o $@ smbus_mctp_adapter.c $(LDFLAGS)
	@echo "[build] smbus_mctp_adapter OK"

# ── SMBus Slave (sends CCI requests only) ──────────────────────────────
smbus_slave: smbus_slave.c mctp_packet.h smbus_mctp_adapter.h
	$(CC) $(CFLAGS) -o $@ smbus_slave.c $(LDFLAGS)
	@echo "[build] smbus_slave OK"

# ── SMBus Master (receives + prints CCI responses) ──────────────────────
smbus_master: smbus_master.c mctp_packet.h smbus_mctp_adapter.h
	$(CC) $(CFLAGS) -o $@ smbus_master.c $(LDFLAGS)
	@echo "[build] smbus_master OK"

# ── Unit tests (mctp_packet.h wire format) ─────────────────────────────
test_mctp_packet: test_mctp_packet.c mctp_packet.h
	$(CC) $(CFLAGS) -o $@ test_mctp_packet.c $(LDFLAGS)
	@echo "[build] test_mctp_packet OK"

test: test_mctp_packet
	@echo ""
	@echo "Running unit tests..."
	./test_mctp_packet

# ── Clean ──────────────────────────────────────────────────────────────
clean:
	rm -f smbus_mctp_adapter smbus_slave smbus_master test_mctp_packet
	rm -f /tmp/smbus_slave.sock /tmp/smbus_master.sock
	@echo "[clean] done"
