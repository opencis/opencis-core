ifeq ($(shell uname), Darwin)
	NPROC = $(shell sysctl -n hw.logicalcpu)
else
	NPROC = $$(nproc)
endif

test:
	uv run python -O -m compileall -q opencis tests
	uv run pytest --cov --cov-report=term-missing -n $(NPROC)
	rm -f *.bin

lint:
	uv run pylint opencis
	uv run pylint demos
	uv run pylint tests

format:
	uv run black opencis tests

clean:
	rm -rf *.bin logs *.log *.pcap
	find . | grep -E "(/__pycache__$$|\.pyc$$|\.pyo$$)" | xargs rm -rf
