"""Schema 61: sources.retired, and the source rows no sweep reads are retired with the reason. #625."""
from __future__ import annotations

from harness.memory_store.migrations import columns as cols
from harness.memory_store.migrations import legacy

VERSION = 61


def columns(conn) -> None:
    cols._add_source_retired(conn)


def data(conn) -> None:
    legacy.retire_unread_sources(conn)
