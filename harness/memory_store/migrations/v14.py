"""Schema 14: the attachment kind and the upstream's age get columns. #269."""
from __future__ import annotations

from harness.memory_store.migrations import prose
from harness.memory_store.schema import _columns

VERSION = 14


def data(conn) -> None:
    # UNDER THE NAME IT ENDS UP WITH. A store arriving from schema 13 has
    # never seen `stale_days`, so creating it just to rename it one block
    # later would make the old name real for the first time in a database
    # that exists AFTER it was retired. v15 below handles the stores that
    # genuinely have it.
    for col, ddl in (("attaches_to", "TEXT NOT NULL DEFAULT ''"),
                     ("upstream_idle_days", "REAL NOT NULL DEFAULT 0")):
        if col not in _columns(conn, "verdicts") and \
                "stale_days" not in _columns(conn, "verdicts"):
            conn.execute(f"ALTER TABLE verdicts ADD COLUMN {col} {ddl}")
    if "stale_days" in _columns(conn, "verdicts"):
        conn.execute("ALTER TABLE verdicts "
                     "RENAME COLUMN stale_days TO upstream_idle_days")
    if "attaches_to" not in _columns(conn, "verdicts"):
        conn.execute("ALTER TABLE verdicts ADD COLUMN "
                     "attaches_to TEXT NOT NULL DEFAULT ''")
    prose._lift_kind_and_age_out_of_prose(conn)
