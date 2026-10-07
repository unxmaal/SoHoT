"""Schema 18: a refusal's reopen condition, read out of its prose. #296."""
from __future__ import annotations

from harness.memory_store.migrations import prose

VERSION = 18


def data(conn) -> None:
    prose._backfill_until(conn)
