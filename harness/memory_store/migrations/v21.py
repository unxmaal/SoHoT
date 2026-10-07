"""Schema 21: requeue the broken verdicts the guidance_scale phrase caught. #401."""
from __future__ import annotations

from harness.memory_store.migrations import retractions

VERSION = 21


def data(conn) -> None:
    # Only the new phrase: rerunning the whole list reopens what earlier
    # schemas deliberately left. #401.
    retractions._requeue_broken_matching(conn)
