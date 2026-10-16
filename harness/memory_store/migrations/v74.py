"""Schema 74: jobs.not_before, a queued job's earliest start. #900."""
from __future__ import annotations

from harness.memory_store.migrations import columns as cols

VERSION = 74


def columns(conn) -> None:
    cols._add_job_not_before(conn)
