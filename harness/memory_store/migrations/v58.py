"""Schema 58: a removed download is not complete; repairs rows the cleanup stamped before the fix."""
from __future__ import annotations

VERSION = 58


def data(conn) -> None:
    conn.execute("UPDATE downloads SET complete = 0 WHERE removed_at IS NOT NULL AND complete")
