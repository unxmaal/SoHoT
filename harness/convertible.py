"""Whether stored replies cut at a reply budget pass at a higher one: what makes the budget bind (#1020)."""
from __future__ import annotations

import json

from harness import reasons

CUT = reasons.TOKEN_BUDGET_EXHAUSTED


def base_of(spec: str) -> str:
    return (spec or "").partition(",")[0].strip()


def _top(receipt: dict, rows: list) -> int | None:
    """The most room a run gave any reply: its ladder's top rung, else its max_tokens, else the budget its cuts name."""
    rungs = [int(b) for b in receipt.get("budget_ladder") or [] if b]
    if rungs or receipt.get("max_tokens"):
        return max(rungs + [int(receipt.get("max_tokens") or 0)])
    named = [int(r["hit_limit"].rpartition(">")[2]) for r in rows
             if (r["hit_limit"] or "").startswith("max_tokens.") and r["hit_limit"].rpartition(">")[2].isdigit()]
    return max(named) if named else None


def _setting(receipt: dict, lane: str, spec: str) -> str:
    """What a run held fixed apart from its budget: the spec and the lane's sampling and template."""
    return json.dumps([spec, (receipt.get("sampling") or {}).get(lane), (receipt.get("template") or {}).get(lane)],
                      sort_keys=True, default=str)


def stored(conn, lane: str, spec: str, machines) -> list[dict]:
    """Every unflagged measured run here of `spec`'s base model in `lane`, newest first, with each case's cuts and final grade."""
    from harness import reverify, runs
    flagged = reverify._flagged_runs(conn)
    sql = ("SELECT runs.id AS run_id, runs.receipt, COALESCE(runs.generated_at, runs.recorded_at) AS at, "
           "COALESCE(c.spec, res.candidate) AS spec, res.case_id, res.repeat_index, res.passed, "
           "res.failure_class, res.hit_limit, res.attempts "
           "FROM results res JOIN runs ON res.run_id = runs.id LEFT JOIN candidates c ON c.id = res.candidate_id "
           "WHERE runs.lane = ? AND runs.tier = ?")
    clause, ids = runs._in("runs.machine_id", machines) if machines is not None else ("", ())
    by: dict = {}
    for r in conn.execute(sql + clause + " ORDER BY at DESC, runs.id DESC, res.seq", (lane, runs.MEASURE, *ids)):
        if r["run_id"] in flagged or base_of(r["spec"]) != base_of(spec):
            continue
        by.setdefault((r["run_id"], r["spec"]), {"run_id": r["run_id"], "spec": r["spec"], "at": r["at"],
                                                 "receipt": json.loads(r["receipt"] or "{}"), "rows": []})["rows"].append(dict(r))
    out = []
    for got in by.values():
        top = _top(got["receipt"], got["rows"])
        if top is None:
            continue
        cases = {}
        for r in got["rows"]:
            tries = json.loads(r["attempts"] or "[]")
            cut_at = ({int(a["max_tokens"]) for a in tries if a.get("failure_class") == CUT and a.get("max_tokens")}
                      if tries else {top} if r["failure_class"] == CUT else set())
            cases[(r["case_id"], r["repeat_index"])] = {"cut_at": cut_at, "passed": bool(r["passed"]),
                                                        "cut": r["failure_class"] == CUT}
        out.append({"run_id": got["run_id"], "spec": got["spec"], "top": top, "cases": cases,
                    "setting": _setting(got["receipt"], lane, got["spec"])})
    return out


def _pairs(low: dict, high: dict, budget: int) -> dict:
    keys = [k for k, c in low["cases"].items() if budget in c["cut_at"] and k in high["cases"]]
    fin = [high["cases"][k] for k in keys]
    return {"cut": len(keys), "passed": sum(c["passed"] for c in fin),
            "again": sum(c["cut"] for c in fin), "wrong": sum(not c["passed"] and not c["cut"] for c in fin)}


def sources(found: list[dict], spec: str, budget: int) -> list[dict]:
    """Each stored pairing of replies cut at `budget` with the same cases at more room, the unconfounded first."""
    swept = next((r["setting"] for r in found if r["spec"] == spec), None)
    out = []
    for low in found:
        for high in found:
            if high["top"] <= budget or (low is high and low["top"] <= budget):
                continue
            got = _pairs(low, high, budget)
            if not got["cut"]:
                continue
            same = low["setting"] == high["setting"]
            clean = same and low["setting"] == swept
            why = "" if clean else ("sampling differs" if not same else f"sampling differs from {spec}")
            where = f"run {low['run_id']}'s ladder" if low is high else f"runs {low['run_id']} and {high['run_id']}"
            out.append({**got, "top": high["top"], "clean": clean, "confounded": why, "where": where,
                        "low": low["run_id"], "high": high["run_id"], "rank": (not clean, low["setting"] != swept)})
    return sorted(out, key=lambda s: s["rank"])


def evidence(conn, lane: str, spec: str, budget: int, machines) -> dict:
    """{binding: True/False/None, detail, ...}: whether a reply cut at `budget` passes at more room in the stored runs."""
    found = sources(stored(conn, lane, spec, machines), spec, int(budget))
    if not found:
        return {"binding": None, "detail": f"no stored run of {base_of(spec)} in {lane} gave a reply cut at "
                                           f"{int(budget)} more room"}
    s = found[0]
    head = (f"{s['passed']} of {s['cut']} cut replies pass at {s['top']} "
            f"({'confounded: ' + s['confounded'] if s['confounded'] else 'same settings'}); "
            f"{s['where']}, {s['wrong']} finished wrong, {s['again']} cut again")
    if s["passed"] == 0:
        return {**s, "binding": False, "detail": f"not binding: {head}"}
    if s["confounded"]:
        return {**s, "binding": None, "detail": f"unknown: {head}, so the store cannot tell budget from sampling"}
    return {**s, "binding": True, "detail": f"binding: {head}"}
