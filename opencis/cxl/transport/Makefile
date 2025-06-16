
CYTHON_FILES = packet_base.pyx packet_structs.pyx
GENERATOR_SCRIPT = generate_packet_structs.py
GENERATED_STAMP = .generated
BUILD_SCRIPT = setup.py

# Default target
packets: $(GENERATED_STAMP)
	uv run setup.py build_ext --inplace

# Regenerate things if generator.py changed
$(GENERATED_STAMP): $(GENERATOR_SCRIPT)
	uv run generate_packet_structs.py
	@touch $(GENERATED_STAMP)

# Clean up build artifacts
clean:
	rm -rf *.so *.c __pycache__ packet_structs* build $(GENERATED_STAMP)
