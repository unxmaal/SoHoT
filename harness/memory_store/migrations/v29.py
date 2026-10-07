"""Schema 29: why a verdict happened is verdicts.reason and the results' failure class. #408, #406."""
from __future__ import annotations

from harness.memory_store.migrations import columns as cols
from harness.memory_store.migrations import prose

VERSION = 29


def columns(conn) -> None:
    cols._add_reasons(conn)


def data(conn) -> None:
    prose.backfill_result_classes(conn)
    prose.backfill_reasons(conn)
    prose._reopen_terminal_harness_and_limit_facts(conn)
