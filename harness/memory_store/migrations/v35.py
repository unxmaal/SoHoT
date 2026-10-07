"""Schema 35: work queue jobs are rows, linked to the runs they produce. #418."""
from __future__ import annotations

from harness.memory_store.schema import _columns

VERSION = 35
#: Also runs on a new store, not only an upgraded one.
FRESH = True


def columns(conn) -> None:
    if "job_id" not in _columns(conn, "runs"):
        conn.execute("ALTER TABLE runs ADD COLUMN job_id "
                     "INTEGER REFERENCES jobs(id) ON DELETE SET NULL")


def data(conn) -> None:
    # After the runs backfill, so an old job's log can name its run. #418.
    from harness import workqueue
    workqueue.import_json(conn)


def indexes(conn) -> None:
    conn.execute("CREATE INDEX IF NOT EXISTS ix_runs_job ON runs(job_id)")
