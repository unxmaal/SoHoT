"""Schema 28: an adoption is an adoptions row. #412."""
from __future__ import annotations

from harness.memory_store.migrations import identity

VERSION = 28


def data(conn) -> None:
    identity.backfill_adoptions(conn)
