"""Schema 64: contamination_probes.hit_limit, the limit a cut probe hit. #700."""
from __future__ import annotations

from harness.memory_store.migrations import columns as cols

VERSION = 64


def columns(conn) -> None:
    cols._add_probe_limit(conn)
