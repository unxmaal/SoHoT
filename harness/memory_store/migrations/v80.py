"""Schema 80: a stored reply cut before grading carries its lane's graded-failure metrics. #1113."""
from __future__ import annotations

VERSION = 80


def data(conn) -> None:
    from harness import runs
    runs.grade_cut_rows(conn)
