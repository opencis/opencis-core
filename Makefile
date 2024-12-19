CONFIG_DIR = configs
CONFIG ?= 1vcs_4sld.yaml

ifeq ($(shell uname), Darwin)
	NPROC = $(shell sysctl -n hw.logicalcpu)
else
	NPROC = $$(nproc)
endif

test:
	poetry run python -O -m compileall -q opencis tests
	poetry run pytest --cov --cov-report=term-missing -n $(NPROC)
	rm -f *.bin

lint:
	poetry run pylint opencis
	poetry run pylint demos
	poetry run pylint tests

format:
	poetry run black opencis tests

clean:
	rm -rf *.bin logs *.log *.pcap
	find . | grep -E "(/__pycache__$$|\.pyc$$|\.pyo$$)" | xargs rm -rf
