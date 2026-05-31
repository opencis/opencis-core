"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

import logging
import pytest

from opencis.util.logger import logger as opencis_logger

_log = logging.getLogger("tests.conftest")

# Standard logger that pytest's log_cli will capture
_opencis_std_log = logging.getLogger("opencis")


# ---------------------------------------------------------------------------
# Bridge: forward opencis MyLogger → standard logging → pytest log_cli
#
# MyLogger writes to its own StreamHandler on sys.stdout and is NOT part of
# Python's logging hierarchy.  BridgeHandler is attached to MyLogger so every
# record it emits is also re-emitted through the standard 'opencis' logger,
# which pytest's log_cli plugin CAN intercept and display.
# ---------------------------------------------------------------------------

class _BridgeHandler(logging.Handler):
    """Re-emit records from opencis MyLogger into standard Python logging."""

    def emit(self, record: logging.LogRecord) -> None:
        # Re-emit under the 'opencis.<original-name>' namespace so pytest
        # can show the source module in the live-log column.
        target_name = f"opencis.{record.name}" if record.name != "mylogger" else "opencis"
        std_logger = logging.getLogger(target_name)
        # Avoid infinite loops: only forward if the standard logger has handlers
        # above WARNING (i.e. pytest's caplog/log_cli is active).
        std_logger.log(record.levelno, record.getMessage())


def _install_bridge() -> None:
    """Attach the bridge handler to opencis MyLogger (once per session)."""
    # Check if already installed to be idempotent across multiple conftest loads
    for h in opencis_logger.handlers:
        if isinstance(h, _BridgeHandler):
            return
    bridge = _BridgeHandler()
    bridge.setLevel(logging.DEBUG)
    opencis_logger.addHandler(bridge)
    # Ensure the MyLogger level itself passes DEBUG records through
    opencis_logger.set_stdout_levels(loglevel="DEBUG")


_install_bridge()


# ---------------------------------------------------------------------------
# Global autouse fixture: activate opencis logger + print test banners
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _enable_opencis_logging(request):
    """Enable opencis internal logger at DEBUG for every test."""
    opencis_logger.set_stdout_levels(loglevel="DEBUG")
    _log.info(">>> START  %s", request.node.nodeid)
    yield
    outcome = "UNKNOWN"
    rep = getattr(request.node, "rep_call", None)
    if rep is not None:
        outcome = "PASSED" if rep.passed else ("FAILED" if rep.failed else "ERROR")
    _log.info("<<< %s  %s", outcome, request.node.nodeid)


# ---------------------------------------------------------------------------
# Hook: attach report phases to the test item so fixtures can inspect them
# ---------------------------------------------------------------------------

@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    rep = outcome.get_result()
    setattr(item, f"rep_{rep.when}", rep)


# ---------------------------------------------------------------------------
# Fixture: gold-standard register values
# ---------------------------------------------------------------------------

@pytest.fixture
def get_gold_std_reg_vals():
    def _get_gold_std_reg_vals(device_type: str):
        with open("tests/regvals.txt") as f:
            for line in f:
                (k, v) = line.strip().split(":")
                if k == device_type:
                    return v
        return None

    return _get_gold_std_reg_vals
