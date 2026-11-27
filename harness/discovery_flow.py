"""The status page's discovery flow: node and edge counts, repeats and leaks from the store. #2158."""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime

from harness import refetch

WINDOW_S = 7 * 86400.0
GIB = float(1 << 30)
NODES = ("sweep", "inspect", "rank", "fetch", "screen", "measure", "adopt")
#: The sweep step whose jobs spend a node's time; the edge into the node is where a step's repeated failure shows.
STEP_NODE = {"sweep": "sweep", "repair": "inspect", "runtimes": "inspect", "inspect": "inspect", "queue": "rank",
             "screen": "screen", "measure": "measure"}
#: The sweep steps the panel draws no node for: they spend no candidate's way through the pipeline.
UNDRAWN = ("retests", "reverify", "knob-sweeps", "disk")
PASSED = ("queued", "screened", "measured")
#: A removal verdict that settled the candidate; queued and screened are deferrals. #2170.
DECIDED = refetch.DECIDED


def _loads(text, default):
    try:
        got = json.loads(text) if isinstance(text, str) else text
    except ValueError:
        return default
    return got if isinstance(got, type(default)) else default


def _mine(conn, rule: str) -> tuple[str, tuple]:
    from harness import machine_scope
    return machine_scope.here(conn, rule)


def _scalar(conn, sql: str, args: tuple = ()) -> int:
    row = conn.execute(sql, args).fetchone()
    return int(row[0] or 0) if row else 0


def _distinct(conn, tier: str, since: float, outcomes: tuple = (), event: str = "") -> int:
    here, mine = _mine(conn, "verdicts.decided_here")
    sql, args = f"SELECT COUNT(DISTINCT proposal_id) FROM verdicts WHERE tier = ? AND decided_at >= ? AND {here}", [tier, since, *mine]
    if outcomes:
        sql += f" AND outcome IN ({','.join('?' * len(outcomes))})"
        args += list(outcomes)
    if event:
        sql += " AND event = ?"
        args.append(event)
    return _scalar(conn, sql, tuple(args))


def _steps(conn, since: float) -> list[dict]:
    from harness.commands import loop_steps
    out = []
    here, mine = _mine(conn, "jobs.claimed")
    for r in conn.execute("SELECT id, argv, state, rc, started_at, finished_at FROM jobs WHERE requested_by = ? AND created_at >= ? "
                          f"AND {here} ORDER BY id", ("discover", since, *mine)):
        words = _loads(r["argv"], [])
        step = loop_steps._step_of(words)
        if step:
            out.append({"id": r["id"], "step": step, "cycle": loop_steps._cycle_of(words), "state": r["state"], "rc": r["rc"],
                        "took": max(0.0, float(r["finished_at"]) - float(r["started_at"])) if r["started_at"] and r["finished_at"] else 0.0})
    return out


def _fetched(conn, since: float) -> list[dict]:
    here, mine = _mine(conn, "downloads.mine")
    got = conn.execute("SELECT proposal_id, repo, bytes, started_at, finished_at, removed_at, removal_verdict_id FROM downloads "
                       "WHERE origin = 'fetch' AND bytes > 0 AND started_at >= ? AND (complete = 1 OR state IN ('complete', 'removed')) "
                       f"AND {here}", (since, *mine)).fetchall()
    return [dict(r) if hasattr(r, "keys") else dict(zip(("proposal_id", "repo", "bytes", "started_at", "finished_at", "removed_at",
                                                         "removal_verdict_id"), r)) for r in got]


def _powers(conn, run_ids: list[int]) -> dict[int, float]:
    """The planned power of each measure run, from its verdict or its paused row."""
    if not run_ids:
        return {}
    marks = ",".join("?" * len(run_ids))
    out: dict[int, float] = {}
    paused, mine_p = _mine(conn, "paused_runs.mine")
    decided, mine_v = _mine(conn, "verdicts.decided_here")
    for r in conn.execute(f"SELECT run_id, plan FROM paused_runs WHERE run_id IN ({marks}) AND {paused}", [*run_ids, *mine_p]):
        p = (_loads(r["plan"], {}).get("power") or {})
        if isinstance(p, dict) and p.get("power") is not None:
            out[int(r["run_id"])] = float(p["power"])
    for r in conn.execute(f"SELECT run_id, power FROM verdicts WHERE run_id IN ({marks}) AND tier IN ('measure', 'adopt') AND {decided}",
                          [*run_ids, *mine_v]):
        p = _loads(r["power"], {}).get("power")
        if isinstance(p, (int, float)) and not isinstance(p, bool):
            out[int(r["run_id"])] = float(p)
    return out


def _pairs(conn, since: float, cycles: dict[int, str]) -> tuple[list[dict], dict[int, str], int]:
    """(pairs measured more than once in one sweep, lane of each run, runs) over the window."""
    here, mine = _mine(conn, "runs.ran_here")
    runs = conn.execute(f"SELECT id, lane, job_id, recorded_at FROM runs WHERE tier = 'measure' AND recorded_at >= ? AND {here}",
                        (since, *mine)).fetchall()
    ids = {int(r["id"]) for r in runs}
    who: dict[int, set] = defaultdict(set)
    for r in conn.execute("SELECT DISTINCT run_id, candidate FROM results WHERE run_id IN "
                          f"(SELECT id FROM runs WHERE tier = 'measure' AND recorded_at >= ? AND {here})", (since, *mine)):
        who[int(r["run_id"])].add(r["candidate"])
    seen: Counter = Counter()
    for r in runs:
        names = sorted(who.get(int(r["id"])) or ())
        if len(names) == 2:
            day = datetime.fromtimestamp(float(r["recorded_at"])).strftime("%Y-%m-%d")
            seen[(cycles.get(r["job_id"]) or day, r["lane"], " vs ".join(names))] += 1
    out = [{"name": f"{lane}: {pair}", "n": n, "cycle": cycle} for (cycle, lane, pair), n in seen.items() if n > 1]
    return out, {int(r["id"]): r["lane"] for r in runs}, len(ids)


def _failures(steps: list[dict]) -> list[dict]:
    from harness import workqueue as wq
    bad: dict = defaultdict(list)
    for s in steps:
        if s["state"] == wq.FAILED or (s["rc"] not in (None, 0) and s["state"] != wq.DONE):
            bad[(s["cycle"], s["step"])].append(s["id"])
    return [{"name": f"{step} step failed again", "n": len(ids), "cycle": cycle, "step": step, "jobs": ids}
            for (cycle, step), ids in bad.items() if len(ids) > 1]


def wasted(conn, fetched: list[dict]) -> list[dict]:
    """The fetched downloads removed again that bought nothing, each marked undecided and again; removed with no decision, or fetched again later. #2170."""
    here, mine = _mine(conn, "verdicts.decided_here")
    last = {int(r[0]): float(r[1]) for r in conn.execute(
        "SELECT proposal_id, MAX(decided_at) FROM verdicts WHERE tier IN ('screen', 'measure', 'adopt') AND proposal_id IS NOT NULL "
        f"AND {here} GROUP BY proposal_id", mine)}
    ids = sorted({d["removal_verdict_id"] for d in fetched if d["removal_verdict_id"] is not None})
    outcome = {int(r[0]): r[1] for r in conn.execute(f"SELECT id, outcome FROM verdicts WHERE id IN ({','.join('?' * len(ids))})", ids)} if ids else {}
    latest: dict = {}
    for d in fetched:
        latest[d["repo"]] = max(latest.get(d["repo"], 0.0), float(d["started_at"] or 0))
    out = []
    for d in fetched:
        if d["removed_at"] is None:
            continue
        pid, started = d["proposal_id"], float(d["started_at"] or 0)
        if d["removal_verdict_id"] is None:
            undecided = not (pid is not None and last.get(pid, 0.0) >= started)
        else:
            undecided = outcome.get(d["removal_verdict_id"]) not in DECIDED
        again = bool(d["repo"]) and latest.get(d["repo"], 0.0) > started
        if undecided or again:
            d["undecided"], d["again"] = undecided, again
            out.append(d)
    return out


def waste_gib(rows: list[dict]) -> dict:
    """GiB wasted in all, and each component: removed with no decision, fetched again later (the two may overlap)."""
    gib = lambda xs: round(sum(d["bytes"] for d in xs) / GIB, 1)  # noqa: E731
    return {"gib": gib(rows), "undecided_gib": gib([d for d in rows if d["undecided"]]), "again_gib": gib([d for d in rows if d["again"]]),
            "n": len(rows)}


def _downloads(conn, since: float, fetched: list[dict]) -> tuple[list[dict], dict, dict]:
    """(candidates fetched more than once, the wasted-download leak, the evicted-while-queued leak)."""
    key = lambda d: d["proposal_id"] if d["proposal_id"] is not None else d["repo"]  # noqa: E731
    count = Counter(key(d) for d in fetched)
    names = {d["proposal_id"]: d["repo"] for d in fetched}
    twice = [{"name": names.get(k) or str(k), "n": n} for k, n in count.items() if n > 1]
    state = {int(r[0]): r[1] for r in conn.execute("SELECT id, state FROM proposals")}
    w = waste_gib(wasted(conn, fetched))
    evicted = {d["proposal_id"] for d in fetched if d["removed_at"] is not None and d["proposal_id"] is not None
               and state.get(d["proposal_id"]) == "screened"}
    gone = {"key": "deleted", "n": w["gib"], "undecided_gib": w["undecided_gib"], "again_gib": w["again_gib"],
            "text": f"{w['gib']:.1f} GiB downloaded, then removed for nothing ({w['n']} download(s)): {w['undecided_gib']:.1f} GiB removed "
                    f"with no decision on the candidate, {w['again_gib']:.1f} GiB fetched again later"}
    out = {"key": "evicted", "n": len(evicted), "text": f"weights of {len(evicted)} candidate(s) evicted while their measure was still queued"}
    return twice, gone, out


def gather(conn, now: float, window_s: float = WINDOW_S) -> dict:
    """Nodes (in, out, seconds), edges (count, repeats) and leak markers over the last `window_s`, read from the store."""
    from harness import power, wip
    from harness import workqueue as wq
    from harness.commands import loop_steps
    if conn is None:
        return {"error": "store down: discovery flow not read"}
    since = now - window_s
    steps = _steps(conn, since)
    secs: Counter = Counter()
    for s in steps:
        secs[STEP_NODE.get(s["step"], "")] += s["took"]
    fetched = _fetched(conn, since)
    secs["fetch"] = sum(max(0.0, float(d["finished_at"]) - float(d["started_at"])) for d in fetched if d["finished_at"] and d["started_at"])
    secs["screen"] = max(0.0, secs["screen"] - secs["fetch"])
    cycles = {s["id"]: s["cycle"] for s in steps}
    ran, mine_r = _mine(conn, "runs.ran_here")
    jobs = {int(r[0]): _loads(r[1], []) for r in conn.execute(
        f"SELECT id, argv FROM jobs WHERE id IN (SELECT job_id FROM runs WHERE tier = 'measure' AND recorded_at >= ? AND job_id IS NOT NULL AND {ran})",
        (since, *mine_r))}
    cycles |= {j: loop_steps._cycle_of(w) for j, w in jobs.items() if j not in cycles}
    pairs, lane_of, runs = _pairs(conn, since, cycles)
    twice, gone, evicted = _downloads(conn, since, fetched)
    failed = _failures(steps)
    sweeps = sum(1 for s in steps if s["step"] == "sweep" and s["state"] == wq.DONE)
    fresh = _scalar(conn, "SELECT COUNT(*) FROM proposals WHERE first_seen >= ?", (since,))
    inspected, passed = _distinct(conn, "inspect", since), _distinct(conn, "inspect", since, PASSED)
    taken, downloaded = _distinct(conn, "fetch", since), _distinct(conn, "fetch", since, event="downloaded")
    screened, kept = _distinct(conn, "screen", since), _distinct(conn, "screen", since, ("screened",))
    decided = _distinct(conn, "adopt", since)
    adopted = _distinct(conn, "adopt", since, ("measured",))
    counts = {"sweep": (sweeps, fresh), "inspect": (inspected, passed), "rank": (passed, taken),
              "fetch": (taken, downloaded), "screen": (screened, kept), "measure": (runs, decided), "adopt": (decided, adopted)}
    nodes = [{"name": n, "in": counts[n][0], "out": counts[n][1], "seconds": round(secs.get(n, 0.0), 1) or None} for n in NODES]
    again = refetch.redone(conn, now)
    next(n for n in nodes if n["name"] == "fetch")["redone"] = again
    edge_n = [inspected, passed, taken, screened, kept, decided]
    repeats: dict[tuple, list] = defaultdict(list)
    repeats[("rank", "fetch")] += [{**t, "kind": "fetch"} for t in twice]
    repeats[("screen", "measure")] += [{**p, "kind": "pair"} for p in pairs]
    for f in failed:
        node = STEP_NODE.get(f["step"], "")
        into = NODES[NODES.index(node) - 1] if node in NODES[1:] else ""
        if into:
            repeats[(into, node)].append({**f, "kind": "failure"})
    edges = [{"src": a, "dst": b, "n": n, "repeats": repeats.get((a, b), [])} for (a, b), n in zip(zip(NODES, NODES[1:]), edge_n)]
    power_of = _powers(conn, sorted(lane_of))
    weak = {rid: p for rid, p in power_of.items() if p < power.TARGET}
    backlog = _scalar(conn, "SELECT COUNT(*) FROM proposals WHERE state = 'screened'")
    leaks = []
    if gone["n"]:
        leaks.append(gone)
    if weak:
        lanes = ", ".join(sorted({f"{lane_of[r]} {p:.2f}" for r, p in weak.items()}))
        leaks.append({"key": "power", "n": len(weak), "text": f"{len(weak)} measure run(s) started with power below {power.TARGET}: {lanes}"})
    if backlog > runs:
        leaks.append({"key": "backlog", "n": backlog, "need": "discovery-screens-nothing",
                      "text": f"{backlog} screened candidate(s) wait for measure; it finished {runs} run(s) in {window_s / 86400:.0f} d"})
    if evicted["n"]:
        leaks.append(evicted)
    if again["n"]:
        leaks.append({"key": "refetched", "n": again["gib"], "text": f"{again['gib']:.1f} GiB downloaded again in {refetch.REFETCH_WINDOW_S / 3600:g} h "
                      f"({again['n']} download(s) of {again['repos']} repo(s) already fetched): Hugging Face warns of an egress quota"})
    return {"since": since, "until": now, "cycle": next((s["cycle"] for s in reversed(steps) if s["cycle"]), ""),
            "nodes": nodes, "edges": edges, "leaks": leaks, "wip": wip.status(conn)}
