"""Replay past fetch runs from their own verdicts, and project future nights, with and without the pass-over term (#1288)."""
from __future__ import annotations

import random
import re
import statistics
import time

from harness import fetching, rank, reasons
from harness import memory_store as ms

#: Seconds with no fetch decision that end one run; a night's passes are about 2 h apart, day runs 3 h.
GAP_S = 9000.0
DAY = 86400.0
_BUDGET = re.compile(r"past its (\d+(?:\.\d+)?) GiB budget")


def runs(conn, since: float) -> list[dict]:
    """Each fetch run since `since`: its start, budget, and the rows it fetched or refused for the remainder, in order."""
    rows = conn.execute("""
        SELECT v.decided_at AS at, v.detail, p.name, p.size_bytes,
               -- A download's verdict lands when it finishes; the run decided on it when it started.
               COALESCE((SELECT MAX(d.started_at) FROM downloads d WHERE d.proposal_id = p.id
                           AND d.started_at <= v.decided_at AND v.detail = :downloaded), v.decided_at) AS start
          FROM verdicts v JOIN proposals p ON p.id = v.proposal_id
         WHERE v.tier = 'fetch' AND v.decided_at >= :since
           AND (v.detail = :downloaded OR (v.reason = :limit AND COALESCE(v.until, '') = '' AND v.detail GLOB :refusal))
         ORDER BY v.id""", {"since": since, "downloaded": fetching.DOWNLOADED, "limit": reasons.LIMIT,
                            "refusal": f"[0-9]* GiB {fetching.PASSED} *"}).fetchall()
    out: list[dict] = []
    for r in rows:
        if not out or r["start"] - out[-1]["last"] > GAP_S:
            out.append({"at": r["start"], "last": r["at"], "budget": 0.0, "rows": [], "fetched": []})
        run = out[-1]
        run["last"] = r["at"]
        if r["name"] not in {x["name"] for x in run["rows"]}:
            run["rows"].append({"name": r["name"], "size": int(r["size_bytes"] or 0)})
        if r["detail"] == fetching.DOWNLOADED:
            run["fetched"].append(r["name"])
        elif not run["budget"]:
            m = _BUDGET.search(r["detail"] or "")
            run["budget"] = float(m.group(1)) if m else 0.0
    return [r for r in out if r["budget"]]


def _night(ranked: list[dict], sizes: dict, budget: float, conn) -> list[str]:
    """What one fetch run takes from ranked rows: lane turns, then each row that still fits the budget."""
    spent, got = 0, []
    for r in fetching.by_lane_turns([r for r in ranked if r["name"] in sizes], conn):
        if spent + sizes[r["name"]] <= budget * fetching.GIB:
            spent += sizes[r["name"]]
            got.append(r["name"])
    return got


def replay(conn, since: float, **rank_kw) -> list[dict]:
    """Each run's actual fetches, what today's rank would fetch from the same rows without the term, and with it."""
    out = []
    for run in runs(conn, since):
        names = [r["name"] for r in run["rows"]]
        sizes = {r["name"]: r["size"] for r in run["rows"]}
        rows = ms.judgeable(conn, names=names)
        passed = rank.passed_over(conn, before=run["at"])
        orders = {label: _night(rank.rank(rows, keep_laneless=True, now=run["at"], passed=got, trace=False, conn=conn, **rank_kw),
                                sizes, run["budget"], conn)
                  for label, got in (("without", {}), ("with", passed))}
        out.append({"at": run["at"], "budget": run["budget"], "considered": len(names), "fetched": run["fetched"],
                    **orders, "passed": {n: passed[n] for n in names if n in passed}})
    return out


def project(conn, nights: int, *, budget_gib: float, arrivals: int = 0, term: bool = True, seed: int = 1288,
            now: float | None = None, **rank_kw) -> dict[str, int]:
    """name -> the night today's fittable queue row fetches, one run a night, with `arrivals` fresh clones of queue rows a night."""
    now = time.time() if now is None else now
    budget = int(budget_gib * fetching.GIB)
    queue = [r for r in fetching.queued(conn) if not fetching.why_not(r, budget=budget)]
    sizes = {r["name"]: int(r.get("size_bytes") or 0) for r in queue}
    rows = ms.judgeable(conn, names=list(sizes))
    passed = rank.passed_over(conn, before=now) if term else {}
    rng, left, when = random.Random(seed), set(sizes), {}
    pool = list(rows)
    for n in range(1, nights + 1):
        at = now + n * DAY
        for i in range(arrivals if pool else 0):
            src = rng.choice(pool)
            fresh = {**src, "name": f"arrival-{n}-{i}/{src['name'].rsplit('/', 1)[-1]}",
                     "first_seen": at - 3600, "last_seen": at - 3600}
            rows.append(fresh)
            sizes[fresh["name"]] = sizes[src["name"]]
            left.add(fresh["name"])
        ranked = rank.rank([r for r in rows if r["name"] in left], keep_laneless=True, now=at, trace=False,
                           passed=passed if term else {}, conn=conn, **rank_kw)
        got = _night(ranked, sizes, budget_gib, conn)
        for name in got:
            when[name] = n
            left.discard(name)
        if term:
            for r in ranked:
                if r["name"] in left and sizes[r["name"]] <= budget:
                    passed[r["name"]] = passed.get(r["name"], 0) + 1
    return {name: when.get(name, 0) for name in sizes if not name.startswith("arrival-")}


def report(conn, days: float, *, now: float | None = None, **rank_kw) -> list[str]:
    """Lines for `soh fetch --replay`: per run, what it fetched and what the term changes."""
    now = time.time() if now is None else now
    lines = [f"replay of {days:g} day(s) of fetch runs; each run replayed alone on the rows it considered, "
             f"ranked as of today with pass-over {rank.PASSED_OVER:g}/day up to {rank.PASSED_OVER_MAX:g}"]
    for run in replay(conn, now - days * DAY, **rank_kw):
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(run["at"]))
        lines.append(f"\n{when}  budget {run['budget']:g} GiB, {run['considered']} considered")
        lines.append(f"  fetched:   {', '.join(run['fetched']) or '-'}")
        lines.append(f"  replayed:  {', '.join(run['without']) or '-'}")
        lines.append(f"  with term: {', '.join(run['with']) or '-'}")
        lines += [f"    + {n} (passed over on {run['passed'].get(n, 0)} day(s))" for n in run["with"] if n not in run["without"]]
        lines += [f"    - {n}" for n in run["without"] if n not in run["with"]]
    return lines


def projection(conn, nights: int, *, budget_gib: float, arrivals: int, watch=(), now: float | None = None,
               **rank_kw) -> list[str]:
    """Lines for `soh fetch --replay DAYS --project NIGHTS`: today's queue waits, with the term and without."""
    got = {term: project(conn, nights, budget_gib=budget_gib, arrivals=arrivals, term=term, now=now, **rank_kw)
           for term in (False, True)}
    lines = [f"\nprojection: {nights} nights of {budget_gib:g} GiB, {arrivals} fresh arrival(s) a night, "
             f"{len(got[True])} fittable rows today"]
    for term, when in got.items():
        waits = [w or nights + 1 for w in when.values()]
        lines.append(f"  {'with term' if term else 'no term  '}: unfetched {sum(w > nights for w in waits)}, "
                     f"median {statistics.median(waits):g} nights, worst {max(waits)}" if waits else "  nothing queued")
    if not watch:
        po = rank.passed_over(conn, before=now)
        watch = sorted((n for n in po if n in got[True]), key=lambda n: -po[n])[:5]
    for name in watch:
        if name in got[True]:
            lines.append(f"  {name}: night {got[False][name] or '-'} without, {got[True][name] or '-'} with")
    return lines
