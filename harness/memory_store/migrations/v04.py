"""Schema 4: proposals.description."""
from __future__ import annotations

from harness.memory_store.schema import _columns

VERSION = 4


def early(conn) -> None:
    if "description" not in _columns(conn, "proposals"):
        conn.execute("ALTER TABLE proposals "
                     "ADD COLUMN description TEXT NOT NULL DEFAULT ''")
