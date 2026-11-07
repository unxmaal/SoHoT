"""`soh interactive plan|health|probe`: the pinned interactive server, and its warm latency under load. #1561."""
from __future__ import annotations

import math
import time

from harness.commands.common import emit, note

#: The owner's LAN target for decide and extract, warm (KB decision #1035).
TARGET_P95_S = 10.0
PROBES = 20
SCHEMA = {"answer": {"type": "enum", "choices": ["yes", "no"], "description": "whether the sky is blue on a clear day"}}
QUESTION = "Is the sky blue on a clear day?"
PROMPT = "From: 'the build failed at 14:02 with exit code 2'. Reply with the exit code only."


def p95(seconds: list[float]) -> float | None:
    """Nearest-rank 95th percentile."""
    got = sorted(seconds)
    return got[math.ceil(0.95 * len(got)) - 1] if got else None


def probe(n: int = PROBES, decide=None, complete=None, sample=None, busy=None, clock=time.perf_counter) -> dict:
    """n warm decide and extract calls each after one untimed warm-up, with pressure and the lock's holder at every call."""
    from harness import delegate, pressure
    decide = decide or (lambda: delegate.decide(QUESTION, SCHEMA))
    complete = complete or (lambda: delegate.complete("extract", PROMPT))
    calls = {"decide": decide, "extract": complete}
    sample, busy = sample or pressure.sample, busy or delegate.busy
    rows: list[dict] = []
    for lane, call in calls.items():
        try:
            call()
        except Exception as exc:  # noqa: BLE001 - a failed warm-up is reported, the timed calls still run
            rows.append({"lane": lane, "warmup": True, "error": f"{type(exc).__name__}: {exc}"[:300]})
    for _ in range(n):
        for lane, call in calls.items():
            row = {"lane": lane, "pressure": getattr(sample(), "level", None), "busy": busy()}
            started = clock()
            try:
                got = call()
                row.update(seconds=round(clock() - started, 3), spec=got.get("spec"), model=got.get("model"))
            except Exception as exc:  # noqa: BLE001 - one failed call is a row, not the end of the probe
                row.update(seconds=round(clock() - started, 3), error=f"{type(exc).__name__}: {exc}"[:300])
            rows.append(row)
    lanes = {}
    for lane in calls:
        timed = [r for r in rows if r["lane"] == lane and not r.get("warmup")]
        good = [r["seconds"] for r in timed if not r.get("error")]
        lanes[lane] = {"calls": len(timed), "errors": len(timed) - len(good), "p95_s": p95(good),
                       "max_s": max(good) if good else None,
                       "pressure": sorted({r["pressure"] for r in timed if r["pressure"] is not None}),
                       "while_busy": sum(1 for r in timed if r["busy"]),
                       "served": sorted({str(r.get("spec")) for r in timed if r.get("spec")})}
    ok = all(v["errors"] == 0 and v["p95_s"] is not None and v["p95_s"] < TARGET_P95_S for v in lanes.values())
    return {"ok": ok, "target_p95_s": TARGET_P95_S, "lanes": lanes, "rows": rows}


def cmd_interactive(a) -> int:
    from harness import interactive
    if a.action == "plan":
        plan = interactive.read()
        for lane, p in (plan.get("lanes") or {}).items():
            note(f"{lane}: {p['stem']} {p['bytes'] / interactive.GIB:.1f} GiB, {p['ctx']} tokens x {p['slots']} slots"
                 f" ({p['why']})")
        for lane, why in (plan.get("skipped") or {}).items():
            note(f"{lane}: not pinned: {why}")
        if not plan:
            note("no interactive plan here: the interactive unit is not installed or was refused")
        emit(plan=plan)
        return 0
    if a.action == "health":
        got = interactive.health()
        note(str(got))
        emit(ok=not got.get("planned") or (got["up"] and not got["missing"]), health=got)
        return 0 if not got.get("planned") or (got["up"] and not got["missing"]) else 1
    got = probe(a.n)
    for lane, v in got["lanes"].items():
        note(f"{lane}: p95 {v['p95_s']} s, max {v['max_s']} s over {v['calls']} calls, {v['errors']} errors, "
             f"pressure {v['pressure']}, {v['while_busy']} while the machine lock was held, served {v['served']}")
    emit(ok=got["ok"], probe=got)
    return 0 if got["ok"] else 1
