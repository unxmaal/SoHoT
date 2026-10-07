"""Schema 25: a proposal's state is a column the transition table writes. #409."""
from __future__ import annotations

from harness.memory_store.migrations import columns as cols
from harness.memory_store.migrations import identity

VERSION = 25


def columns(conn) -> None:
    cols._add_state(conn)


def early(conn) -> None:
    identity._backfill_state(conn)


def indexes(conn) -> None:
    conn.execute("CREATE INDEX IF NOT EXISTS ix_prop_state ON proposals(state)")
