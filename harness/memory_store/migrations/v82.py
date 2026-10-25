"""Schema 82: a stored claims row takes its stratum from its own run, and a bad reply to an expect-empty case counts as missed. #792."""
from __future__ import annotations

VERSION = 82


def data(conn) -> None:
    from harness import runs
    runs.stamp_claims_strata(conn)
