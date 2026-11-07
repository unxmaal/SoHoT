"""Schema 91: the serve_waits table, which the DDL creates. #1556."""
from __future__ import annotations

VERSION = 91


def indexes(conn) -> None:
    conn.execute("CREATE INDEX IF NOT EXISTS ix_serve_waits_lane ON serve_waits(lane, at)")
