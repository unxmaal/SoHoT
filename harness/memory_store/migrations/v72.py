"""Schema 72: the otel_metrics and otel_events tables, which the DDL creates. #868."""
from __future__ import annotations

VERSION = 72


def indexes(conn) -> None:
    conn.execute("CREATE INDEX IF NOT EXISTS ix_otel_metrics_at ON otel_metrics(at, name)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_otel_events_at ON otel_events(at, name)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_otel_events_session ON otel_events(session_id, at)")
