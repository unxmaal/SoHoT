"""Schema 60: requeue screens an MPS backend abort settled as broken. #604."""
from __future__ import annotations

from harness.memory_store.migrations import retractions

VERSION = 60


def data(conn) -> None:
    retractions._requeue_mps_aborts(conn)
