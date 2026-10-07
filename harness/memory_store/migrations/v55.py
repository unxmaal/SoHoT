"""Schema 55: an empty lane is filled for a privacy filter the pii lane now takes. #564."""
from __future__ import annotations

from harness.memory_store.migrations import retractions

VERSION = 55


def data(conn) -> None:
    retractions._relane_the_laneless_from_lineage(conn)
