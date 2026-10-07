"""Schema 40: settle the questioned HF tasks by what a lane's cases can feed. #387."""
from __future__ import annotations

from harness.memory_store.migrations import retractions

VERSION = 40


def data(conn) -> None:
    retractions._relane_the_settled_tasks(conn)
