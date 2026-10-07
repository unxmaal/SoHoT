"""Schema 52: an empty lane is filled from lineage, any-to-any tags and compound audio tags. #557."""
from __future__ import annotations

from harness.memory_store.migrations import retractions

VERSION = 52


def data(conn) -> None:
    retractions._relane_the_laneless_from_lineage(conn)
