"""Schema 78: a knob sweep whose values all passed nothing, or all passed everything, chose nothing. #1009."""
from __future__ import annotations

VERSION = 78


def data(conn) -> None:
    from harness import sweeps
    sweeps.refile(conn)
