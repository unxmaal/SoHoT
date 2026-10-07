"""Schema 17: reopen refusals that were architecture gaps of ours."""
from __future__ import annotations

from harness.memory_store.migrations import retractions

VERSION = 17


def data(conn) -> None:
    retractions._reopen_architecture_gaps(conn)
