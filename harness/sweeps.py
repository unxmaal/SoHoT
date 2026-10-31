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


def _flag(k, value) -> list[str]:
    if k.receipt == "max_tokens":
        return ["--max-tokens", str(int(value))]
    return ["--knob", f"{k.name}={value:g}"]


def argv(item: dict, k, value) -> list[str]:
    """The evals.run command for one value: the served spec at that knob setting."""
    from harness import reverify
    return reverify.argv({**item, "incumbent": ""}) + _flag(k, value)


def _key(conn, knob: str, lane: str, spec: str, mid) -> dict | None:
    same = "machine_id IS NULL" if mid is None else "machine_id = ?"
    row = conn.execute(f"SELECT * FROM knob_sweeps WHERE knob = ? AND lane = ? AND spec = ? AND {same} "
                       "ORDER BY id DESC LIMIT 1", (knob, lane, spec, *(() if mid is None else (mid,)))).fetchone()
    return dict(row) if row else None


def _skip(conn, last: dict | None, now: float) -> str:
    """Why a sweep is not queued: one is waiting, one decided, or one the harness could not run is still recent."""
    from harness import reverify
    if last is None or last["outcome"] in (NOT_BINDING, NOT_BINDING_LANE):
        return ""
    if not last["outcome"]:
        return f"already queued as sweep {last['id']}"
    if last["outcome"] == CHOSEN:
        return f"swept already for this model and machine: chose {json.loads(last['chosen'])}"
    days = reverify.days_for(conn, last["lane"])
    if now - (last["settled_at"] or 0) < days * 86400.0:
        return f"sweep {last['id']} was {last['outcome']}: {last['detail']}; retried after {days:g} days"
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


def _night(conn, entry: dict, k, swept: dict, machines, now: float) -> str:
    """Set the entry's start and projection; why it is refused when it would run past the night. #1020."""
    from harness import power, workqueue as wq
    start, end = wq.night_window(now)
    entry["not_before"], entry["night_end"] = start, end
    entry["projected_s"] = got = projected(conn, swept, k, list(entry["argv"]), machines)
    if got is None or got <= end - start:
        return ""
    return (f"projected {power._hm(got)} for {len(entry['argv'])} values, over the night's "
            f"{power._hm(end - start)} ({time.strftime('%H:%M', time.localtime(start))} to "
            f"{time.strftime('%H:%M', time.localtime(end))})")


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
        entry["skip"] = (_skip(conn, _key(conn, k.name, row["lane"], swept["spec"], mid), now)
                         or _night(conn, entry, k, swept, machines, now))
        out.append(entry)
    return out


def _not_binding(conn, entry: dict, now: float) -> dict | None:
    """Record a knob the stored runs show is not binding, once per distinct finding. #1020."""
    last = _key(conn, entry["knob"], entry["lane"], entry["spec"], entry["machine_id"])
    if last and last["outcome"] in (NOT_BINDING, NOT_BINDING_LANE) and last["detail"] == entry["skip"][:500]:
        return None
    ev = entry["evidence"]
    keys = ("cut", "passed", "where") if ev.get("lane") else (
        "cut", "passed", "wrong", "again", "top", "low", "high", "clean", "confounded")
    cost = {k: ev[k] for k in keys}
    cur = conn.execute(
        "INSERT INTO knob_sweeps (knob, lane, spec, candidate_id, machine_id, jobs, trigger, queued_at, settled_at, "
        "outcome, cost, detail) VALUES (?,?,?,?,?,'[]',?,?,?,?,?,?)",
        (entry["knob"], entry["lane"], entry["spec"], entry["candidate_id"], entry["machine_id"],
         json.dumps(entry["trigger"]), now, now, NOT_BINDING_LANE if ev.get("lane") else NOT_BINDING,
         json.dumps(cost), entry["skip"][:500]))
    conn.commit()
    return {**entry, "sweep": cur.lastrowid}


def _queue(conn, entry: dict, now: float, add) -> dict:
    from harness import paths
    jobs = []
    for value, cmd in entry["argv"].items():
        job = add(cmd, title=f"sweep {entry['knob']}={value:g} on {entry['lane']}: {entry['spec']}",
                  cwd=str(paths.REPO), priority=PRIORITY, requested_by=REQUESTED_BY,
                  not_before=entry.get("not_before"), conn=conn)
        jobs.append([value, int(job["id"])])
    cur = conn.execute(
        "INSERT INTO knob_sweeps (knob, lane, spec, candidate_id, machine_id, jobs, trigger, queued_at) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (entry["knob"], entry["lane"], entry["spec"], entry["candidate_id"], entry["machine_id"],
         json.dumps(jobs), json.dumps(entry["trigger"]), now))
    conn.commit()
    return {**entry, "sweep": cur.lastrowid, "jobs": jobs}


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
    from harness import paired, power
    got = {k: j for k, v in paired.draws(best_rows, unjudged=paired.UNJUDGED_ON_A_TIMEOUT_AXIS, metric=metric).items()
           if (j := [x > floor for x in v if x is not None])}
    if not got:
        return 0.0
    repeat = sum(map(len, got.values())) / len(got)
    rho = (cell.deff - 1.0) / (repeat - 1.0) if repeat > 1 else 0.0
    # A loss of d from rate p has the odds of a gain of d from rate 1-p.
    flipped = [1.0 - sum(v) / len(v) for v in got.values()]
    return power.power(flipped, effect, repeat=max(1, round(repeat)), alpha=alpha, rho=rho)


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
    """Re-decide as uninformative every chosen sweep whose values all sat at the floor or the ceiling; the count changed. #1009."""
    n = 0
    for r in conn.execute("SELECT * FROM knob_sweeps WHERE outcome = ?", (CHOSEN,)).fetchall():
        sw, cost = dict(r), json.loads(r["cost"] or "{}")
        k = knobs.KNOBS.get(sw["knob"])
        if k is None or not flat(cost):
            continue
        for row in cost.values():
            row.update(tied=False, underpowered=False, power=None if row.get("best") else row.get("power"),
                       best=False)
        conn.execute("UPDATE knob_sweeps SET outcome = ?, chosen = '', cost = ?, detail = ? WHERE id = ?",
                     (UNINFORMATIVE, json.dumps(cost), uninformative(k, sw, cost)[:500], sw["id"]))
        n += 1
    conn.commit()
    return n


def settle(conn, *, now: float, write: bool = True) -> list[dict]:
    """Decide every sweep whose jobs are no longer pending or running."""
    from harness import workqueue as wq
    out = []
    for r in conn.execute("SELECT * FROM knob_sweeps WHERE outcome = '' ORDER BY id").fetchall():
        sw = dict(r)
        states = [(wq.get(j, conn=conn) or {}).get("state") for _, j in json.loads(sw["jobs"])]
        if any(s in (wq.PENDING, wq.RUNNING) for s in states):
            continue
        outcome, chosen, cost, detail = judge(conn, sw)
        if outcome == UNRUN and states and all(s == wq.CANCELLED for s in states):
            outcome, detail = CANCELLED, "every job was cancelled"
        if write:
            conn.execute("UPDATE knob_sweeps SET outcome = ?, chosen = ?, cost = ?, detail = ?, settled_at = ? "
                         "WHERE id = ?", (outcome, json.dumps(chosen) if chosen is not None else "",
                                          json.dumps(cost), detail[:500], now, sw["id"]))
        out.append({"id": sw["id"], "knob": sw["knob"], "lane": sw["lane"], "spec": sw["spec"],
                    "outcome": outcome, "chosen": chosen, "cost": cost, "detail": detail})
    if write:
        conn.commit()
    return out


def check(conn, *, now: float | None = None, dry_run: bool = False, add=None) -> dict:
    """Settle finished sweeps, then queue one for each binding knob not yet swept here."""
    from harness import workqueue as wq
    now = time.time() if now is None else now
    settled = settle(conn, now=now, write=not dry_run)
    planned = plan(conn, now=now)
    queued, refused = [], []
    if not dry_run:
        for entry in planned:
            if not entry["skip"]:
                queued.append(_queue(conn, entry, now, add or wq.add))
            elif entry.get("evidence") and entry["evidence"]["binding"] is False:
                got = _not_binding(conn, entry, now)
                refused += [got] if got else []
    return {"settled": settled, "planned": planned, "queued": queued, "not_binding": refused, "dry_run": dry_run}


def render(got: dict) -> str:
    from harness import power
    lines = [f"  {s['detail'] or s['outcome']}" for s in got["settled"]]
    for p in got["planned"]:
        t = p["trigger"]
        why = p["skip"] or ("would queue" if got.get("dry_run") else "queued")
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
