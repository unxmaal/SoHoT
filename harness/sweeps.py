"""A binding knob is swept across its range through the work queue, and the cheapest value tied with the best is recorded (#636).

binding.count says a knob keeps deciding a lane's results. This queues one
evals.run of the lane's served model per value the knob declares, reads the
runs those jobs store, and picks the cheapest value (fewest seconds) that the
paired sign test cannot tell from the best. The decision and its cost are
recorded in knob_sweeps; nothing here changes a constant. A sweep is not run
again for the same knob, lane, model and machine; a change of any of those
asks again.
"""
from __future__ import annotations

import json
import time
from collections import Counter

from harness import binding, knobs

REQUESTED_BY = binding.SWEEP
#: Below a person's jobs and beside reverify's.
PRIORITY = -10
CHOSEN, UNRUN, CANCELLED = "chosen", "unrun", "cancelled"


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


def plan(conn, *, now: float | None = None) -> list[dict]:
    """Every binding knob an eval can set, on a lane this machine serves, with the commands that would sweep it."""
    from harness import binding, memory_store as ms, reverify, runs
    now = time.time() if now is None else now
    served = reverify.served(conn)
    mid = ms.machine_row(conn)
    out = []
    for row in binding.binding(binding.count(conn, now=now, machines=runs.here(conn))):
        k = knobs.KNOBS[row["knob"]]
        item = served.get(row["lane"])
        if not k.receipt or item is None:
            continue
        out.append({"knob": k.name, "lane": row["lane"], "spec": item["spec"],
                    "candidate_id": item["candidate_id"], "machine_id": mid,
                    "trigger": {"limit": row["limit"], "hits": row["hits"], "of": row["of"]},
                    "argv": {v: argv(item, k, v) for v in k.values_for(row["lane"])},
                    "skip": _skip(conn, _key(conn, k.name, row["lane"], item["spec"], mid), now)})
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


def _cells(rows):
    seen: Counter = Counter()
    out = {}
    for r in rows:
        seen[r["case_id"]] += 1
        out[(r["case_id"], seen[r["case_id"]])] = r
    return out


def decide(values, outcomes: dict, alpha: float) -> tuple[object, dict]:
    """The cheapest swept value statistically tied with the best, and the cost table by str(value)."""
    from harness import paired
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
    base = _cells(stats[best]["rows"])
    table, tied = {}, []
    for v in (v for v in values if v in stats):
        mine = _cells(stats[v]["rows"])
        keys = base.keys() & mine.keys()
        lost = sum(1 for key in keys if base[key]["passed"] and not mine[key]["passed"])
        gained = sum(1 for key in keys if mine[key]["passed"] and not base[key]["passed"])
        p = paired.sign_test(min(lost, gained), lost + gained)
        ok = not (lost > gained and p <= alpha)
        table[str(v)] = {"passed": stats[v]["passed"], "n": stats[v]["n"],
                         "seconds": round(stats[v]["seconds"], 3), "lost": lost, "gained": gained,
                         "p": round(p, 4), "tied": ok, "best": v == best}
        if ok:
            tied.append(v)
    return min(tied, key=lambda v: (stats[v]["seconds"], pos[v])), table


def _run_of(conn, job_id: int) -> int | None:
    from harness import runs
    got = runs.for_job(conn, job_id)
    return got["id"] if got else None


def judge(conn, sw: dict) -> tuple[str, object, dict, str]:
    """(outcome, chosen, cost, detail) for one sweep whose jobs have all finished."""
    from harness import adopt, runs
    k = knobs.KNOBS[sw["knob"]]
    outcomes, ran = {}, {}
    for value, job_id in json.loads(sw["jobs"]):
        rid = _run_of(conn, job_id)
        if rid is None:
            continue
        ran[value] = rid
        outcomes[value] = (runs.rows(conn, rid, sw["candidate_id"]) if sw["candidate_id"] is not None
                           else runs.rows(conn, rid))
    chosen, cost = decide(k.values_for(sw["lane"]), outcomes, adopt.ALPHA)
    if chosen is None:
        return UNRUN, None, {}, f"none of the {len(json.loads(sw['jobs']))} jobs stored a run"
    for value, rid in ran.items():
        if str(value) in cost:
            cost[str(value)]["run_id"] = rid
    best = next(v for v in k.values_for(sw["lane"]) if cost.get(str(v), {}).get("best"))
    spent = sum(c["seconds"] for c in cost.values())
    c, b = cost[str(chosen)], cost[str(best)]
    detail = (f"{k.name} on {sw['lane']} for {sw['spec']}: chose {chosen:g} ({c['passed']} of {c['n']}, "
              f"{c['seconds']:g}s), tied with the best {best:g} ({b['passed']} of {b['n']}, "
              f"{b['seconds']:g}s); now {k.default(sw['lane']):g}; the sweep spent {spent:g}s")
    return CHOSEN, chosen, cost, detail


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
        lines.append(f"  {p['knob']} on {p['lane']} ({t['limit']}: {t['hits']} of {t['of']}): "
                     f"{len(p['argv'])} values, {why}")
    return "\n".join(lines) or "  no binding knob to sweep"
