"""Schema 95: downloads.state and reason, written only by download_state; earlier rows mapped from their timestamps. #1734."""
from __future__ import annotations

from harness.memory_store.migrations import columns as cols

VERSION = 95


def columns(conn) -> None:
    cols._add_download_state(conn)


def early(conn) -> None:
    cols._backfill_download_state(conn)
