"""Schema 24: verdicts name a candidate, a stored identity rather than a string rule. #407."""
from __future__ import annotations

from harness.memory_store.migrations import identity
from harness.memory_store.migrations import retractions

VERSION = 24


def data(conn) -> None:
    retractions._verdicts_name_a_candidate(conn)
    identity.backfill_candidates(conn)


def indexes(conn) -> None:
    conn.execute("CREATE INDEX IF NOT EXISTS ix_verdict_cand "
                 "ON verdicts(candidate_id)")
