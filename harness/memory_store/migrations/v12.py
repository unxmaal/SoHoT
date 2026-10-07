"""Schema 12: a verdict names the machine that made it and the condition that would reopen it. #267."""
from __future__ import annotations

from harness.memory_store.migrations import prose
from harness.memory_store.schema import _columns

VERSION = 12


def data(conn) -> None:
    for col, ddl in (("machine_id", "INTEGER REFERENCES machines(id)"),
                     ("until", "TEXT NOT NULL DEFAULT ''")):
        if col not in _columns(conn, "verdicts"):
            conn.execute(f"ALTER TABLE verdicts ADD COLUMN {col} {ddl}")
    prose._attribute_old_verdicts(conn)
