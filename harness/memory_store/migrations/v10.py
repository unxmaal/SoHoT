"""Schema 10: retract verdicts recorded from runs that never reached a model."""
from __future__ import annotations

from harness.memory_store.migrations import retractions

VERSION = 10


def data(conn) -> None:
    retractions._retract_verdicts_from_runs_that_never_ran(conn)
