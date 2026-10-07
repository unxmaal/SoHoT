"""Schema 57: proposals.model_type and remote_code, read by inspect; nothing to backfill. #567."""
from __future__ import annotations

from harness.memory_store.migrations import columns as cols

VERSION = 57


def columns(conn) -> None:
    cols._add_code_facts(conn)
