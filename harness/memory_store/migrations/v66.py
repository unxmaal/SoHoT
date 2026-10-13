"""Schema 66: planned and observed seconds per case on a verdict; paused_runs. #813."""
from __future__ import annotations

from harness.memory_store.migrations import columns as cols

VERSION = 66


def columns(conn) -> None:
    cols._add_verdict_seconds(conn)
