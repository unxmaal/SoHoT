"""Schema 104: verdicts.budget_gib, the fetch run's budget, lifted once from each older refusal's sentence. #1822."""
from __future__ import annotations

import re

from harness.memory_store.schema import _columns

VERSION = 104

# The words the refusal said before #1822, frozen here so a later rewording cannot change this step.
_BUDGET = re.compile(r"past its (\d+(?:\.\d+)?) GiB budget")


def columns(conn) -> None:
    if "budget_gib" not in _columns(conn, "verdicts"):
        conn.execute("ALTER TABLE verdicts ADD COLUMN budget_gib REAL")


def data(conn) -> None:
    from harness import reasons
    rows = conn.execute("SELECT id, detail FROM verdicts WHERE tier = 'fetch' AND reason = ? AND budget_gib IS NULL",
                        (reasons.LIMIT,)).fetchall()
    for vid, detail in rows:
        m = _BUDGET.search(detail or "")
        if m:
            conn.execute("UPDATE verdicts SET budget_gib = ? WHERE id = ?", (float(m.group(1)), vid))
