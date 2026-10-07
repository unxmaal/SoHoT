"""Schema 46: holdout split and adopt-gate power on runs and verdicts. #479."""
from __future__ import annotations

from harness.memory_store.migrations import columns as cols

VERSION = 46


def columns(conn) -> None:
    cols._add_holdout_power(conn)
