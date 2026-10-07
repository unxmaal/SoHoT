"""Schema 38: a sighting records the machine that scored it. #450."""
from __future__ import annotations

from harness.memory_store.migrations import columns as cols
from harness.memory_store.migrations import legacy

VERSION = 38


def columns(conn) -> None:
    cols._add_sighting_machine(conn)


def data(conn) -> None:
    legacy.attribute_sightings(conn)
