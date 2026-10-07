"""Schema 26: rejected screen and measure candidates are retested. #431."""
from __future__ import annotations

from harness.memory_store.migrations import columns as cols
from harness.memory_store.migrations import identity

VERSION = 26


def columns(conn) -> None:
    cols._add_retest(conn)


def data(conn) -> None:
    identity.backfill_retests(conn)
