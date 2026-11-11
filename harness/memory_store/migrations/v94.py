"""Schema 94: jobs.reason, why a job holds its state; superseded deploys named from their note. #1728."""
from __future__ import annotations

from harness.memory_store.migrations import columns as cols

VERSION = 94


def columns(conn) -> None:
    cols._add_job_reason(conn)


def data(conn) -> None:
    conn.execute("UPDATE jobs SET reason = 'superseded' WHERE state = 'cancelled' AND kind = 'deploy' "
                 "AND note LIKE 'superseded by %' AND reason = ''")
