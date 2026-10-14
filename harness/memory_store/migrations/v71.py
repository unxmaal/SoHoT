"""Schema 71: requeue for measurement the candidates the #803 length cap refused. #858."""
from __future__ import annotations

from harness.memory_store.migrations import retractions

VERSION = 71


def data(conn) -> None:
    retractions._requeue_length_refusals(conn)
