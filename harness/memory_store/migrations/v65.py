"""Schema 65: requeue screens a missing-snapshot warm-up 404 settled as broken. #799."""
from __future__ import annotations

from harness.memory_store.migrations import retractions

VERSION = 65


def data(conn) -> None:
    retractions._requeue_screens_of_unresolvable_snapshots(conn)
