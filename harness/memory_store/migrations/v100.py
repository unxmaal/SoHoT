"""Schema 100: adoptions are named moves on one chain per lane; UNIQUE(lane, leaves) makes a racing writer lose. #1735."""
from __future__ import annotations

from harness.memory_store.migrations import columns as cols

VERSION = 100


def columns(conn) -> None:
    cols._add_adoption_move(conn)


def data(conn) -> None:
    last: dict[str, int] = {}
    for r in conn.execute("SELECT id, lane FROM adoptions ORDER BY lane, adopted_at, id").fetchall():
        conn.execute("UPDATE adoptions SET leaves = ? WHERE id = ?", (last.get(r["lane"], 0), r["id"]))
        last[r["lane"]] = r["id"]


def indexes(conn) -> None:
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_adoptions_chain ON adoptions(lane, leaves)")
