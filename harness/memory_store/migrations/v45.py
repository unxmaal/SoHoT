"""Schema 45: downloads' served-context columns. #498."""
from __future__ import annotations

from harness.memory_store.migrations import columns as cols

VERSION = 45


def columns(conn) -> None:
    cols._add_served_context(conn)
