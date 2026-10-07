"""Schema 23: human judge votes move from JSON into human_votes. #425."""
from __future__ import annotations

from harness.memory_store.migrations import legacy

VERSION = 23
#: Also runs on a new store, not only an upgraded one.
FRESH = True


def data(conn) -> None:
    legacy.import_human_verdicts_json(conn)
