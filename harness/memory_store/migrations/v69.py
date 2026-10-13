"""Schema 69: the delegations table, which the DDL creates, and gateway_requests.call_id. #829."""
from __future__ import annotations

from harness.memory_store.schema import _columns

VERSION = 69


def columns(conn) -> None:
    if "call_id" not in _columns(conn, "gateway_requests"):
        conn.execute("ALTER TABLE gateway_requests ADD COLUMN call_id TEXT NOT NULL DEFAULT ''")


def indexes(conn) -> None:
    conn.execute("CREATE INDEX IF NOT EXISTS ix_greq_call ON gateway_requests(call_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_delegations_lane ON delegations(lane, at)")
