"""Schema 33: one machine is one machines row, and its facts live in the store. #415."""
from __future__ import annotations

from harness.memory_store.migrations import columns as cols
from harness.memory_store.migrations import legacy
from harness.memory_store.migrations import prose

VERSION = 33


def columns(conn) -> None:
    cols._add_machine_versions(conn)


def data(conn) -> None:
    # After #411's backfill, so its downloads rows are repointed too.
    legacy.merge_duplicate_machines(conn)
    legacy.import_memory_limits_json(conn)
    prose.strip_machine_from_fetch_details(conn)
