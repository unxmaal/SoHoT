"""Schema 20: requeue screens of weights that were never on disk. #399."""
from __future__ import annotations

from harness.memory_store.migrations import retractions

VERSION = 20


def data(conn) -> None:
    retractions._requeue_screens_of_missing_weights(conn)
