"""Schema 16: retract screens that left no evidence."""
from __future__ import annotations

from harness.memory_store.migrations import retractions

VERSION = 16


def data(conn) -> None:
    retractions._retract_screens_with_no_evidence(conn)
