"""Schema 36: drop the columns nothing reads, keeping what they held. #419."""
from __future__ import annotations

from harness.memory_store.migrations import columns as cols

VERSION = 36


def data(conn) -> None:
    cols.drop_dead_columns(conn)
