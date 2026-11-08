"""Schema 93: the leases table, which the DDL creates. #1558."""
from __future__ import annotations

VERSION = 93


def indexes(conn) -> None:
    conn.execute("CREATE INDEX IF NOT EXISTS ix_leases_live ON leases(machine_id, released_at, expires_at)")
