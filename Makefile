
ifeq ($(shell uname), Darwin)
	NPROC = $(shell sysctl -n hw.logicalcpu)
else
	NPROC = $(shell nproc)
endif

PACKET_DIR := opencis/cxl/transport
MAKEFLAGS += --no-print-directory
STAMP  := .generated

packets:
	@$(MAKE) -C $(PACKET_DIR) -q $(STAMP) || $(MAKE) -C $(PACKET_DIR) packets

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

clean:
	@echo "Cleaning up..."
	rm -rf *.bin logs *.log *.pcap
	find . | grep -E "(/__pycache__$$|\.pyc$$|\.pyo$$)" | xargs rm -rf
	@echo "If you want packets cleaned, run 'make clean-packets'"

clean-packets:
	make -C opencis/cxl/transport clean
