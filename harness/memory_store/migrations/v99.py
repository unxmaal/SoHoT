"""Schema 99: leases.pgid and leases.started, the holder's identity beside its pid. #1772."""
from __future__ import annotations

from harness.memory_store.schema import _columns

VERSION = 99


def columns(conn) -> None:
    for col, ddl in (("pgid", "INTEGER"), ("started", "TEXT NOT NULL DEFAULT ''")):
        if col not in _columns(conn, "leases"):
            conn.execute(f"ALTER TABLE leases ADD COLUMN {col} {ddl}")
