"""Schema 92: jobs.resource, the resource class a queued job declared. #1508."""
from __future__ import annotations

from harness.memory_store.migrations import columns as cols

VERSION = 92


def columns(conn) -> None:
    cols._add_job_resource(conn)
