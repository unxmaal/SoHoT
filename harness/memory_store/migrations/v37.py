"""Schema 37: result rows carry the candidate they ran as. #429."""
from __future__ import annotations

from harness.memory_store.migrations import identity

VERSION = 37


def data(conn) -> None:
    identity.resolve_identity_leftovers(conn)
