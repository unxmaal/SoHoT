"""A lane whose typed incumbent never passes takes its incumbent from measurement, not from a paired win over it. #1110."""
from __future__ import annotations

import json

#: Distinct stored cases a typed incumbent must have passed none of to count as never passing (zero_pass_min_cases). #1110.
MIN_CASES = 30

SOURCE = "taken from measurement"


def _lane(lane: str) -> str:
    return (lane or "").strip().lower()


def zero_pass(conn, lane: str, spec: str) -> dict | None:
    """{"cases", "draws"} when `lane` serves its typed incumbent `spec` and that passed none of MIN_CASES or more stored cases."""
    from harness import adopt, power
    lane = _lane(lane)
    if not lane or not spec or lane in adopt.current(conn):
        return None
    draws, _ = power.served_profile(conn, lane, spec)
    if any(any(d) for d in draws.values()):
        return None
    if len(draws) < MIN_CASES:
        if draws:
            from harness import cuts
            cuts.cut("zero_pass_min_cases", f"{lane}: {spec} passed none of {len(draws)} case(s), too few to call it "
                     "never passing", kept=0, dropped=1, conn=conn)
        return None
    return {"spec": spec, "cases": len(draws), "draws": sum(len(d) for d in draws.values())}


def exam_cases(lane: str, split: str = "all", repeat: int = 1, suite=None) -> list | None:
    """The lane's exam cases on one split at one repeat, as evals.run loads them now; None if it cannot load."""
    from evals import core
    from evals.run import expand_cases, select_cases
    from harness import holdout
    try:
        cases = select_cases(core.load_suite(core.SHIPPED, core.local_root()) if suite is None else suite, _lane(lane))
        return list(expand_cases(holdout.only(cases, split or "all"), max(1, int(repeat or 1))))
    except (SystemExit, ValueError):
        return None


def exam(lane: str, split: str = "all", repeat: int = 1, suite=None) -> tuple[frozenset, str]:
    """(case ids, cases digest) of the lane's exam on one split at one repeat, as evals.run loads it now."""
    from evals import core
    cases = exam_cases(lane, split, repeat, suite)
    return (frozenset(), "") if cases is None else (frozenset(c.id for c in cases), core.cases_digest(cases))


def sat(run: dict, rows, candidate: str, exam_of=None, memo=None) -> bool:
    """Did `candidate` sit the whole current exam in this stored run: the digest its split and repeat give now, every case. #1120."""
    memo = {} if memo is None else memo
    receipt = run.get("receipt") or {}
    receipt = json.loads(receipt) if isinstance(receipt, str) else receipt
    key = (_lane(run.get("lane")), run.get("split") or receipt.get("split") or "all", int(run.get("repeat_count") or 1))
    if key not in memo:
        if exam_of:
            memo[key] = exam_of(*key)
        else:
            if "suite" not in memo:
                from evals import core
                memo["suite"] = core.load_suite(core.SHIPPED, core.local_root())
            memo[key] = exam(*key, suite=memo["suite"])
    ids, digest = memo[key]
    if not digest or (run.get("cases_digest") or "") != digest or (receipt.get("harness") or "patch") != "patch":
        return False
    return {r["case_id"] for r in rows if r.get("candidate") == candidate} >= ids


def measured(conn, lane: str, ids, digest: str, machines, skip=()) -> list[dict]:
    """Local candidates with a row on every case of this exam on these machines, best first."""
    from harness import adopt, methods, winners
    ids, machines = frozenset(ids), tuple(machines or ())
    if not ids or not digest or not machines:
        return []
    marks = ",".join("?" * len(machines))
    got: dict[str, dict] = {}
    for r in conn.execute(
            "SELECT x.candidate, x.case_id, x.passed, x.seconds, x.peak_kb, x.metrics, x.failure_class, r.id AS run_id, r.specs, "
            "r.receipt "
            "FROM results x JOIN runs r ON r.id = x.run_id WHERE r.lane = ? AND r.tier = 'measure' "
            f"AND r.cases_digest = ? AND r.machine_id IN ({marks}) ORDER BY r.id, x.seq",
            (_lane(lane), digest, *machines)):
        if r["case_id"] not in ids or (json.loads(r["receipt"] or "{}").get("harness") or "patch") != "patch":
            continue
        spec = (json.loads(r["specs"] or "{}") or {}).get(r["candidate"]) or r["candidate"]
        if spec in skip or adopt.is_reference(spec) or methods.is_control(spec):
            continue
        mine = got.setdefault(spec, {"spec": spec, "key": r["candidate"], "rows": [], "runs": []})
        mine["rows"].append({"candidate": r["candidate"], "case_id": r["case_id"], "passed": bool(r["passed"]),
                             "seconds": r["seconds"], "peak_kb": r["peak_kb"],
                             "metrics": json.loads(r["metrics"] or "{}"), "failure_class": r["failure_class"] or ""})
        if r["run_id"] not in mine["runs"]:
            mine["runs"].append(r["run_id"])
    full = [{**m, "summary": adopt._summary(m["rows"], m["key"])} for m in got.values()
            if {r["case_id"] for r in m["rows"]} >= ids]
    names = winners.shared_metrics([m["summary"] for m in full], _lane(lane))
    return sorted(full, key=lambda m: (winners.order_key(m["summary"], names, _lane(lane)), m["spec"]), reverse=True)


def _baseline_rows(rows: list[dict], name: str, lane: str) -> list[dict]:
    """The never-passing incumbent's cell on each case the challenger ran: failed, its metric at zero."""
    from harness import winners
    metric = winners.PRIMARY.get(lane)
    return [{"candidate": name, "case_id": r["case_id"], "passed": False, "seconds": 0.0,
             "metrics": {metric: 0.0} if metric else {}} for r in rows]


def take(conn, lane: str, incumbent: str, zero: dict, machines=None, exam_of=None):
    """The adopt verdict for the best measured local candidate on the current exam against the zero-pass incumbent, or None."""
    from harness import adopt, runs
    lane = _lane(lane)
    ids, digest = (exam_of or exam)(lane)
    machines = tuple(runs.here(conn)) if machines is None else machines
    got = measured(conn, lane, ids, digest, machines, skip={incumbent, zero.get("spec")})
    if not got:
        return None
    best = got[0]
    base = _baseline_rows(best["rows"], incumbent, lane)
    inc_row = adopt._summary(base, incumbent)
    passed = sum(1 for r in best["rows"] if r["passed"])
    # Picking the best of several measured candidates is that many comparisons. #698.
    v = adopt.decide(lane, inc_row, best["summary"], best["rows"] + base, tested=len(got) - 1)
    why = (f"{SOURCE}: {best['spec']} passed {passed} of {len(ids)} cases of the current exam "
           f"(digest {digest}, run {', '.join(map(str, best['runs']))}); {incumbent} passed 0 of "
           f"{zero['cases']} stored cases; {v.why}")
    evidence = {**v.evidence, "source": SOURCE, "runs": best["runs"], "cases_digest": digest,
                "zero_pass": zero, "candidates": [m["spec"] for m in got]}
    return adopt.Verdict(lane, incumbent, best["spec"], v.adopt, why, adopt.MEASURED,
                         v.failure_class, evidence, until=v.until)


def screened(lane: str, incumbent: str, challenger: str, ch_row: dict, zero: dict):
    """A paired run against a zero-pass incumbent is a screen: it never adopts. #1110."""
    from harness import adopt, reasons
    return adopt.Verdict(
        _lane(lane), incumbent, challenger, False,
        f"screen only: {incumbent} passed 0 of {zero['cases']} stored cases, so the lane takes its incumbent "
        f"from measurement and adopts no challenger over it; {challenger} passed "
        f"{int(ch_row.get('passed') or 0)} of {ch_row.get('total') or '?'} here",
        failure_class=reasons.INCONCLUSIVE, evidence={"zero_pass": zero})


def source(conn, lane: str, typed: str, exam_of=None) -> dict:
    """What `lane` serves and how it was chosen: adoption, typed default, and what measurement would take. Read only."""
    from harness import adopt
    lane = _lane(lane)
    row = adopt.current(conn).get(lane)
    if row:
        got = conn.execute("SELECT detail FROM verdicts WHERE id = ?", (row.get("verdict_id"),)).fetchone()
        detail = (got["detail"] if got else "") or ""
        return {"lane": lane, "spec": row["spec"], "source": "adopted, " + adopt.describe(row),
                "detail": detail.split(": ", 1)[-1]}
    zero = zero_pass(conn, lane, typed) if typed else None
    out = {"lane": lane, "spec": typed, "source": "typed default", "detail": ""}
    if zero is None:
        return out
    v = take(conn, lane, typed, zero, exam_of=exam_of)
    out["source"] = f"typed default, passed 0 of {zero['cases']} stored cases"
    out["detail"] = ("no local candidate has a row on every case of the current exam" if v is None
                     else f"{'next sweep takes' if v.adopt else 'not taken'}: {v.why}")
    return out
