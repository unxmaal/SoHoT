"""`soh api-spend`: what metered gateway aliases spent of the API credit, in dollars. #1214."""
from __future__ import annotations

import datetime as _dt

from harness.commands.common import emit, note


def _day(text: str) -> float:
    return _dt.datetime.strptime(text, "%Y-%m-%d").timestamp()


def cmd_api_spend(a) -> int:
    """Budget, spent, remaining and the top callers; --start DAY records where spending is counted from."""
    from harness import api_spend
    if a.start:
        try:
            at = _day(a.start)
        except ValueError:
            note(f"--start takes a day such as 2026-10-25, not {a.start!r}")
            emit(False, error="bad --start")
            return 2
        from harness import memory_store as ms
        conn = ms.connect()
        try:
            api_spend.set_start(conn, at)
        finally:
            conn.close()
        note(f"API spend now counts from {a.start}")
    conn = api_spend.read_conn()
    if conn is None or not api_spend._has_table(conn):
        s = {"budget": api_spend.BUDGET_USD, "spent": 0.0, "remaining": api_spend.BUDGET_USD,
             "start": None, "unpriced": 0, "callers": []}
    else:
        try:
            s = api_spend.status(conn)
        finally:
            conn.close()
    note(f"api spend  {api_spend.line(s)}")
    for c in s["callers"]:
        note(f"           {c['caller'][:40]:<40} {c['requests']:>5} req  "
             f"{c['prompt_tokens']:>9}/{c['completion_tokens']:<8} tok  ${c['cost_usd']:.2f}")
    emit(**s)
    return 0
