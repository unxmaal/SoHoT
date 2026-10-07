"""Schema 56: proposals.category, model, tool or technique, filled from what is known. #576."""
from __future__ import annotations

from harness.memory_store.migrations import columns as cols
from harness.memory_store.migrations import retractions

VERSION = 56


def columns(conn) -> None:
    cols._add_category(conn)


def data(conn) -> None:
    retractions._fill_categories(conn)
