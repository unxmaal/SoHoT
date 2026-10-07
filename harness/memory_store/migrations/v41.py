"""Schema 41: the results' output and artifact_path columns. #463."""
from __future__ import annotations

from harness.memory_store.migrations import columns as cols

VERSION = 41


def columns(conn) -> None:
    cols._add_result_split(conn)


def data(conn) -> None:
    cols.split_result_artifacts(conn)
