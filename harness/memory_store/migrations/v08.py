"""Schema 8: retract verdicts that had no control to compare against."""
from __future__ import annotations

from harness.memory_store.migrations import retractions

VERSION = 8


def data(conn) -> None:
    retractions._retract_verdicts_with_no_control(conn)
