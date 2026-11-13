"""A binding knob is swept across its range through the work queue, and the cheapest value shown no worse than the best is recorded (#636, #690).

binding.count says a knob keeps deciding a lane's results. This queues one
evals.run of the lane's served model per value the knob declares, reads the
runs those jobs store, and picks the cheapest value (fewest seconds) that is
not significantly worse than the best with power to have seen a loss. The decision and its cost are
recorded in knob_sweeps; nothing here changes a constant. A sweep is not run
again for the same knob, lane, model and machine; a change of any of those
asks again.
"""
from __future__ import annotations

import json
import math
import time

from harness import binding, knobs, reasons

REQUESTED_BY = binding.SWEEP
#: Below a person's jobs and beside reverify's.
PRIORITY = -10
CHOSEN, UNRUN, CANCELLED, UNINFORMATIVE = "chosen", "unrun", "cancelled", "uninformative"
#: The stored runs show no reply cut at the budget passes with more room, so nothing was queued. #1020.
NOT_BINDING = "not_binding"
#: The swept model has no stored run giving its cuts more room, and the lane's other models' cuts do not convert. #1177.
NOT_BINDING_LANE = "not_binding_lane"
#: Cuts the lane's stored runs must have given more room, none passing, before a model with no ladder of its own is not swept.
LANE_MIN_CUTS = 20
#: Measured cases a run needs to stand for its model over a newer, smaller one, and to rank above a smaller run. #1179, #1239.
FALLBACK_MIN_CASES = 20
#: GPU seconds a reply-budget sweep, all its values together, may be projected to take before it is refused. #1020, #1509.
BUDGET_S = 11 * 3600.0

#: A sweep's state is its outcome column: OPEN while its jobs run, then one settled outcome. #1733.
OPEN = ""
SETTLED = (CHOSEN, UNINFORMATIVE, UNRUN, CANCELLED)
FOUND = (NOT_BINDING, NOT_BINDING_LANE)
#: Why a sweep row moves: queued, a not-binding finding recorded, settled, a paused job resumed, or refiled (#1009).
QUEUED, RECORDED, JUDGED, RESUMED, REFILED = "queued", "recorded", "judged", "resumed", "refiled"
#: (outcome it leaves, outcome it enters) -> the reasons that may move it; None leaves no open sweep for the key. #1733.
MOVES: dict[tuple, frozenset[str]] = {
    (None, OPEN): frozenset({QUEUED}),
    **{(None, to): frozenset({RECORDED}) for to in FOUND},
    (OPEN, OPEN): frozenset({RESUMED}),
    **{(OPEN, to): frozenset({JUDGED}) for to in SETTLED},
    # The one move out of a settled sweep: a chosen one re-decided under the #1009 floor rule.
    (CHOSEN, UNINFORMATIVE): frozenset({REFILED}),
}
#: A job of a sweep whose row no longer exists: it runs nothing more, as a cancelled one. #1733.
GONE = "gone"
_INSERTS = frozenset({"jobs", "trigger", "queued_at", "settled_at", "chosen", "cost", "detail"})
_UPDATES = frozenset({"jobs", "settled_at", "chosen", "cost", "detail"})
_LEDGER = "knob-sweep:"


class IllegalMove(ValueError):
    """A knob sweep write MOVES refuses, refused before anything is written. #1733."""


def refused(frm, to: str, reason: str) -> str:
    """Why a sweep may not move from `frm` to `to` for `reason`, or '' if it may."""
    allowed = MOVES.get((frm, to))
    if allowed is None:
        return f"no sweep moves from {'nothing' if frm is None else frm or 'open'} to {to or 'open'}"
    if reason not in allowed:
        return f"{reason or 'no reason'} does not move a sweep from {frm} to {to}; {', '.join(sorted(allowed))} may"
    return ""


def _where(sw: dict) -> tuple[str, tuple]:
    from harness import machine_scope
    here, mine = machine_scope.where("knob_sweeps.mine", sw["machine_id"])
    return f"knob = ? AND lane = ? AND spec = ? AND {here}", (sw["knob"], sw["lane"], sw["spec"], *mine)


def _open(conn, sw: dict) -> dict | None:
    """The key's open sweep, of which _move lets there be one."""
    where, args = _where(sw)
    row = conn.execute(f"SELECT * FROM knob_sweeps WHERE {where} AND outcome = ? ORDER BY id", (*args, OPEN)).fetchone()
    return dict(row) if row else None


def _found(conn, sw: dict, detail: str) -> bool:
    where, args = _where(sw)
    return conn.execute(f"SELECT 1 FROM knob_sweeps WHERE {where} AND outcome IN (?, ?) AND detail = ?",
                        (*args, *FOUND, detail)).fetchone() is not None


def _move(conn, sw: dict, frm, to: str, reason: str, commit: bool = True, **cols) -> int | None:
    """The one writer of knob_sweeps: refuses a move MOVES does not list, else compare-and-swap on the state it leaves; the row id, None if it lost. Commits unless commit=False. #1733."""
    from harness import item_lease
    why = refused(frm, to, reason)
    if why:
        raise IllegalMove(f"knob sweep {sw.get('id', '-')}: {why}")
    unknown = set(cols) - (_INSERTS if frm is None else _UPDATES)
    if unknown:
        raise IllegalMove(f"a sweep move does not set {', '.join(sorted(unknown))}")
    if frm is not None:
        sets = "".join(f", {k} = ?" for k in cols)
        # A move out of an open sweep was decided on the jobs it read; a resume since then changed them. #1862.
        cas, was = (" AND jobs = ?", (sw["jobs"],)) if frm == OPEN else ("", ())
        won = conn.execute(f"UPDATE knob_sweeps SET outcome = ?{sets} WHERE id = ? AND outcome = ?{cas}",
                           (to, *cols.values(), int(sw["id"]), frm, *was)).rowcount == 1
        if commit:
            conn.commit()
        return int(sw["id"]) if won else None
    if commit:
        conn.commit()
    key = _LEDGER + json.dumps([sw["knob"], sw["lane"], sw["spec"], sw["machine_id"]])
    seen = item_lease._version(conn, key)
    if _open(conn, sw) is not None or (to in FOUND and _found(conn, sw, cols.get("detail", ""))):
        return None
    row = {k: sw[k] for k in ("knob", "lane", "spec", "candidate_id", "machine_id")} | cols | {"outcome": to}
    cur = conn.execute(f"INSERT INTO knob_sweeps ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})",
                       tuple(row.values()))
    if not item_lease._bump(conn, key, seen):
        if commit:
            conn.rollback()
        return None
    if commit:
        conn.commit()
    return int(cur.lastrowid)


def _flag(k, value) -> list[str]:
    if k.receipt == "max_tokens":
        return ["--max-tokens", str(int(value))]
    return ["--knob", f"{k.name}={value:g}"]


def argv(item: dict, k, value) -> list[str]:
    """The evals.run command for one value: the served spec at that knob setting."""
    from harness import reverify
    return reverify.argv({**item, "incumbent": ""}) + _flag(k, value)


def _skip(conn, sw: dict, now: float) -> str:
    """Why a sweep is not queued: one is open, one chose a value, or one the harness could not run is still recent."""
    from harness import reverify
    got = _open(conn, sw)
    if got is not None:
        return f"already queued as sweep {got['id']}"
    where, args = _where(sw)
    got = conn.execute(f"SELECT * FROM knob_sweeps WHERE {where} AND outcome = ? ORDER BY id", (*args, CHOSEN)).fetchone()
    if got is not None:
        return f"swept already for this model and machine: chose {json.loads(got['chosen'])}"
    days = reverify.days_for(conn, sw["lane"])
    recent = conn.execute(f"SELECT * FROM knob_sweeps WHERE {where} AND outcome IN (?, ?, ?) AND settled_at > ? "
                          "ORDER BY settled_at, id", (*args, UNRUN, CANCELLED, UNINFORMATIVE, now - days * 86400.0)
                          ).fetchall()
    if recent:
        got = recent[-1]
        return f"sweep {got['id']} was {got['outcome']}: {got['detail']}; retried after {days:g} days"
    return ""


def passing(conn, lane: str, machines) -> dict:
    """(candidate_id or spec) -> {spec, candidate_id, passed, n, run_id} from each model's newest measured run here that no flag or sweep marks, of at least FALLBACK_MIN_CASES cases when it has one. #1009, #1239."""
    from harness import reverify, runs
    flagged = reverify._flagged_runs(conn)
    sql = ("SELECT runs.id AS run_id, res.candidate_id, res.candidate, c.spec, res.passed, res.metrics, res.failure_class "
           "FROM results res JOIN runs ON res.run_id = runs.id LEFT JOIN jobs ON jobs.id = runs.job_id "
           "LEFT JOIN candidates c ON c.id = res.candidate_id "
           "WHERE runs.lane = ? AND runs.tier = ? "
           f"AND COALESCE(jobs.requested_by, '') != '{REQUESTED_BY}'")
    clause, ids = runs._in("runs.machine_id", machines) if machines is not None else ("", ())
    by: dict = {}
    for r in conn.execute(sql + clause + " ORDER BY COALESCE(runs.generated_at, runs.recorded_at) DESC, "
                          "runs.id DESC", (lane, runs.MEASURE, *ids)).fetchall():
        if r["run_id"] in flagged:
            continue
        key = r["candidate_id"] if r["candidate_id"] is not None else r["candidate"]
        got = by.setdefault(key, {}).setdefault(r["run_id"], {
            "spec": r["spec"] or r["candidate"], "candidate_id": r["candidate_id"], "passed": 0, "n": 0,
            "run_id": r["run_id"], "rows": []})
        got["passed"] += int(bool(r["passed"]))
        got["n"] += 1
        got["rows"].append({"passed": bool(r["passed"]), "metrics": json.loads(r["metrics"] or "{}"),
                            "failure_class": r["failure_class"] or ""})
    out: dict = {}
    passed_over = 0
    for key, seen in by.items():
        # A newer smoke run does not stand for a model over a run of enough cases. #1239.
        got = out[key] = next((m for m in seen.values() if m["n"] >= FALLBACK_MIN_CASES), next(iter(seen.values())))
        passed_over += got is not next(iter(seen.values()))
        rows = got.pop("rows")
        got["working"] = bool(got["passed"]) or _working(conn, lane, got)
        got.update(_bound(rows, lane))
    if passed_over:
        from harness import cuts
        cuts.cut("fallback_min_cases", f"{lane}: models whose newest run is too small to stand for them",
                 dropped=passed_over, conn=conn)
    return out


def _bound(rows: list[dict], lane: str) -> dict:
    """The lane metric ranked on ('' for none), its pooled value, the share of judged rows it covers, and a 95% Wilson bound signed so larger is better: the pass rate's where the rows carry no lane metric. #1230."""
    from evals import core
    from harness import intervals, reasons, winners
    from harness.checks import claims
    name = winners.PRIMARY.get(lane, "")
    judged = max(1, sum(r["failure_class"] not in reasons.NEVER_RAN for r in rows))
    if name in core.RATIO_METRICS:
        num, den = core.RATIO_METRICS[name]
        have = [r["metrics"] for r in rows if r["metrics"].get(den)]
        k, n = sum(float(m.get(num) or 0.0) for m in have), sum(float(m[den]) for m in have)
        if n:
            lower = core.direction_of(name) == "lower"
            bound = -intervals.wilson(min(k, n), n)[1] if lower else intervals.wilson(k, n)[0]
            return {"metric": name, "value": k / n, "covered": min(1.0, len(have) / judged), "bound": bound}
    elif lane in winners.STRATIFIED:
        by = {want: [r["passed"] for r in rows if r["metrics"].get(claims.STRATUM) == want] for want in (0, 1)}
        if by[0] and by[1]:
            def lo(bits):
                return intervals.wilson(sum(bits), len(bits))[0]
            return {"metric": name, "value": claims.balanced(sum(by[0]) / len(by[0]), sum(by[1]) / len(by[1])),
                    "covered": min(1.0, (len(by[0]) + len(by[1])) / judged), "bound": claims.balanced(lo(by[0]), lo(by[1]))}
    return {"metric": "", "value": None, "covered": 0.0,
            "bound": intervals.wilson(sum(r["passed"] for r in rows), len(rows))[0]}


def _working(conn, lane: str, got: dict) -> bool:
    """A model that passed no case here still works on the lane's metric, as the screen reads it. #733, #1219."""
    from harness import reverify, runs
    rows = [r for r in runs.rows(conn, got["run_id"], got["candidate_id"])
            if got["candidate_id"] is not None or r["candidate"] == got["spec"]]
    return reverify._working(rows, lane)


def _failed(conn, lane: str, cid) -> str:
    from harness import reverify
    last = reverify._latest(conn, lane, cid, settled=True) if cid is not None else None
    return last["detail"] if last and last["outcome"] in (reverify.FAILED, reverify.REGRESSED) else ""


def below(conn, lane: str, spec: str, incumbents, machines) -> str:
    """Why the newest run here pairing `spec` with one of `incumbents` (on at least FALLBACK_MIN_CASES shared cases when one does) shows it losing more shared cases than it gains on what the lane pairs on; '' if none does. #1177, #1219, #1239."""
    from harness import adopt, reverify, runs
    flagged = reverify._flagged_runs(conn)
    others = [i for i in incumbents if i and i != spec and not adopt.is_reference(i)]
    sql = ("SELECT runs.id AS run_id, COALESCE(c.spec, res.candidate) AS spec, res.case_id, res.repeat_index, "
           "res.passed, res.metrics, res.failure_class FROM results res JOIN runs ON res.run_id = runs.id "
           "LEFT JOIN jobs ON jobs.id = runs.job_id LEFT JOIN candidates c ON c.id = res.candidate_id "
           f"WHERE runs.lane = ? AND runs.tier = ? AND COALESCE(jobs.requested_by, '') != '{REQUESTED_BY}'")
    clause, ids = runs._in("runs.machine_id", machines) if machines is not None else ("", ())
    by: dict = {}
    for r in conn.execute(sql + clause + " ORDER BY COALESCE(runs.generated_at, runs.recorded_at) DESC, runs.id DESC",
                          (lane, runs.MEASURE, *ids)):
        if r["run_id"] not in flagged and r["spec"] in (spec, *others):
            by.setdefault(r["run_id"], {}).setdefault(r["spec"], {})[(r["case_id"], r["repeat_index"])] = {
                "candidate": r["spec"], "case_id": f"{r['case_id']}#{r['repeat_index']}", "passed": bool(r["passed"]),
                "metrics": json.loads(r["metrics"] or "{}"), "failure_class": r["failure_class"] or ""}
    for inc in others:
        pairs = [(rid, got, shared) for rid, got in by.items()
                 if (shared := got.get(spec, {}).keys() & got.get(inc, {}).keys())]
        if not pairs:
            continue
        rid, got, shared = next((p for p in pairs if len(p[2]) >= FALLBACK_MIN_CASES), pairs[0])
        cell = adopt.lane_cell([got[who][k] for who in (inc, spec) for k in shared], inc, spec, lane, "challenger")
        if cell.lost > cell.gained:
            mine, theirs = (sum(got[who][k]["passed"] for k in shared) for who in (spec, inc))
            on = reverify._compared_on(lane)
            return (f"{spec} passed {mine} of {len(shared)} beside {inc}'s {theirs} in run {rid}"
                    + (f", {cell.lost} lost against {cell.gained} gained on {on}" if on and mine >= theirs else ""))
    return ""


def _rank(m: dict) -> tuple:
    """Runs of at least FALLBACK_MIN_CASES first, then by how much of the run the lane metric covers, then its Wilson bound (the pass rate's where there is none). #1179, #1230."""
    return (m["n"] < FALLBACK_MIN_CASES, -round(m["covered"], 3), -m["bound"], -m["passed"] / m["n"], -m["passed"])


def model(conn, item: dict, machines) -> tuple[dict | None, str]:
    """The model a lane's sweep runs: the served one when it passes a case here (or works on the lane metric, #1219) and no paired run shows it below its incumbent, else the lane's best such one, else None and why. #1009, #1177."""
    from harness import adopt
    lane = item["lane"]
    seen = passing(conn, lane, machines)
    own = (seen.get(item["candidate_id"]) if item["candidate_id"] is not None
           else next((m for m in seen.values() if m["spec"] == item["spec"]), None))
    why = _failed(conn, lane, item["candidate_id"])
    lost = below(conn, lane, item["spec"], [item.get("incumbent")], machines) if own and own["working"] and not why else ""
    if own and own["working"] and not why and not lost:
        return item, ""
    why = why or lost or (f"{item['spec']} passed 0 of {own['n']} in run {own['run_id']}" if own
                          else f"{item['spec']} has no measured run in {lane} here")
    above = [item["spec"], item.get("incumbent")]
    best = sorted((m for m in seen.values() if m["working"] and not adopt.is_reference(m["spec"])
                   and m["spec"] != item["spec"] and not _failed(conn, lane, m["candidate_id"])
                   and not below(conn, lane, m["spec"], above, machines)),
                  key=_rank)
    if not best:
        return None, f"{why}, and no model passes a case in {lane} here, so a sweep could see nothing"
    m = best[0]
    return ({"lane": lane, "spec": m["spec"], "candidate_id": m["candidate_id"], "incumbent": "",
             "incumbent_id": None},
            f"{why}; sweeping {m['spec']}, the best passing ({m['passed']} of {m['n']} in run {m['run_id']}"
            + (f", {m['metric']} {m['value']:.3f}" if m["metric"] else "") + ")")


def _base_run(conn, swept: dict, machines) -> int | None:
    seen = passing(conn, swept["lane"], machines)
    own = (seen.get(swept["candidate_id"]) if swept["candidate_id"] is not None
           else next((m for m in seen.values() if m["spec"] == swept["spec"]), None))
    return own["run_id"] if own else None


def projected(conn, swept: dict, k, values, machines) -> float | None:
    """Seconds the sweep's jobs take one after another: the run passing() keeps for the swept model, its cut rows scaled to each value. #1020."""
    from harness import runs
    rid = _base_run(conn, swept, machines)
    if rid is None:
        return None
    rows = runs.rows(conn, rid, swept["candidate_id"])
    head = k.limit_name(swept["lane"]) + ">"
    total = 0.0
    for v in values:
        for r in rows:
            at = (r["limit"] or "").removeprefix(head) if (r["limit"] or "").startswith(head) else ""
            scale = float(v) / float(at) if at.replace(".", "", 1).isdigit() and float(at) > 0 else 1.0
            total += float(r["seconds"] or 0) * scale
    return total


def _budget(conn, entry: dict, k, swept: dict, machines) -> str:
    """Set the entry's projection; why it is refused when it would take more than BUDGET_S. #1020, #1509."""
    from harness import cuts, power
    entry["projected_s"] = got = projected(conn, swept, k, list(entry["argv"]), machines)
    if got is None or got <= BUDGET_S:
        return ""
    cuts.cut("sweep_budget", "reply-budget sweeps projected past the budget", dropped=1, conn=conn)
    return f"projected {power._hm(got)} for {len(entry['argv'])} values, over the {power._hm(BUDGET_S)} sweep budget"


def lane_evidence(row: dict, spec: str) -> dict | None:
    """Not binding for a model with no ladder of its own when at least LANE_MIN_CUTS of the lane's cuts were given more room and none passed. #1177."""
    if row.get("converted") or row.get("cuts", 0) < LANE_MIN_CUTS:
        if not row.get("converted") and row.get("cuts", 0):
            from harness import cuts
            cuts.cut("lane_min_cuts", f"{spec}: lane evidence of {row['cuts']} cut(s) too thin to stop a sweep",
                     kept=row["cuts"])
        return None
    where = ", ".join(row["where"])
    return {"binding": False, "lane": True, "cut": row["cuts"], "passed": 0, "where": row["where"],
            "detail": f"not binding on the lane: 0 of {row['cuts']} cut replies pass with more room ({where}), "
                      f"and no stored run of {spec} gave its cuts more room"}


def plan(conn, *, now: float | None = None) -> list[dict]:
    """Every binding knob an eval can set, on a lane this machine serves, with the commands that would sweep it."""
    from harness import binding, convertible, memory_store as ms, reverify, runs
    now = time.time() if now is None else now
    served = reverify.served(conn)
    mid = ms.machine_row(conn)
    machines = runs.here(conn)
    out = []
    for row in binding.binding(binding.count(conn, now=now, machines=machines)):
        k = knobs.KNOBS[row["knob"]]
        item = served.get(row["lane"])
        # A cut names no lane an eval can sweep it on. #1087.
        if not k.receipt or item is None or row.get("source") == "cut":
            continue
        trigger = {"limit": row["limit"], "hits": row["hits"], "of": row["of"]}
        if k.grades:
            why = (f"{k.name} sets the grade, not the run: a sweep would choose the laxest value by the passes "
                   f"it grades, so it is calibrated against labelled cases instead (#1228)")
            out.append({"knob": k.name, "lane": row["lane"], "spec": item["spec"],
                        "candidate_id": item["candidate_id"], "machine_id": mid, "trigger": trigger,
                        "argv": {}, "model": "", "skip": why})
            continue
        swept, note = model(conn, item, machines)
        if swept is None:
            out.append({"knob": k.name, "lane": row["lane"], "spec": item["spec"],
                        "candidate_id": item["candidate_id"], "machine_id": mid, "trigger": trigger,
                        "argv": {}, "model": note, "skip": note})
            continue
        entry = {"knob": k.name, "lane": row["lane"], "spec": swept["spec"], "candidate_id": swept["candidate_id"],
                 "machine_id": mid, "trigger": trigger, "model": note, "evidence": None}
        if k.receipt == "max_tokens":
            ev = entry["evidence"] = convertible.evidence(conn, row["lane"], swept["spec"], row["value"], machines)
            if ev["binding"] is None and "cut" not in ev:
                ev = entry["evidence"] = lane_evidence(row, swept["spec"]) or ev
            if ev.get("lane"):
                trigger.update(cut=ev["cut"], convertible=ev["passed"], runs=ev["where"])
            elif ev["binding"] is not None:
                trigger.update(cut=ev["cut"], convertible=ev["passed"], at=ev["top"])
            if ev["binding"] is False:
                out.append({**entry, "argv": {}, "skip": ev["detail"]})
                continue
        entry["argv"] = {v: argv(swept, k, v) for v in k.values_for(row["lane"])}
        entry["skip"] = _skip(conn, entry, now) or _budget(conn, entry, k, swept, machines)
        out.append(entry)
    return out


def _not_binding(conn, entry: dict, now: float) -> dict | None:
    """Record a knob the stored runs show is not binding, once per distinct finding and never over an open sweep. #1020, #1733."""
    ev = entry["evidence"]
    keys = ("cut", "passed", "where") if ev.get("lane") else (
        "cut", "passed", "wrong", "again", "top", "low", "high", "clean", "confounded")
    got = _move(conn, entry, None, NOT_BINDING_LANE if ev.get("lane") else NOT_BINDING, RECORDED,
                jobs="[]", trigger=json.dumps(entry["trigger"]), queued_at=now, settled_at=now,
                cost=json.dumps({k: ev[k] for k in keys}), detail=entry["skip"][:500])
    return None if got is None else {**entry, "sweep": got}


def _queue(conn, entry: dict, now: float, add) -> dict | None:
    """Queue one job per value and open the sweep in one transaction; a writer that loses the open keeps no job. #1733, #1756."""
    from harness import job_state as js
    from harness import paths
    values = list(entry["argv"])
    specs = [(cmd, {"title": f"sweep {entry['knob']}={value:g} on {entry['lane']}: {entry['spec']}",
                    "cwd": str(paths.REPO), "priority": PRIORITY, "requested_by": REQUESTED_BY,
                    "not_before": entry.get("not_before")}) for value, cmd in entry["argv"].items()]

    def own(rows):
        pairs = [[v, int(r["id"])] for v, r in zip(values, rows)]
        return _move(conn, entry, None, OPEN, QUEUED, commit=False, jobs=json.dumps(pairs),
                     trigger=json.dumps(entry["trigger"]), queued_at=now)
    got, rows = js.add_owned(conn, specs, own, add)
    if got is None:
        return None
    return {**entry, "sweep": got, "jobs": [[v, int(r["id"])] for v, r in zip(values, rows)]}


def _floor(outcomes: dict, metric: str) -> float:
    """The signed score of a judged row with nothing to show: a fail, 0 on a higher-is-better metric, else the worst seen. #1219."""
    from evals.core import direction_of
    from harness import paired
    if not metric or direction_of(metric) == "higher":
        return 0.0
    seen = (paired._score(r, metric, paired.UNJUDGED_ON_A_TIMEOUT_AXIS) for rows in outcomes.values() for r in rows or ())
    return min([-1.0, *(s for s in seen if s is not None and math.isfinite(s))])


def _filled(rows: list[dict], metric: str, floor: float) -> list[dict]:
    """Failed rows judged on this axis but never scored (a timeout) take the metric's floor, not -inf. #1219."""
    from evals.core import direction_of
    from harness import paired
    if not metric:
        return rows
    unsigned = floor if direction_of(metric) == "higher" else -floor
    return [r if r.get("passed") or (r.get("metrics") or {}).get(metric) is not None
            or paired._verdict(r, paired.UNJUDGED_ON_A_TIMEOUT_AXIS) is None
            else {**r, "metrics": {**(r.get("metrics") or {}), metric: unsigned}} for r in rows]


def _pair(best: list[dict], rows: list[dict], lane: str):
    """This value against the best by base case and repeat on what the lane pairs on, as reverify pairs a rerun. #733, #1219."""
    import dataclasses
    from harness import adopt, holdout, paired, reverify, winners
    axis = paired.UNJUDGED_ON_A_TIMEOUT_AXIS
    cell = paired.pair(best, rows, same_repeat=True, unjudged=axis, metric=reverify._metric(lane))
    if lane not in winners.STRATIFIED or cell.refused:
        return cell

    def as_(name, mine):
        return [{**r, "candidate": name, "failure_class": "" if paired._verdict(r, axis) is not None else r.get("failure_class"),
                 "case_id": f"{holdout.base_id(r['case_id'])}#{paired.repeat_index(r['case_id'])}"} for r in mine]
    got = adopt.lane_cell(as_("best", best) + as_("value", rows), "best", "value", lane, against="challenger")
    return dataclasses.replace(got, deff=cell.deff)


def _standing(rows: list[dict], lane: str, metric: str, floor: float) -> tuple:
    """How good a value's rows are, larger better: the pooled metric of a stratified lane, else the summed row scores. #1219."""
    from harness import paired, runs, winners
    if lane in winners.STRATIFIED:
        return tuple(winners.primary(next(iter(runs.summarize([{**r, "candidate": "v"} for r in rows]).values())), lane))
    scores = (paired._score(r, metric, paired.UNJUDGED_ON_A_TIMEOUT_AXIS) for r in rows)
    return (sum(floor if s is None or not math.isfinite(s) else float(s) for s in scores),)


def _power_to_see_a_loss(best_rows, cell, alpha: float, effect: float, metric: str, floor: float) -> float:
    """Power of the paired test to see this value lose `effect` per cell against the best; a draw can lose when it scores above the floor. #690, #1178, #1219."""
    from harness import power
    flipped, repeat, rho = power.loss_odds(best_rows, cell.deff, metric, floor)
    return power.power(flipped, effect, repeat=repeat, alpha=alpha, rho=rho)


def decide(values, outcomes: dict, alpha: float, effect: float | None = None, lane: str = "") -> tuple[object, dict]:
    """The cheapest value not significantly worse than the best on the lane's metric with power >= TARGET to see a loss of effect, and the cost table. #690, #1219."""
    from harness import paired, power, reverify
    effect = power.DEFAULT_EFFECT if effect is None else effect
    metric = reverify._metric(lane)
    floor = _floor(outcomes, metric)
    pos = {v: i for i, v in enumerate(values)}
    stats = {}
    for v in values:
        rows = [{"peak_kb": 0, "detail": "", "warnings": [], **r, "metrics": r.get("metrics") or {}}
                for r in _filled(outcomes.get(v) or [], metric, floor)]
        if rows:
            scores = [paired._score(r, metric, paired.UNJUDGED_ON_A_TIMEOUT_AXIS) for r in rows]
            stats[v] = {"passed": sum(1 for r in rows if r["passed"]), "n": len(rows),
                        "seconds": sum(float(r["seconds"] or 0) for r in rows), "rows": rows,
                        "rank": _standing(rows, lane, metric, floor),
                        "room": sum(1 for s in scores if s is not None and s > floor),
                        "at_best": sum(power.draw(r, lane) for r in rows)}
    if not stats:
        return None, {}
    best = min(stats, key=lambda v: (tuple(-x for x in stats[v]["rank"]), -stats[v]["passed"],
                                     stats[v]["seconds"], pos[v]))
    table, tied = {}, []
    for v in (v for v in values if v in stats):
        cell = _pair(stats[best]["rows"], stats[v]["rows"], lane)
        worse = cell.lost > cell.gained and cell.p <= alpha
        pw = None if v == best else (0.0 if cell.refused else
                                     _power_to_see_a_loss(stats[best]["rows"], cell, alpha, effect, metric, floor))
        ok = v == best or (not worse and pw >= power.TARGET)
        table[str(v)] = {"passed": stats[v]["passed"], "n": stats[v]["n"],
                         "seconds": round(stats[v]["seconds"], 3), "lost": cell.lost, "gained": cell.gained,
                         "p": round(cell.p, 4), "power": None if pw is None else round(pw, 3), "tied": ok,
                         "underpowered": not ok and not worse and not cell.refused,
                         "refused": cell.refused, "best": v == best,
                         **({"room": stats[v]["room"], "at_best": stats[v]["at_best"]} if metric else {}),
                         **({"scored": got} if (got := reverify._scored(stats[v]["rows"], lane)) else {})}
        if ok:
            tied.append(v)
    if flat(table):
        for row in table.values():
            row.update(tied=False, best=False, underpowered=False)
        return None, table
    return min(tied, key=lambda v: (stats[v]["seconds"], pos[v])), table


def flat(cost: dict) -> str:
    """Why the cases cannot tell the values apart: all at the floor or all at their best, on the lane's metric when it pairs on one; '' when they can. #1009, #1219."""
    rows = list(cost.values())
    if rows and all(r.get("room", r["passed"]) == 0 for r in rows):
        return "every value passed 0 of its cases"
    if rows and all(r.get("at_best", r["passed"]) == r["n"] for r in rows):
        return "every value passed every case"
    return ""


def caveats(cost: dict) -> str:
    """Why each value that was neither chosen nor worse was left out."""
    out = ""
    for v, row in cost.items():
        if row.get("refused"):
            out += f"; {v} could not be paired with the best: {row['refused']}"
        elif row.get("underpowered"):
            out += f"; {v} not distinguishable from the best at power {row['power']:.2f}"
    return out


def _run_of(conn, job_id: int) -> int | None:
    from harness import runs
    got = runs.for_job(conn, job_id)
    return got["id"] if got else None


def judge(conn, sw: dict) -> tuple[str, object, dict, str]:
    """(outcome, chosen, cost, detail) for one sweep whose jobs have all finished."""
    from harness import adopt, power, runs
    k = knobs.KNOBS[sw["knob"]]
    outcomes, ran = {}, {}
    for value, job_id in json.loads(sw["jobs"]):
        rid = _run_of(conn, job_id)
        if rid is None:
            continue
        rows = runs.rows(conn, rid, sw["candidate_id"]) if sw["candidate_id"] is not None else runs.rows(conn, rid)
        if rows and all(not r["passed"] and r["failure_class"] in reasons.NEVER_RAN for r in rows):
            continue
        ran[value] = rid
        outcomes[value] = rows
    chosen, cost = decide(k.values_for(sw["lane"]), outcomes, adopt.ALPHA, power.effect_for(sw["lane"]), sw["lane"])
    if not cost:
        return UNRUN, None, {}, f"none of the {len(json.loads(sw['jobs']))} jobs stored a run"
    for value, rid in ran.items():
        if str(value) in cost:
            cost[str(value)]["run_id"] = rid
    if chosen is None:
        return UNINFORMATIVE, None, cost, uninformative(k, sw, cost)
    return CHOSEN, chosen, cost, detail(sw, chosen, cost)


def detail(sw: dict, chosen, cost: dict) -> str:
    """What a chosen sweep settled, naming the pooled lane metric of the chosen and best values. #1219."""
    k = knobs.KNOBS[sw["knob"]]
    best = next(v for v in k.values_for(sw["lane"]) if cost.get(str(v), {}).get("best"))
    spent = sum(c["seconds"] for c in cost.values())
    c, b = cost[str(chosen)], cost[str(best)]
    return (f"{k.name} on {sw['lane']} for {sw['spec']}: chose {chosen:g} ({c['passed']} of {c['n']}{c.get('scored', '')}, "
            f"{c['seconds']:g}s), {'the best' if chosen == best else 'no worse than the best'} "
            f"{best:g} ({b['passed']} of {b['n']}{b.get('scored', '')}, {b['seconds']:g}s); now {k.default(sw['lane']):g}; "
            f"the sweep spent {spent:g}s" + caveats(cost))


def uninformative(k, sw: dict, cost: dict) -> str:
    """The detail of a sweep whose cases cannot tell its values apart: nothing is chosen. #1009."""
    each = ", ".join(f"{v} {c['passed']} of {c['n']}" for v, c in cost.items())
    spent = sum(c["seconds"] for c in cost.values())
    return (f"{k.name} on {sw['lane']} for {sw['spec']}: chose nothing, {flat(cost)} ({each}), so the cases "
            f"cannot tell the values apart; still {k.default(sw['lane']):g}; the sweep spent {spent:g}s")


def refile(conn) -> int:
    """Re-decide as uninformative every chosen sweep whose values all sat at the floor or the ceiling, the one named move out of a settled sweep; the count changed. #1009, #1733."""
    n = 0
    for r in conn.execute("SELECT * FROM knob_sweeps WHERE outcome = ?", (CHOSEN,)).fetchall():
        sw, cost = dict(r), json.loads(r["cost"] or "{}")
        k = knobs.KNOBS.get(sw["knob"])
        if k is None or not flat(cost):
            continue
        for row in cost.values():
            row.update(tied=False, underpowered=False, power=None if row.get("best") else row.get("power"),
                       best=False)
        said = f"refiled from chosen {sw['chosen']} (#1009): {uninformative(k, sw, cost)}"
        n += _move(conn, sw, CHOSEN, UNINFORMATIVE, REFILED, chosen="", cost=json.dumps(cost),
                   detail=said[:500]) is not None
    return n


def _job_state(conn, job_id) -> str:
    """A sweep job's queue state, GONE when its row no longer exists. #1733."""
    from harness import workqueue as wq
    got = wq.get(job_id, conn=conn)
    return GONE if got is None else got["state"]


def _ended(states: list[str]) -> bool:
    """Whether a sweep's jobs will run nothing more: each done, failed, cancelled or gone, none paused or unknown."""
    from harness import job_state as js
    return all(s in (js.DONE, js.FAILED, js.CANCELLED, GONE) for s in states)


def _dropped(states: list[str]) -> str:
    """The detail of a sweep none of whose jobs ran because each was cancelled or deleted; '' otherwise."""
    from harness import job_state as js
    if not states or any(s not in (js.CANCELLED, GONE) for s in states):
        return ""
    if all(s == js.CANCELLED for s in states):
        return "every job was cancelled"
    return "every job was deleted" if all(s == GONE for s in states) else "every job was cancelled or deleted"


def _resume(conn, sw: dict, value, job: dict, add) -> dict | None:
    """Queue a paused value's continuation and point the open sweep at it in one transaction; None if another writer moved the sweep. #1733, #1755."""
    from harness import job_state as js
    from harness import paths, runs
    from harness import job_settle
    run = runs.for_job(conn, int(job["id"]))
    argv = job["argv"] if run is None else job_settle.resume_argv(job["argv"], runs.run_dir(run["path"]))
    jobs: list = []

    def own(rows):
        jobs[:] = [[v, int(rows[0]["id"]) if int(j) == int(job["id"]) else j] for v, j in json.loads(sw["jobs"])]
        return _move(conn, sw, OPEN, OPEN, RESUMED, commit=False, jobs=json.dumps(jobs))
    got, rows = js.add_owned(conn, [(argv, {
        "title": job["title"] or f"sweep {sw['knob']}={value:g} on {sw['lane']}: {sw['spec']}",
        "cwd": job["cwd"] or str(paths.REPO), "priority": PRIORITY, "requested_by": REQUESTED_BY})], own, add)
    if got is None:
        return None
    nxt = rows[0]
    sw["jobs"] = json.dumps(jobs)
    return {"id": sw["id"], "knob": sw["knob"], "lane": sw["lane"], "value": value, "paused": job["id"],
            "job": nxt["id"]}


def settle(conn, *, now: float, write: bool = True, add=None, resumed: list | None = None) -> list[dict]:
    """Decide every open sweep whose jobs will run nothing more; a paused job is resumed into `resumed`, never judged. #1733."""
    from harness import job_state as js
    from harness import workqueue as wq
    out = []
    for r in conn.execute("SELECT * FROM knob_sweeps WHERE outcome = ? ORDER BY id", (OPEN,)).fetchall():
        sw = dict(r)
        jobs = json.loads(sw["jobs"])
        states = [_job_state(conn, j) for _, j in jobs]
        paused = [(v, j) for (v, j), s in zip(jobs, states) if s == js.PAUSED]
        if paused:
            for value, job_id in paused if write else ():
                got = _resume(conn, sw, value, wq.get(job_id, conn=conn), add or wq.add)
                if got is not None and resumed is not None:
                    resumed.append(got)
            continue
        if not _ended(states):
            continue
        outcome, chosen, cost, detail = judge(conn, sw)
        if outcome == UNRUN and _dropped(states):
            outcome, detail = CANCELLED, _dropped(states)
        if write and _move(conn, sw, OPEN, outcome, JUDGED, chosen=json.dumps(chosen) if chosen is not None else "",
                           cost=json.dumps(cost), detail=detail[:500], settled_at=now) is None:
            continue
        out.append({"id": sw["id"], "knob": sw["knob"], "lane": sw["lane"], "spec": sw["spec"],
                    "outcome": outcome, "chosen": chosen, "cost": cost, "detail": detail})
    return out


def check(conn, *, now: float | None = None, dry_run: bool = False, add=None) -> dict:
    """Settle finished sweeps, then queue one for each binding knob not yet swept here."""
    from harness import workqueue as wq
    now = time.time() if now is None else now
    resumed: list = []
    settled = settle(conn, now=now, write=not dry_run, add=add, resumed=resumed)
    planned = plan(conn, now=now)
    queued, refused = [], []
    from harness import hold
    held = hold.active(conn, now)
    if not dry_run and held is None:
        for entry in planned:
            if not entry["skip"]:
                got = _queue(conn, entry, now, add or wq.add)
                queued += [got] if got else []
            elif entry.get("evidence") and entry["evidence"]["binding"] is False:
                got = _not_binding(conn, entry, now)
                refused += [got] if got else []
    return {"settled": settled, "resumed": resumed, "planned": planned, "queued": queued, "not_binding": refused,
            "dry_run": dry_run,
            "held": hold.line(held, now) if held else ""}


def render(got: dict) -> str:
    from harness import power
    lines = [f"  {s['detail'] or s['outcome']}" for s in got["settled"]]
    lines += [f"  sweep {r['id']} {r['knob']}={r['value']:g} on {r['lane']}: job {r['paused']} paused, "
              f"resumed as job {r['job']}" for r in got.get("resumed", ())]
    lines += [f"  queued nothing: {got['held']}"] if got.get("held") and not got.get("dry_run") else []
    for p in got["planned"]:
        t = p["trigger"]
        why = p["skip"] or ("would queue" if got.get("dry_run") else "held" if got.get("held") else "queued")
        if not p["argv"]:
            lines.append(f"  {p['knob']} on {p['lane']} ({t['limit']}: {t['hits']} of {t['of']}): not swept, {why}")
            continue
        if not p["skip"] and p.get("not_before"):
            why += (f" to start {time.strftime('%a %H:%M', time.localtime(p['not_before']))}"
                    + (f", projected {power._hm(p['projected_s'])}" if p.get("projected_s") is not None else ""))
        ev = p.get("evidence")
        lines.append(f"  {p['knob']} on {p['lane']} ({t['limit']}: {t['hits']} of {t['of']}): "
                     f"{len(p['argv'])} values, {why}" + (f" ({p['model']})" if p.get("model") else "")
                     + (f"; {ev['detail']}" if ev else ""))
    return "\n".join(lines) or "  no binding knob to sweep"
