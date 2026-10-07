"""Schema 3: which registry holds a name, resolved from what the store already shows. #167."""
from __future__ import annotations

from harness.memory_store.migrations import identity
from harness.memory_store.schema import _columns

VERSION = 3
#: Also runs on a new store, not only an upgraded one.
FRESH = True


def early(conn) -> None:
    # v3 adds a column to a table that already exists, which CREATE IF NOT EXISTS
    # cannot do.
    if "registry" not in _columns(conn, "proposals"):
        conn.execute("ALTER TABLE proposals "
                     "ADD COLUMN registry TEXT NOT NULL DEFAULT ''")
    identity._backfill_registry(conn)
