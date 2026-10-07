"""Schema 15: say whose staleness it is, and let a revived upstream be reconsidered. #271."""
from __future__ import annotations

from harness.memory_store.migrations import prose
from harness.memory_store.schema import _columns

VERSION = 15


def data(conn) -> None:
    # SAY WHOSE FACT IT IS. `stale_days` reads as the age of the row; it
    # is days since the CANDIDATE's upstream last committed. It was read
    # the other way within a day of landing, which is the only test of a
    # name that matters.
    cols = _columns(conn, "verdicts")
    if "stale_days" in cols and "upstream_idle_days" not in cols:
        conn.execute("ALTER TABLE verdicts "
                     "RENAME COLUMN stale_days TO upstream_idle_days")
    elif "upstream_idle_days" not in cols:
        conn.execute("ALTER TABLE verdicts ADD COLUMN "
                     "upstream_idle_days REAL NOT NULL DEFAULT 0")
    prose._let_a_revived_upstream_be_reconsidered(conn)
