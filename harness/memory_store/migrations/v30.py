"""Schema 30: a candidate's measured size is proposals.size_bytes. #413."""
from __future__ import annotations

from harness.memory_store.migrations import prose
from harness.memory_store.schema import _columns

VERSION = 30


def columns(conn) -> None:
    if "size_bytes" not in _columns(conn, "proposals"):
        conn.execute("ALTER TABLE proposals "
                     "ADD COLUMN size_bytes INTEGER NOT NULL DEFAULT 0")


def data(conn) -> None:
    prose.backfill_sizes(conn)
