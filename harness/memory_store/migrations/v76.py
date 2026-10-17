"""Schema 76: runtime screen declines wait on their cause; layout runner gaps leave broken. #950, #951."""
from __future__ import annotations

from harness.memory_store.migrations import retractions

VERSION = 76


def data(conn) -> None:
    retractions._decline_runner_layout_gaps(conn)
    retractions._rewrite_runner_gap_untils(conn)
