"""Schema 5: one lane vocabulary, and every proposal filed under it. #208."""
from __future__ import annotations

from harness.memory_store.migrations import retractions

VERSION = 5


def data(conn) -> None:
    retractions._canonical_lanes(conn)
    retractions._backfill_lanes(conn)
