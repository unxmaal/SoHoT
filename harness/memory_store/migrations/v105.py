"""Schema 105: verdicts.event, set by the writer; an older fetch verdict that said it downloaded takes the event once. #1878."""
from __future__ import annotations

from harness.memory_store.schema import _columns

VERSION = 105

# The words a download verdict said before #1878, frozen here so a later rewording cannot change this step.
_SAID = "downloaded"
_EVENT = "downloaded"


def columns(conn) -> None:
    if "event" not in _columns(conn, "verdicts"):
        conn.execute("ALTER TABLE verdicts ADD COLUMN event TEXT NOT NULL DEFAULT ''")


def data(conn) -> None:
    conn.execute("UPDATE verdicts SET event = ? WHERE tier = 'fetch' AND detail = ?", (_EVENT, _SAID))
