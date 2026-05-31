
ifeq ($(shell uname), Darwin)
	NPROC = $(shell sysctl -n hw.logicalcpu)
else
	NPROC = $(shell nproc)
endif

PACKET_DIR := opencis/cxl/transport
MAKEFLAGS += --no-print-directory
STAMP  := .generated

# ── Setup ────────────────────────────────────────────────────────────────────

# Sync uv environment (must be done once before 'make test' or 'make packets').
# In Docker: run 'make sync' first, then 'make test'.
sync:
	uv python pin 3.13
	uv sync

# One-shot setup for a fresh Docker container:
#   docker run --rm -v $(pwd):/work -w /work <image> bash -c "make docker-setup && make test"
docker-setup: sync packets

# ── Build ────────────────────────────────────────────────────────────────────

packets:
	@$(MAKE) -C $(PACKET_DIR) -q $(STAMP) || $(MAKE) -C $(PACKET_DIR) packets

# ── Test / Lint ──────────────────────────────────────────────────────────────

test:
	@$(MAKE) -C $(PACKET_DIR) -q $(STAMP) || $(MAKE) -C $(PACKET_DIR) packets
	uv run python -O -m compileall -q opencis tests
	uv run pytest --cov --cov-report=term-missing -n $(NPROC)
	rm -f *.bin

lint:
	@$(MAKE) -C $(PACKET_DIR) -q $(STAMP) || $(MAKE) -C $(PACKET_DIR) packets
	uv run pylint opencis
	uv run pylint demos
	uv run pylint tests

format:
	uv run black opencis tests demos

# ── Clean ────────────────────────────────────────────────────────────────────

clean:
	@echo "Cleaning up..."
	rm -rf *.bin logs *.log *.pcap
	find . | grep -E "(/__pycache__$$|\.pyc$$|\.pyo$$)" | xargs rm -rf
	@echo "If you want packets cleaned, run 'make clean-packets'"

clean-packets:
	make -C opencis/cxl/transport clean

