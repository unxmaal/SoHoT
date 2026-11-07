"""`soh residency-sim`: replay the gateway's requests and the queue's jobs against each residency policy; read-only. #1559."""
from __future__ import annotations

import datetime as _dt
import time
from pathlib import Path

from harness.commands.common import emit, err, note


def _t(at: float) -> str:
    return _dt.datetime.fromtimestamp(at).strftime("%Y-%m-%d %H:%M")


def _s(x) -> str:
    return "--" if x is None else f"{x:.1f}"


def show(trace: dict, result: dict, budget: float, pins: list, why: str) -> None:
    w, reqs = trace["window"], trace["reqs"]
    kinds: dict = {}
    for r in reqs:
        kinds[r.kind] = kinds.get(r.kind, 0) + 1
    note(f"window {_t(w['start'])} .. {_t(w['end'])}: {kinds.get('interactive', 0)} interactive and "
         f"{kinds.get('batch', 0)} batch requests, {kinds.get('job', 0)} job hold(s), over "
         f"{len(trace['sizes'])} model(s), budget {budget:.1f} GB")
    left = trace["left_out"]
    note(f"  left out: {left['skipped_purpose']} watchdog/smoke, {left['failed']} failed, {left['hosted']} hosted"
         + "".join(f"; {c} {m} (no size)" for m, c in sorted(trace["unsized"].items(), key=lambda kv: -kv[1])))
    f = trace["fit"]
    note(f"  size fit: {f['s_per_gb']} s per weights GB over {f['models']} measured model(s)"
         + (f", leave-one-out median error {f['error_s']} s" if f["error_s"] is not None else ", error unknown")
         + (" (fallback: nothing measured)" if f["fallback"] else ""))
    counts: dict = {}
    for r in reqs:
        counts[r.model] = counts.get(r.model, 0) + 1
    note(f"  {'model':<46} {'reqs':>7} {'GB':>6} {'GB src':<20} {'load s':>7} load src")
    for m in sorted(trace["sizes"], key=lambda m: -counts.get(m, 0)):
        s, ld = trace["sizes"][m], trace["loads"][m]
        note(f"  {m[-46:]:<46} {counts.get(m, 0):>7} {s['gb']:>6.1f} {s['source']:<20} {ld['s']:>7.1f} {ld['source']}")
    note(f"  pinned (pinned-lru): {', '.join(pins) or 'none'}" + (f" ({why})" if why else ""))
    note(f"  {'policy':<11} {'hit rate':>8} {'loads':>6} {'load s':>9} {'p50 s':>6} {'p95 s':>6} {'max s':>7} "
         f"{'batch s/case':>12} {'over':>5} {'over h':>7} {'peak GB':>8}")
    for p, r in result.items():
        i, b, o = r["interactive"], r["batch"], r["over_budget"]
        hit = _s(None if r["hit_rate"] is None else 100 * r["hit_rate"])
        per = "--" if b["load_s_per_case"] is None else f"{b['load_s_per_case']:.3f}"
        note(f"  {p:<11} {hit:>7}% {r['loads']:>6} {r['load_s']:>9.0f} {_s(i['p50_s']):>6} {_s(i['p95_s']):>6} "
             f"{_s(i['max_s']):>7} {per:>12} {o['moments']:>5} {o['seconds'] / 3600:>7.1f} {o['peak_gb']:>8.1f}")


def cmd_residency_sim(a) -> int:
    from harness import context_report as cr
    from harness import ledger, load_log, memory, residency, residency_trace
    from harness import memory_store as ms
    from harness.commands.common import lent_store
    now = time.time()
    try:
        since = cr.parse_when(a.since, now)
    except ValueError as exc:
        return err(str(exc))
    db = Path(a.db) if a.db else None
    if db is not None and not db.is_file():
        return err(f"residency-sim: no store at {db}")
    budget = float(a.budget_gb) if a.budget_gb else memory.total_gb()
    logs = [Path(p) for p in a.log] if a.log else load_log.router_logs()
    if db is not None:
        conn = ledger.open_ro(db)
        held = ms.lend(conn)
    else:
        held = lent_store()
    try:
        with held as c:
            trace = residency_trace.gather(c, since, now, logs, with_jobs=not a.no_jobs)
            pins, why = (list(a.pin), "") if a.pin else residency_trace.pins(c)
    finally:
        if db is not None:
            conn.close()
    sizes = {m: s["gb"] for m, s in trace["sizes"].items()}
    loads = {m: s["s"] for m, s in trace["loads"].items()}
    result = residency.compare(trace["reqs"], sizes, loads, budget, pins)
    show(trace, result, budget, pins, why)
    emit(True, window=trace["window"], requests=sum(r.kind != "job" for r in trace["reqs"]), jobs=trace["jobs"],
         budget_gb=budget, pins=pins, models={m: {**trace["sizes"][m], "load_s": trace["loads"][m]["s"],
                                                  "load_source": trace["loads"][m]["source"]} for m in trace["sizes"]},
         fit=trace["fit"], unsized=trace["unsized"], left_out=trace["left_out"], policies=result)
    return 0
