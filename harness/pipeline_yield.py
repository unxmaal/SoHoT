"""Discovery yield: GPU hours and GiB per decided verdict and per adoption, per lane, from the store (#2163)."""
from __future__ import annotations

from collections import defaultdict

from harness import discovery_flow as df
from harness import reasons

DAY = 86400.0
WINDOWS = (7, 30)
GIB = df.GIB
MEASURE = "measure"
#: The measure step ended these ways; the first two decided the candidate, the rest left it undecided.
ADOPTED, LOST = "adopted", "lost"
DECIDED = (ADOPTED, LOST)
KINDS = (ADOPTED, LOST, "lane_too_small", "underpowered", "confirming", "futile", "harness", "other")
#: More than this share of a lane's measure hours ending undecided marks it red.
RED_SHARE = 0.5
NO_LANE = ""


def kind_of(outcome: str, event: str = "", reason: str = "", failure_class: str = "") -> str:
    """What an adopt-tier verdict row amounts to: decided (adopted, lost on the candidate) or one undecided kind."""
    from harness import adopt
    if outcome == "measured":
        return ADOPTED
    if failure_class in (reasons.LANE_TOO_SMALL, reasons.UNDERPOWERED, reasons.CONFIRMING):
        return failure_class
    if event == adopt.FUTILITY:
        return "futile"
    if reason == reasons.HARNESS:
        return "harness"
    return LOST if outcome == "declined" and reason == reasons.CANDIDATE else "other"


def _gpu(conn, since: float) -> list[dict]:
    """Each finished gpu job as {lane weights, step, at, hours}; a job's hours split over its runs' lanes."""
    from harness import resources
    from harness.commands import loop_steps
    here, mine = df._mine(conn, "jobs.claimed")
    runs: dict[int, list] = defaultdict(list)
    ran, mine_r = df._mine(conn, "runs.ran_here")
    for r in conn.execute(f"SELECT id, lane, job_id FROM runs WHERE job_id IS NOT NULL AND recorded_at >= ? AND {ran}", (since - DAY, *mine_r)):
        runs[int(r["job_id"])].append((int(r["id"]), r["lane"] or NO_LANE))
    out = []
    for r in conn.execute("SELECT id, argv, kind, resource, requested_by, started_at, finished_at FROM jobs WHERE finished_at >= ? "
                          f"AND started_at IS NOT NULL AND resource IN ('gpu', '') AND {here} ORDER BY id", (since, *mine)):
        words = df._loads(r["argv"], [])
        if (r["resource"] or resources.classify(words, r["kind"] or "command")) != resources.GPU:
            continue
        step = loop_steps._step_of(words) if r["requested_by"] == "discover" else (r["requested_by"] or "manual")
        flag = [str(w) for w in words]
        lane = flag[flag.index("--lane") + 1] if "--lane" in flag[:-1] else NO_LANE
        got = runs.get(int(r["id"])) or [(None, lane)]
        hours = max(0.0, float(r["finished_at"]) - float(r["started_at"])) / 3600.0
        out += [{"lane": ln, "run": rid, "step": step or "other", "at": float(r["finished_at"]), "hours": hours / len(got)}
                for rid, ln in got]
    return out


def _verdicts(conn, since: float) -> list[dict]:
    here, mine = df._mine(conn, "verdicts.decided_here")
    out = []
    for r in conn.execute("SELECT v.run_id, v.outcome, v.event, v.reason, v.failure_class, v.decided_at, COALESCE(NULLIF(v.lane, ''), p.lane, '') AS lane "
                          "FROM verdicts v LEFT JOIN proposals p ON p.id = v.proposal_id WHERE v.tier = 'adopt' AND v.decided_at >= ? "
                          f"AND {here.replace('machine_id', 'v.machine_id')}", (since, *mine)):
        out.append({"lane": r["lane"] or NO_LANE, "run": r["run_id"], "at": float(r["decided_at"]),
                    "kind": kind_of(r["outcome"], r["event"], r["reason"], r["failure_class"])})
    return out


def _downloads(conn, since: float) -> list[dict]:
    fetched = df._fetched(conn, since)
    gone = {id(d) for d in df.lost(conn, fetched)}
    lanes = {int(r[0]): r[1] or NO_LANE for r in conn.execute("SELECT id, lane FROM proposals")}
    return [{"lane": lanes.get(d["proposal_id"], NO_LANE), "at": float(d["started_at"] or 0), "gib": d["bytes"] / GIB,
             "wasted": id(d) in gone} for d in fetched]


def _row(lane: str, jobs: list[dict], verdicts: list[dict], downloads: list[dict]) -> dict:
    steps: dict[str, float] = defaultdict(float)
    for j in jobs:
        steps[j["step"]] += j["hours"]
    kinds = {k: sum(1 for v in verdicts if v["kind"] == k) for k in KINDS}
    decided_runs = {v["run"] for v in verdicts if v["kind"] in DECIDED and v["run"] is not None}
    measure = [j for j in jobs if j["step"] == MEASURE]
    spent = sum(j["hours"] for j in measure)
    undecided = sum(j["hours"] for j in measure if j["run"] not in decided_runs)
    hours, decided, adopted = sum(steps.values()), sum(kinds[k] for k in DECIDED), kinds[ADOPTED]
    share = undecided / spent if spent else None
    return {"lane": lane, "gpu_hours": round(hours, 2), "steps": {s: round(h, 2) for s, h in sorted(steps.items())},
            "gib": round(sum(d["gib"] for d in downloads), 1), "wasted_gib": round(sum(d["gib"] for d in downloads if d["wasted"]), 1),
            "verdicts": kinds, "decided": decided, "undecided": sum(kinds.values()) - decided, "adopted": adopted,
            "hours_per_decided": round(hours / decided, 2) if decided else None,
            "hours_per_adoption": round(hours / adopted, 2) if adopted else None,
            "measure_hours": round(spent, 2), "undecided_measure_hours": round(undecided, 2),
            "undecided_share": round(share, 3) if share is not None else None,
            "red": share is not None and share > RED_SHARE}


def window(rows: tuple[list, list, list], since: float, until: float, lane: str = "") -> dict:
    """One window's per-lane rows and the all-lane total, over what finished or was decided in [since, until)."""
    inside = lambda xs: [x for x in xs if since <= x["at"] < until]  # noqa: E731
    jobs, verdicts, downloads = (inside(x) for x in rows)
    names = sorted({x["lane"] for x in jobs + verdicts + downloads if not lane or x["lane"] == lane} | ({lane} if lane else set()))
    pick = lambda xs, ln: [x for x in xs if x["lane"] == ln]  # noqa: E731
    out = [_row(ln, pick(jobs, ln), pick(verdicts, ln), pick(downloads, ln)) for ln in names]
    sel = (lambda xs: pick(xs, lane)) if lane else (lambda xs: xs)
    return {"since": since, "until": until, "lanes": out, "total": _row("all", sel(jobs), sel(verdicts), sel(downloads))}


def gather(conn, now: float, days: tuple[int, ...] = WINDOWS, lane: str = "") -> dict:
    """Yield per lane for each window in `days`, read from the store only."""
    if conn is None:
        return {"error": "store down: discovery yield not read"}
    longest = max(days)
    since = now - longest * DAY
    rows = (_gpu(conn, since), _verdicts(conn, since), _downloads(conn, since))
    return {"now": now, "lane": lane, "windows": {str(n): window(rows, now - n * DAY, now + 1, lane) for n in days}}


def trend(conn, now: float, days: int = 30) -> dict:
    """The last `days` against the `days` before: the hours per decided verdict and the undecided share of each."""
    rows = (_gpu(conn, now - 2 * days * DAY), _verdicts(conn, now - 2 * days * DAY), _downloads(conn, now - 2 * days * DAY))
    now_t = window(rows, now - days * DAY, now + 1)["total"]
    before = window(rows, now - 2 * days * DAY, now - days * DAY)["total"]
    return {"days": days, "now": now_t, "before": before}


def _n(v, spec: str = ".1f") -> str:
    return "-" if v is None else format(v, spec)


def trend_line(t: dict | None) -> str:
    """One morning line: how the hours per decided verdict and the undecided share moved against the window before."""
    if not t:
        return ""
    a, b = t["now"], t["before"]
    share = lambda r: "-" if r["undecided_share"] is None else f"{r['undecided_share']:.0%}"  # noqa: E731
    return (f"yield     {t['days']} d: {_n(a['hours_per_decided'])} h per decided verdict (before {_n(b['hours_per_decided'])}), "
            f"{_n(a['hours_per_adoption'])} h per adoption (before {_n(b['hours_per_adoption'])}), "
            f"{share(a)} of measure hours undecided (before {share(b)}), {a['decided']} decided / {a['undecided']} undecided")


def render(r: dict) -> list[str]:
    out = []
    for days, w in r["windows"].items():
        out.append(f"last {days} d")
        out.append(f"{'lane':<10} {'gpu h':>7} {'GiB':>8} {'wasted':>8} {'decided':>7} {'undec':>6} {'h/dec':>7} {'h/adopt':>8} {'undec share':>12}")
        for x in [*w["lanes"], w["total"]]:
            share = "-" if x["undecided_share"] is None else f"{x['undecided_share']:.0%}{' RED' if x['red'] else ''}"
            out.append(f"{x['lane'] or '(none)':<10} {x['gpu_hours']:>7.1f} {x['gib']:>8.1f} {x['wasted_gib']:>8.1f} {x['decided']:>7} "
                       f"{x['undecided']:>6} {_n(x['hours_per_decided']):>7} {_n(x['hours_per_adoption']):>8} {share:>12}")
        steps = w["total"]["steps"]
        out.append("steps     " + ", ".join(f"{s} {h:.1f} h" for s, h in steps.items()))
        out.append("verdicts  " + ", ".join(f"{k} {n}" for k, n in w["total"]["verdicts"].items() if n))
        out.append("")
    return out
