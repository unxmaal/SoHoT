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
import time

from harness import binding, knobs

REQUESTED_BY = binding.SWEEP
#: Below a person's jobs and beside reverify's.
PRIORITY = -10
CHOSEN, UNRUN, CANCELLED, UNINFORMATIVE = "chosen", "unrun", "cancelled", "uninformative"


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
    if last is None:
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
    """(candidate_id or spec) -> {spec, candidate_id, passed, n, run_id} from each model's newest measured run here that no flag or sweep marks. #1009."""
    from harness import reverify, runs
    flagged = reverify._flagged_runs(conn)
    sql = ("SELECT runs.id AS run_id, res.candidate_id, res.candidate, c.spec, res.passed "
           "FROM results res JOIN runs ON res.run_id = runs.id LEFT JOIN jobs ON jobs.id = runs.job_id "
           "LEFT JOIN candidates c ON c.id = res.candidate_id "
           "WHERE runs.lane = ? AND runs.tier = ? "
           f"AND COALESCE(jobs.requested_by, '') != '{REQUESTED_BY}'")
    clause, ids = runs._in("runs.machine_id", machines) if machines is not None else ("", ())
    out: dict = {}
    for r in conn.execute(sql + clause + " ORDER BY COALESCE(runs.generated_at, runs.recorded_at) DESC, "
                          "runs.id DESC", (lane, runs.MEASURE, *ids)).fetchall():
        if r["run_id"] in flagged:
            continue
        key = r["candidate_id"] if r["candidate_id"] is not None else r["candidate"]
        got = out.setdefault(key, {"spec": r["spec"] or r["candidate"], "candidate_id": r["candidate_id"],
                                   "passed": 0, "n": 0, "run_id": r["run_id"]})
        if got["run_id"] == r["run_id"]:
            got["passed"] += int(bool(r["passed"]))
            got["n"] += 1
    return out


def _failed(conn, lane: str, cid) -> str:
    from harness import reverify
    last = reverify._latest(conn, lane, cid, settled=True) if cid is not None else None
    return last["detail"] if last and last["outcome"] in (reverify.FAILED, reverify.REGRESSED) else ""


def model(conn, item: dict, machines) -> tuple[dict | None, str]:
    """The model a lane's sweep runs: the served one when it passes a case here, else the lane's best passing one, else None and why. #1009."""
    from harness import adopt
    lane = item["lane"]
    seen = passing(conn, lane, machines)
    own = (seen.get(item["candidate_id"]) if item["candidate_id"] is not None
           else next((m for m in seen.values() if m["spec"] == item["spec"]), None))
    why = _failed(conn, lane, item["candidate_id"])
    if own and own["passed"] and not why:
        return item, ""
    why = why or (f"{item['spec']} passed 0 of {own['n']} in run {own['run_id']}" if own
                  else f"{item['spec']} has no measured run in {lane} here")
    best = sorted((m for m in seen.values() if m["passed"] and not adopt.is_reference(m["spec"])
                   and not _failed(conn, lane, m["candidate_id"])),
                  key=lambda m: (-m["passed"] / m["n"], -m["passed"]))
    if not best:
        return None, f"{why}, and no model passes a case in {lane} here, so a sweep could see nothing"
    m = best[0]
    return ({"lane": lane, "spec": m["spec"], "candidate_id": m["candidate_id"], "incumbent": "",
             "incumbent_id": None},
            f"{why}; sweeping {m['spec']}, the best passing ({m['passed']} of {m['n']} in run {m['run_id']})")


def plan(conn, *, now: float | None = None) -> list[dict]:
    """Every binding knob an eval can set, on a lane this machine serves, with the commands that would sweep it."""
    from harness import binding, memory_store as ms, reverify, runs
    now = time.time() if now is None else now
    served = reverify.served(conn)
    mid = ms.machine_row(conn)
    machines = runs.here(conn)
    out = []
    for row in binding.binding(binding.count(conn, now=now, machines=machines)):
        k = knobs.KNOBS[row["knob"]]
        item = served.get(row["lane"])
        if not k.receipt or item is None:
            continue
        swept, note = model(conn, item, machines)
        trigger = {"limit": row["limit"], "hits": row["hits"], "of": row["of"]}
        if swept is None:
            out.append({"knob": k.name, "lane": row["lane"], "spec": item["spec"],
                        "candidate_id": item["candidate_id"], "machine_id": mid, "trigger": trigger,
                        "argv": {}, "model": note, "skip": note})
            continue
        out.append({"knob": k.name, "lane": row["lane"], "spec": swept["spec"],
                    "candidate_id": swept["candidate_id"], "machine_id": mid, "trigger": trigger,
                    "argv": {v: argv(swept, k, v) for v in k.values_for(row["lane"])}, "model": note,
                    "skip": _skip(conn, _key(conn, k.name, row["lane"], swept["spec"], mid), now)})
    return out


def _queue(conn, entry: dict, now: float, add) -> dict:
    from harness import paths
    jobs = []
    for value, cmd in entry["argv"].items():
        job = add(cmd, title=f"sweep {entry['knob']}={value:g} on {entry['lane']}: {entry['spec']}",
                  cwd=str(paths.REPO), priority=PRIORITY, requested_by=REQUESTED_BY, conn=conn)
        jobs.append([value, int(job["id"])])
    cur = conn.execute(
        "INSERT INTO knob_sweeps (knob, lane, spec, candidate_id, machine_id, jobs, trigger, queued_at) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (entry["knob"], entry["lane"], entry["spec"], entry["candidate_id"], entry["machine_id"],
         json.dumps(jobs), json.dumps(entry["trigger"]), now))
    conn.commit()
    return {**entry, "sweep": cur.lastrowid, "jobs": jobs}


def _power_to_see_a_loss(best_rows, cell, alpha: float, effect: float) -> float:
    """Power of the paired test to see this value lose `effect` per cell against the best. #690."""
    from harness import paired, power
    got = paired.draws(best_rows)
    if not got:
        return 0.0
    repeat = sum(map(len, got.values())) / len(got)
    rho = (cell.deff - 1.0) / (repeat - 1.0) if repeat > 1 else 0.0
    # A loss of d from rate p has the odds of a gain of d from rate 1-p.
    flipped = [1.0 - sum(v) / len(v) for v in got.values()]
    return power.power(flipped, effect, repeat=max(1, round(repeat)), alpha=alpha, rho=rho)


def decide(values, outcomes: dict, alpha: float, effect: float | None = None) -> tuple[object, dict]:
    """The cheapest value not significantly worse than the best with power >= TARGET to see a loss of effect, and the cost table. #690."""
    from harness import paired, power
    effect = power.DEFAULT_EFFECT if effect is None else effect
    pos = {v: i for i, v in enumerate(values)}
    stats = {}
    for v in values:
        rows = outcomes.get(v)
        if rows:
            stats[v] = {"passed": sum(1 for r in rows if r["passed"]), "n": len(rows),
                        "seconds": sum(float(r["seconds"] or 0) for r in rows), "rows": rows}
    if not stats:
        return None, {}
    best = min(stats, key=lambda v: (-stats[v]["passed"], stats[v]["seconds"], pos[v]))
    table, tied = {}, []
    for v in (v for v in values if v in stats):
        cell = paired.pair(stats[best]["rows"], stats[v]["rows"], same_repeat=True,
                           unjudged=paired.UNJUDGED_ON_A_TIMEOUT_AXIS)
        worse = cell.lost > cell.gained and cell.p <= alpha
        pw = None if v == best else (0.0 if cell.refused else
                                     _power_to_see_a_loss(stats[best]["rows"], cell, alpha, effect))
        ok = v == best or (not worse and pw >= power.TARGET)
        table[str(v)] = {"passed": stats[v]["passed"], "n": stats[v]["n"],
                         "seconds": round(stats[v]["seconds"], 3), "lost": cell.lost, "gained": cell.gained,
                         "p": round(cell.p, 4), "power": None if pw is None else round(pw, 3), "tied": ok,
                         "underpowered": not ok and not worse and not cell.refused,
                         "refused": cell.refused, "best": v == best}
        if ok:
            tied.append(v)
    if flat(table):
        for row in table.values():
            row.update(tied=False, best=False, underpowered=False)
        return None, table
    return min(tied, key=lambda v: (stats[v]["seconds"], pos[v])), table


def flat(cost: dict) -> str:
    """Why the cases cannot tell the values apart: every one at the floor or every one at the ceiling; '' when they can. #1009."""
    rows = list(cost.values())
    if rows and all(r["passed"] == 0 for r in rows):
        return "every value passed 0 of its cases"
    if rows and all(r["passed"] == r["n"] for r in rows):
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
        ran[value] = rid
        outcomes[value] = (runs.rows(conn, rid, sw["candidate_id"]) if sw["candidate_id"] is not None
                           else runs.rows(conn, rid))
    chosen, cost = decide(k.values_for(sw["lane"]), outcomes, adopt.ALPHA, power.effect_for(sw["lane"]))
    if not cost:
        return UNRUN, None, {}, f"none of the {len(json.loads(sw['jobs']))} jobs stored a run"
    for value, rid in ran.items():
        if str(value) in cost:
            cost[str(value)]["run_id"] = rid
    if chosen is None:
        return UNINFORMATIVE, None, cost, uninformative(k, sw, cost)
    best = next(v for v in k.values_for(sw["lane"]) if cost.get(str(v), {}).get("best"))
    spent = sum(c["seconds"] for c in cost.values())
    c, b = cost[str(chosen)], cost[str(best)]
    detail = (f"{k.name} on {sw['lane']} for {sw['spec']}: chose {chosen:g} ({c['passed']} of {c['n']}, "
              f"{c['seconds']:g}s), {'the best' if chosen == best else 'no worse than the best'} "
              f"{best:g} ({b['passed']} of {b['n']}, {b['seconds']:g}s); now {k.default(sw['lane']):g}; the sweep spent {spent:g}s"
              + caveats(cost))
    return CHOSEN, chosen, cost, detail


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
    queued = []
    if not dry_run:
        for entry in planned:
            if not entry["skip"]:
                queued.append(_queue(conn, entry, now, add or wq.add))
    return {"settled": settled, "planned": planned, "queued": queued, "dry_run": dry_run}


def render(got: dict) -> str:
    lines = [f"  {s['detail'] or s['outcome']}" for s in got["settled"]]
    for p in got["planned"]:
        t = p["trigger"]
        why = p["skip"] or ("would queue" if got.get("dry_run") else "queued")
        if not p["argv"]:
            lines.append(f"  {p['knob']} on {p['lane']} ({t['limit']}: {t['hits']} of {t['of']}): not swept, {why}")
            continue
        lines.append(f"  {p['knob']} on {p['lane']} ({t['limit']}: {t['hits']} of {t['of']}): "
                     f"{len(p['argv'])} values, {why}" + (f" ({p['model']})" if p.get("model") else ""))
    return "\n".join(lines) or "  no binding knob to sweep"
