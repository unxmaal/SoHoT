"""Schema 32: a model card's facts are columns, backfilled before the relane steps read them. #414."""
from __future__ import annotations

from harness.memory_store.migrations import columns as cols
from harness.memory_store.migrations import prose

VERSION = 32


def columns(conn) -> None:
    cols._add_card_facts(conn)


def early(conn) -> None:
    # Before the relane steps, which read hf_task. #414.
    prose.backfill_card_facts(conn)
