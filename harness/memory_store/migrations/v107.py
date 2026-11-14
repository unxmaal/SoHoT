"""Schema 107: met-until retractions and soh coherence re-decisions take their verdicts.event once. #1998."""
from __future__ import annotations

VERSION = 107

# The events revisit.UNTIL_MET and adopt.REDECIDED name and the words their writers said before #1998, frozen here.
_EVENT = "until_met"
_REDECIDED, _SAID = "re-decided", "%re-decided (#%"


def data(conn) -> None:
    conn.execute("UPDATE verdicts SET event = ? WHERE event = '' AND EXISTS ("
                 "SELECT 1 FROM verdicts o WHERE o.id = verdicts.reopens AND o.until != '' "
                 "AND substr(verdicts.detail, 1, length(o.until) + 18) = 'retracted: ' || o.until || ' is met')",
                 (_EVENT,))
    conn.execute("UPDATE verdicts SET event = ? WHERE event = '' AND reopen_kind = '' AND detail LIKE ?",
                 (_REDECIDED, _SAID))
