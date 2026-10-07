"""Schema 27: run results are store rows, backfilled before the older steps read them. #410."""
from __future__ import annotations

from harness.memory_store.schema import _columns

VERSION = 27
#: Also runs on a new store, not only an upgraded one.
FRESH = True


def early(conn) -> None:
    # Before the older steps, so they read stored runs, not the dir. #410.
    if "run_id" not in _columns(conn, "verdicts"):
        conn.execute("ALTER TABLE verdicts ADD COLUMN run_id "
                     "INTEGER REFERENCES runs(id)")
    from harness import runs
    runs.backfill(conn)
