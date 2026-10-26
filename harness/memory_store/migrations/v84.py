"""Schema 84: a stored reply that crashed or timed out before grading carries its lane's graded-failure metrics too. #1302."""
from __future__ import annotations

VERSION = 84


def data(conn) -> None:
    from harness import runs
    runs.grade_cut_rows(conn)
