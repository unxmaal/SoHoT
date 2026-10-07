"""Schema 22: requeue the broken verdicts a dead generation thread caused. #404."""
from __future__ import annotations

from harness.memory_store.migrations import retractions

VERSION = 22


def data(conn) -> None:
    retractions._requeue_broken_matching(conn, ("generation thread died",))
