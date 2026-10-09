"""Schema 63: results.attempts, the budget-ladder rungs a row tried. #668."""
from __future__ import annotations

from harness.memory_store.migrations import columns as cols

VERSION = 63


def columns(conn) -> None:
    cols._add_attempts(conn)
