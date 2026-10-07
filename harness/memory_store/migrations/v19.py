"""Schema 19: unlisted card tasks file by what they produce; diffusers layout gaps requeue. #379, #381."""
from __future__ import annotations

from harness.memory_store.migrations import retractions

VERSION = 19


def data(conn) -> None:
    # Unlisted card tasks now file by what they produce, and a layout stock
    # diffusers cannot assemble is not the candidate's fault. #379, #381.
    retractions._relane_from_the_card(conn)
    retractions._requeue_diffusers_layout_gaps(conn)
