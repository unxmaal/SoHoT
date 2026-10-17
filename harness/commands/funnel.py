"""`soh funnel`: every proposal's stage, time in it, age, and why it waits, from a copy of the store. #925."""
from __future__ import annotations

import time

from harness.commands.common import emit, note


def _d(v) -> str:
    return "-" if v is None else f"{v:.1f}d"


def render(r: dict, head: int) -> list[str]:
    out = [f"{'stage':<10} {'count':>5} {'median':>7} {'p90':>7} {'oldest':>7}  longest waiting"]
    for s in r["stages"]:
        names = ", ".join(f"{o['name']} {_d(o['in_state_days'])}" for o in s["oldest"][:3])
        out.append(f"{s['stage']:<10} {s['count']:>5} {_d(s['median_days']):>7} {_d(s['p90_days']):>7} "
                   f"{_d(s['oldest_days']):>7}  {names}")
    out.append(f"\n{r['untried']} queued with a lane have no fetch verdict or download of any kind")
    waiting = sorted((p for p in r["proposals"] if p["reason"] and p["lane_rank"] and p["lane_rank"] <= head),
                     key=lambda p: (p["lane"], p["lane_rank"]))
    if waiting:
        out.append(f"\nranked top {head} per lane, not downloaded:")
    for p in waiting:
        out.append(f"  {p['lane']:<8} #{p['lane_rank']:<3} {p['name'][:48]:<48} {p['stage']:<9} "
                   f"in state {_d(p['in_state_days'])}, seen {_d(p['age_days'])} ago: {p['reason']}: {p['why']}")
        if p["fetch_said"]:
            out.append(f"{'':<16}fetch last said: {p['fetch_said']}")
    return out


def cmd_funnel(a) -> int:
    from harness import context_report as cr, fetching, funnel, morning
    from harness.commands import screen as screen_cmd

    now = time.time()
    want = (getattr(a, "lane", "") or "").strip().lower()
    try:
        since = cr.parse_when(a.since, now) if a.since else None
    except ValueError as exc:
        note(str(exc))
        emit(False, error=str(exc))
        return 2
    top = int(a.top)
    budget = int(fetching.budget_gib(a.budget_gib) * fetching.GIB)
    try:
        backlog = len(screen_cmd.screenable_backlog(""))
    except Exception as exc:  # noqa: BLE001
        note(f"(backpressure not computed: {exc})")
        backlog = 0
    conn = morning.snapshot()
    try:
        r = funnel.gather(conn, lane=want, since=since, now=now, budget=budget, backlog=backlog, top=top)
    finally:
        conn.close()
    r.update(generated=now, lane=want, since=since, top=top, budget_gib=budget / fetching.GIB, backlog=backlog)
    for ln in render(r, a.head):
        note(ln)
    emit(**r)
    return 0
