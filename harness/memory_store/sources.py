"""The sources table: where proposals were read from, and when."""
from __future__ import annotations

import time

DEFERRED = "deferred"


def record_source(conn, name: str, *, kind: str = "", url: str = "",
                  enabled: bool = True, ok: bool = True, error: str = "",
                  at: float | None = None, deferred: bool = False) -> None:
    """One read of a discovery source: ok, failed, or deferred by the upstream's rate limit (#416, #630)."""
    at = time.time() if at is None else float(at)
    conn.execute(
        "INSERT INTO sources (name, kind, url, enabled) VALUES (?,?,?,?) "
        "ON CONFLICT (name) DO UPDATE SET kind = excluded.kind, "
        "url = excluded.url, enabled = excluded.enabled",
        (name, kind, url, int(bool(enabled))))
    if deferred:
        conn.execute("UPDATE sources SET last_attempt_at = ?, last_status = ?, "
                     "last_error = ? WHERE name = ?", (at, DEFERRED, error[:500], name))
    elif ok:
        conn.execute("UPDATE sources SET last_read_at = ?, last_attempt_at = ?, "
                     "last_status = 'ok', last_error = '', failures = 0, retired = '' "
                     "WHERE name = ?", (at, at, name))
    else:
        conn.execute("UPDATE sources SET last_attempt_at = ?, "
                     "last_status = 'failed', last_error = ?, "
                     "failures = failures + 1 WHERE name = ?",
                     (at, error[:500], name))
    conn.commit()


def source_row(conn, name: str) -> dict | None:
    row = conn.execute("SELECT * FROM sources WHERE name = ?",
                       (name,)).fetchone()
    return dict(row) if row else None
