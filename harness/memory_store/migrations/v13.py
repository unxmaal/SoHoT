"""Schema 13: verdicts.size_bytes, lifted out of the prose. #269."""
from __future__ import annotations

from harness.memory_store.migrations import prose
from harness.memory_store.schema import _columns

VERSION = 13


def data(conn) -> None:
    if "size_bytes" not in _columns(conn, "verdicts"):
        conn.execute("ALTER TABLE verdicts "
                     "ADD COLUMN size_bytes INTEGER NOT NULL DEFAULT 0")
    prose._lift_sizes_out_of_prose(conn)
