"""Schema 103: verdicts.lane, set by the writer; an older adopt verdict takes its detail's lane, else its run's. #1777."""
from __future__ import annotations

from harness.memory_store.schema import _columns

VERSION = 103


def columns(conn) -> None:
    if "lane" not in _columns(conn, "verdicts"):
        conn.execute("ALTER TABLE verdicts ADD COLUMN lane TEXT NOT NULL DEFAULT ''")


def data(conn) -> None:
    from harness import lanes
    for r in conn.execute("SELECT v.id, v.detail, u.lane AS run_lane FROM verdicts v LEFT JOIN runs u ON u.id = v.run_id "
                          "WHERE v.tier = 'adopt' AND v.lane = ''").fetchall():
        head, sep, _ = (r["detail"] or "").partition(":")
        lane = head.strip() if sep and head.strip() in lanes.ALL else (r["run_lane"] or "")
        if lane:
            conn.execute("UPDATE verdicts SET lane = ? WHERE id = ?", (lane, r["id"]))
