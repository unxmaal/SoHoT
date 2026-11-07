"""Schema 89: a stored agent row crashed on the 500 for a tool call the reply budget cut is token_budget_exhausted. #1547."""
from __future__ import annotations

VERSION = 89


def data(conn) -> None:
    from harness import runs
    runs.class_cut_calls(conn)
