"""Schema 42: the results' first-token timing columns. #468."""
from __future__ import annotations

from harness.memory_store.migrations import columns as cols

VERSION = 42


def columns(conn) -> None:
    cols._add_first_token(conn)
