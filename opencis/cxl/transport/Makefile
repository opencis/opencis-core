
CYTHON_FILES = packet_base.pyx packet_structs.pyx
GENERATOR_SCRIPT = generate_packet_structs.py
GENERATED_STAMP = .generated
BUILD_SCRIPT = setup.py

# Use uv if available, otherwise fall back to plain python.
# This makes the Makefile work both locally (uv installed) and in
# Docker containers where only plain python3/python may be present.
UV_BIN := $(shell command -v uv 2>/dev/null)
ifdef UV_BIN
    PYRUN = uv run --no-sync
else
    PYRUN = python3
endif

# Default target
packets: $(GENERATED_STAMP)
	$(PYRUN) setup.py build_ext --inplace

# Regenerate packet_structs.pyx if the generator script changed.
# NOTE: uv run --no-sync requires the venv to already exist.
#   Run 'uv sync' (or 'make sync') from the project root before 'make packets'.
$(GENERATED_STAMP): $(GENERATOR_SCRIPT)
	$(PYRUN) generate_packet_structs.py
	@touch $(GENERATED_STAMP)

# Clean up build artifacts
clean:
	rm -rf *.so *.c __pycache__ packet_structs* _packet_structs_cython* build $(GENERATED_STAMP)
