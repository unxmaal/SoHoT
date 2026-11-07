"""Schema 90: holds (the DDL creates it) and jobs.despite_hold, a benchmark hold's per-job pass. #1564."""
from __future__ import annotations

from harness.memory_store.migrations import columns as cols

VERSION = 90


def columns(conn) -> None:
    cols._add_job_despite_hold(conn)
