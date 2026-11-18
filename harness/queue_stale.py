"""Monit's check that the queue still moves: nothing started or finished for QUEUE_STALE_S while work is due (#2064)."""
from __future__ import annotations

import sys
import time
from pathlib import Path

#: Seconds no queue job may start or finish, and no deploy record be written, while a due job waits, before monit alerts.
QUEUE_STALE_S = 43200.0


def last_moved(conn, records: Path | None = None) -> float | None:
    """The newest job start or finish here, or deploy record write; None when nothing ever ran."""
    from harness import deploy, workqueue as wq
    here, args = wq._here(conn)
    row = conn.execute(f"SELECT MAX(started_at), MAX(finished_at) FROM jobs WHERE {here}", args).fetchone()
    marks = [float(x) for x in tuple(row) if x is not None]
    marks += [p.stat().st_mtime for p in (records or deploy.records_dir()).glob("*.json")]
    return max(marks) if marks else None


def stale(conn, now: float | None = None, records: Path | None = None) -> str:
    """Why the queue has not moved for QUEUE_STALE_S while a due job waits; '' while it moves or nothing is due."""
    from harness import cuts, deploy, workqueue as wq
    now = time.time() if now is None else now
    due = [j for j in wq.pending(conn) if wq.due(j, now)]
    if not due:
        return ""
    queued = min(wq._epoch(j["added"]) or now for j in due)
    moved = last_moved(conn, records)
    since = queued if moved is None else max(moved, queued)
    if now - since < QUEUE_STALE_S:
        return ""
    cuts.cut("queue_stale_alert", "queue alerted as not moving", dropped=1, conn=conn)
    kinds = sorted({j["kind"] for j in due})
    deploys = [j for j in due if j["kind"] == deploy.KIND]
    ok, why = wq.gate(now=now)
    head = f"nothing has run for {(now - since) / 3600:.1f} h with {len(due)} due job(s) pending ({', '.join(kinds)})"
    tail = f"; deploy job {deploys[0]['id']} among them" if deploys else ""
    return f"{head}{tail}: {'the gate is open' if ok else why}"


def main() -> int:
    from harness import workqueue as wq
    with wq._store() as c:
        said = stale(c)
    print(said or "the queue moves, or nothing is due")
    return 1 if said else 0


if __name__ == "__main__":
    sys.exit(main())
