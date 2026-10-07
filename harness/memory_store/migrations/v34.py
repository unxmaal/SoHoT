"""Schema 34: discovery source state is a sources row; neighbor scores are columns. #416."""
from __future__ import annotations

from harness.memory_store.migrations import columns as cols
from harness.memory_store.migrations import legacy
from harness.memory_store.migrations import prose

VERSION = 34
#: Also runs on a new store, not only an upgraded one.
FRESH = True


def data(conn) -> None:
    cols._add_edge_scores(conn)
    prose.lift_edge_scores(conn)
    legacy.import_discovery_state_json(conn)
    legacy.import_size_cache_lanes(conn)
