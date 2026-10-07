"""Schema 9: relane proposals from their model card."""
from __future__ import annotations

from harness.memory_store.migrations import retractions

VERSION = 9


def data(conn) -> None:
    retractions._relane_from_the_card(conn)
