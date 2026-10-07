"""Schema 44: the gateway_requests and gateway_samples tables, which the DDL creates. #481."""
from __future__ import annotations

VERSION = 44


def indexes(conn) -> None:
    conn.execute("CREATE INDEX IF NOT EXISTS ix_greq_at ON gateway_requests(at)")
