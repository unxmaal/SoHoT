"""`soh inventory`: read-only accounts of what the machine and the project spent. `time` is #1152."""
from __future__ import annotations

import datetime as _dt
import json
import time
from pathlib import Path

from harness.commands.common import emit, note


def _h(x) -> str:
    return "--" if x is None else f"{x:.1f}"


def _s(x) -> str:
    return "--" if x is None else f"{x:.2f}"


def _day(at: float) -> str:
    return _dt.datetime.fromtimestamp(at).strftime("%Y-%m-%d %H:%M")


def open_store():
    """The live store read-only (SQLite mode=ro), or a Postgres connection; None when there is no store."""
    from harness import ledger, store
    from harness import memory_store as ms
    if store.backend() == store.POSTGRES:
        return ms.connect()
    path = ms.db_path()
    return ledger.open_ro(path) if path.exists() else None


def show(L: dict) -> None:
    w = L["window"]
    note(f"time account {_day(w['start'])} .. {_day(w['end'])}: {w['hours']} hours, {L['sweeps']} sweep(s)")
    note(f"  {'category':<17} {'hours':>6} {'share':>6} {'cum':>6} {'busy h':>7} {'gpu h':>6}")
    for r in L["pareto"]:
        note(f"  {r['category']:<17} {r['hours']:>6} {r['share']:>6.1%} {r['cumulative']:>6.1%} "
             f"{r['busy_hours']:>7.1f} {r['gpu_busy_hours']:>6.1f}")
    b = L["blocked"]
    note(f"blocked: {b['any']} hour(s) with a reason; daytime {b['daytime_any']} of {b['daytime_hours']}")
    for why, n in b["by_reason"].items():
        note(f"  {why:<17} {n:>6}")
    note(f"  daytime hours the GPU or RAM was taken by non-work: {b['daytime_taken']} of {b['daytime_hours']}"
         + "".join(f"; {c} {n}" for c, n in b["daytime_taken_by"].items()))
    note(f"  delegations refused for a held machine: {b['refused']} of {b['failed']} failed")
    loc = L["local"]
    note("local work (gateway_requests purpose work):")
    note(f"  {'client':<22} {'lane':<9} {'reqs':>6} {'tok in':>9} {'tok out':>8} {'p50 s':>7} {'p90 s':>7} {'p99 s':>7}")
    for r in loc["requests"]:
        s = r["seconds"]
        note(f"  {r['client'][:22]:<22} {(r['lane'] or '-')[:9]:<9} {r['requests']:>6} {r['prompt_tokens']:>9} "
             f"{r['completion_tokens']:>8} {_s(s['p50']):>7} {_s(s['p90']):>7} {_s(s['p99']):>7}")
    note("delegations:")
    for r in loc["delegations"]:
        o = r["outcomes"]
        note(f"  {r['caller'][:22]:<22} {r['lane']:<9} {r['delegations']:>4}  used {o['used']} edited {o['edited']} "
             f"discarded {o['discarded']} accepted {o['accepted']} rejected {o['rejected']} "
             f"unknown {o['unknown']} pending {o['pending']}  p50 {_s(r['seconds']['p50'])} s")
    note("  outcomes: " + ", ".join(f"{k} {v}" for k, v in loc["outcomes"].items()))
    e = L.get("effort")
    if e:
        for key, label in (("all", "since the repo began"), ("recent", f"last {e['recent_days']} days")):
            note(f"effort {label}:")
            note(f"  {'area':<12} {'issues':>6} {'prs':>5} {'merged':>6} {'lines':>8}")
            tot = sum(r["lines"] for r in e[key].values()) or 1
            for area, r in sorted(e[key].items(), key=lambda kv: -kv[1]["lines"]):
                note(f"  {area:<12} {r['issues']:>6} {r['prs']:>5} {r['merged']:>6} {r['lines']:>8} "
                     f"{r['lines'] / tot:>6.1%}")
        s = e.get("sample")
        if s:
            rate = "--" if s["rate"] is None else f"{s['rate']:.0%}"
            note(f"  hand-checked sample: {s['agree']} of {s['checked']} agree ({rate})")


def cmd_time(a) -> int:
    from harness import inventory_time as it, paths

    now = time.time()
    since = None
    if a.since:
        from harness import context_report as cr
        try:
            since = cr.parse_when(a.since, now)
        except ValueError as exc:
            note(str(exc))
            emit(False, error=str(exc))
            return 2
    conn = open_store()
    if conn is None:
        note("no store")
        emit(False, error="no store")
        return 1
    try:
        src = it.gather(conn, paths.home(), now, since)
    finally:
        conn.close()
    prs = issues = None
    if a.effort_from:
        got = json.loads(Path(a.effort_from).read_text(encoding="utf-8"))
        prs, issues = got["prs"], got["issues"]
    elif not a.no_effort:
        try:
            prs, issues = it.gh_items()
        except (OSError, RuntimeError, ValueError) as exc:
            note(f"effort: unavailable ({exc})")
    L = it.build(src, prs=prs, issues=issues, sample=it.load_sample())
    if not a.hours:
        L.pop("hours")
    show(L)
    emit(**L)
    return 0
