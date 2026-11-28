"""Schema 109: owner_picks, the blind A/B picks a perceptual lane's holdout win waits on. #2183."""
from __future__ import annotations

VERSION = 109


def columns(conn) -> None:
    from harness.memory_store.schema import OWNER_PICKS_DDL
    conn.execute(OWNER_PICKS_DDL.strip())
