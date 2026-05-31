
CYTHON_FILES = packet_base.pyx packet_structs.pyx
GENERATOR_SCRIPT = generate_packet_structs.py
GENERATED_STAMP = .generated
BUILD_SCRIPT = setup.py

# generate_packet_structs.py only uses Python stdlib (pathlib, importlib, sys).
# It does NOT need the uv venv — plain python3 works everywhere including
# fresh Docker containers before 'uv sync' has been run.
#
# setup.py (Cython build) DOES need the venv (needs Cython package).
# Use 'uv run --no-sync' for that step — venv must already exist.
UV_BIN := $(shell command -v uv 2>/dev/null)
ifdef UV_BIN
    CYTHON_RUN = uv run --no-sync
else
    CYTHON_RUN = python3
endif

# Default target
packets: $(GENERATED_STAMP)
	$(CYTHON_RUN) setup.py build_ext --inplace

# Regenerate packet_structs.pyx whenever the generator script changes.
# Runs with plain python3 — no venv needed.
$(GENERATED_STAMP): $(GENERATOR_SCRIPT)
	python3 $(GENERATOR_SCRIPT)
	@touch $(GENERATED_STAMP)

# Clean up build artifacts
clean:
	rm -rf *.so *.c __pycache__ packet_structs* _packet_structs_cython* build $(GENERATED_STAMP)
