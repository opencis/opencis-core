#!/usr/bin/env python3
"""
docker/smoke_test_imports.py
----------------------------
Run inside Docker to verify all key modules (both control plane and data plane)
import cleanly in the pure-Python environment (no Cython .so files).

Usage:
    python docker/smoke_test_imports.py
    # exits 0 on success, 1 on any import failure
"""

import sys

MODULES = [
    # ── Core transport ─────────────────────────────────────────────────────
    ("opencis.cxl.transport.packet_structs",       "_GenCciBasePacket"),
    ("opencis.cxl.transport.cci_packets",          "CciMessagePacket"),
    ("opencis.cxl.transport.pbr_packets",          "PbrBasePacket"),

    # ── Control plane: MCTP / CCI ──────────────────────────────────────────
    ("opencis.cxl.component.mctp.mctp_cci_executor",   "MctpCciExecutor"),
    ("opencis.cxl.component.mctp.mctp_cci_api_client", "MctpCciApiClient"),
    ("opencis.cxl.component.mctp.fm_mctp_cci_server",  "FmMctpCciServer"),

    # ── Control plane: PBR switch CCI commands (0x5700–0x5709) ────────────
    ("opencis.cxl.component.pbr_switch_manager",       "PbrSwitchManager"),
    ("opencis.cxl.cci.fabric_manager.pbr_switch",      "IdentifyPbrSwitchCommand"),

    # ── Control plane: GAE/GFA CCI commands (0x5800–0x580B) ───────────────
    ("opencis.cxl.component.gae_manager",              "GaeManager"),
    ("opencis.cxl.cci.fabric_manager.gae",             "IdentifyGaeCommand"),
    ("opencis.cxl.cci.fabric_manager.gae",             "ProxyGfdMgmtCommand"),
    ("opencis.cxl.cci.fabric_manager.gae",             "GetProxyThreadStatusCommand"),
    ("opencis.cxl.cci.fabric_manager.gae",             "CancelProxyThreadCommand"),

    # ── Data plane: PBR router + HDM decoder ──────────────────────────────
    ("opencis.cxl.component.pbr_switch_router",        "PbrSwitchRouter"),
    ("opencis.cxl.component.pbr_hdm_decoder",          "PbrHdmDecoderManager"),
    ("opencis.cxl.component.hdm_decoder",              "PbrHdmDecoderManager"),

    # ── GFD device ────────────────────────────────────────────────────────
    ("opencis.cxl.device.cxl_gfd_device",              "CxlGfdDevice"),
    ("opencis.apps.generic_fabric_device",             "GenericFabricDevice"),

    # ── Top-level apps ────────────────────────────────────────────────────
    ("opencis.apps.cxl_switch",                        "CxlSwitch"),
    ("opencis.apps.fabric_manager",                    "CxlFabricManager"),
]

failures = []

for module, symbol in MODULES:
    try:
        mod = __import__(module, fromlist=[symbol])
        if not hasattr(mod, symbol):
            raise AttributeError(f"'{symbol}' not found in {module}")
        print(f"  OK  {module}.{symbol}")
    except Exception as exc:
        print(f"  ERR {module}.{symbol}: {exc}", file=sys.stderr)
        failures.append((module, symbol, str(exc)))

print()
if failures:
    print(f"FAILED: {len(failures)} import(s) broken:", file=sys.stderr)
    for mod, sym, err in failures:
        print(f"  - {mod}.{sym}: {err}", file=sys.stderr)
    sys.exit(1)
else:
    print(f"ALL {len(MODULES)} imports OK — pure-Python mode working")
    sys.exit(0)
