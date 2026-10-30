"""`soh specs`: per capability, scenarios, bound to a test, and untested; non-zero when a spec is broken. #1363."""
from __future__ import annotations

from harness.commands.common import emit, note


def cmd_specs(a) -> int:
    from harness import specs
    rows, problems = specs.counts(), specs.check()
    width = max([len(r["name"]) for r in rows] + [10])
    note(f"{'capability':<{width}}  {'spec':<7}  scenarios  bound  untested")
    for r in rows:
        note(f"{r['name']:<{width}}  {r['spec']:<7}  {r['scenarios']:>9}  {r['bound']:>5}  {r['untested']:>8}")
    written = [r for r in rows if r["spec"] == "written"]
    note(f"{len(written)} of {len(rows)} capabilities specified; "
         f"{sum(r['scenarios'] for r in rows)} scenarios, {sum(r['bound'] for r in rows)} bound, "
         f"{sum(r['untested'] for r in rows)} untested")
    gaps = specs.untested() if a.untested else []
    for cap, req, sc in gaps:
        note(f"untested  {cap}: {req} / {sc}")
    for p in problems:
        note(f"PROBLEM  {p}")
    emit(ok=not problems, capabilities=rows, problems=problems,
         untested=[{"capability": c, "requirement": r, "scenario": s} for c, r, s in gaps])
    return 1 if problems else 0
