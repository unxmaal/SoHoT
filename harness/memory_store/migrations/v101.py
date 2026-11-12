"""Schema 101: a stored fetch refusal for what the run already fetched carries failure_class passed_over. #1779."""
from __future__ import annotations

import re

VERSION = 101

# The words the refusal said before #1779, frozen here so a later rewording cannot change this step.
_REFUSAL = re.compile(r"[0-9].* GiB would take this run past its .*", re.S)


def data(conn) -> None:
    from harness import reasons
    rows = conn.execute("SELECT id, detail FROM verdicts WHERE tier = 'fetch' AND reason = ? "
                        "AND COALESCE(until, '') = '' AND failure_class = ''", (reasons.LIMIT,)).fetchall()
    for vid, detail in rows:
        if _REFUSAL.fullmatch(detail or ""):
            conn.execute("UPDATE verdicts SET failure_class = ? WHERE id = ?", (reasons.PASSED_OVER, vid))
