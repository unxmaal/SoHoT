"""Schema 47: the reverifications table, which the DDL creates. #480."""
from __future__ import annotations

VERSION = 47


def indexes(conn) -> None:
    conn.execute("CREATE INDEX IF NOT EXISTS ix_reverify_lane ON reverifications(lane, candidate_id)")
