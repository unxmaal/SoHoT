"""Schema 50: reopen candidates a full disk settled at fetch. #528."""
from __future__ import annotations

from harness.memory_store.migrations import retractions

VERSION = 50


def data(conn) -> None:
    retractions._requeue_disk_floor_declines(conn)
