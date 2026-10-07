"""Schema 59: requeue screens a package missing from the hf-task venv settled as broken. #601."""
from __future__ import annotations

from harness.memory_store.migrations import retractions

VERSION = 59


def data(conn) -> None:
    retractions._requeue_missing_backends(conn)
