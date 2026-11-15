"""Schema 108: delegations.shape, the task kind a used-rate is measured per. #2033."""
from __future__ import annotations

from harness.memory_store.schema import _columns

VERSION = 108


def columns(conn) -> None:
    if "shape" not in _columns(conn, "delegations"):
        conn.execute("ALTER TABLE delegations ADD COLUMN shape TEXT NOT NULL DEFAULT ''")
