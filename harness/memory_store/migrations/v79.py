"""Schema 79: day_clearances (the DDL creates it) and jobs.night_gate, which a day clearance lifts. #1112."""
from __future__ import annotations

import time

from harness.memory_store.migrations import columns as cols

VERSION = 79


def columns(conn) -> None:
    cols._add_job_night_gate(conn)


def data(conn) -> None:
    """A pending job queued with --night before this column: a not_before on the hour outside the day hours."""
    from harness import watchdog
    for r in conn.execute("SELECT id, not_before FROM jobs WHERE state = 'pending' AND not_before IS NOT NULL").fetchall():
        t = time.localtime(float(r["not_before"]))
        if t.tm_min == 0 and t.tm_sec == 0 and not watchdog.DAY_START_HOUR <= t.tm_hour < watchdog.DAY_END_HOUR:
            conn.execute("UPDATE jobs SET night_gate = 1 WHERE id = ?", (r["id"],))
