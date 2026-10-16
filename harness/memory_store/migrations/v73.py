"""Schema 73: verdicts.ceiling_gb, lifted from each too-big verdict's prose. #880."""
from __future__ import annotations

from harness.memory_store.migrations import columns as cols
from harness.memory_store.migrations import prose

VERSION = 73


def columns(conn) -> None:
    cols._add_verdict_ceiling(conn)


def data(conn) -> None:
    prose._lift_ceilings_out_of_prose(conn)
