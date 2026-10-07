"""Schema 51: gateway_switches.outcome and reason, so a switch that did not take is recorded. #522."""
from __future__ import annotations

from harness.memory_store.migrations import columns as cols

VERSION = 51


def columns(conn) -> None:
    cols._add_switch_outcome(conn)
