"""Schema 53: an empty lane is filled for a card the ocr lane now takes. #562."""
from __future__ import annotations

from harness.memory_store.migrations import retractions

VERSION = 53


def data(conn) -> None:
    retractions._relane_the_laneless_from_lineage(conn)
