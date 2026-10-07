"""Schema 7: retract refusals that were the harness's, not the candidate's."""
from __future__ import annotations

from harness.memory_store.migrations import retractions

VERSION = 7


def data(conn) -> None:
    retractions._retract_harness_refusals(conn)
