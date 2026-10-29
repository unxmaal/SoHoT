"""Each real workload as all local, all Claude and hybrid, from stored rows and the shadow replay's summary. #687.

    soh baseline [--store PATH] [--summary PATH | --replay DIR [--save PATH]] [--lane LANE] [--gate P] [--bar RATE]

Reads the store read-only and writes nothing to it.
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from evals import repo_routing
from evals.analysis import demand
from evals.analysis.demand import replay as rp
from harness import intervals
from harness.runs import _split_case

DEMAND = Path(__file__).resolve().parent / "analysis" / "demand"
SUMMARY = DEMAND / "replay.jsonl"
MANIFEST = DEMAND / "manifest.jsonl"
STRATA = DEMAND / "strata.json"
#: The lanes the table reads by default: the ones #687 names and the text lanes the replay routes to.
LANES = ("repo", "decide", "claims", "code", "extract")
#: Confidence under which a decide field goes to Claude.
DECIDE_GATE = 0.95
CLAUDE = "claude-code:"
USABLE = rp.GRADES[:2]


class Refused(Exception):
    """The table cannot be built from what is stored; the message says why."""


def _rate(k: int, n: int) -> dict:
    lo, hi = intervals.wilson(k, n)
    return {"k": k, "n": n, "rate": round(k / n, 4) if n else None, "ci": [lo, hi]}


def _tokens(tokens: dict, cases) -> dict:
    got = [tokens[c] for c in cases if c in tokens]
    return {"in": sum(t[0] for t in got), "out": sum(t[1] for t in got)}


def cascade(items: list[dict], tokens: dict) -> dict:
    """Three arms over items {case, local, claude, keep}: local alone, Claude alone, and local kept where the gate
    passes it, else Claude. claude None means no stored Claude answer, and the hybrid becomes [low, high] bounds.
    tokens: case -> (in, out) Claude spent on it, counted once per case."""
    n = len(items)
    sent = [i for i in items if not i["keep"]]
    kept_ok = sum(bool(i["local"]) for i in items if i["keep"])
    out = {"n": n, "local": _rate(sum(bool(i["local"]) for i in items), n), "to_claude": len(sent),
           "accepted_wrong": sum(not i["local"] for i in items if i["keep"])}
    if items and all(i["claude"] is not None for i in items):
        out.update(claude=_rate(sum(bool(i["claude"]) for i in items), n),
                   hybrid=_rate(kept_ok + sum(bool(i["claude"]) for i in sent), n), hybrid_bounds=None,
                   claude_tokens=_tokens(tokens, {i["case"] for i in items}),
                   hybrid_tokens=_tokens(tokens, {i["case"] for i in sent}))
    else:
        out.update(claude=None, hybrid=None, hybrid_bounds=[kept_ok, kept_ok + len(sent)], claude_tokens=None,
                   hybrid_tokens=None)
    return out


def _no_gate(got: dict) -> dict:
    return {**got, "hybrid": None, "hybrid_bounds": None, "to_claude": None, "accepted_wrong": None,
            "hybrid_tokens": None}


def _row(workload: str, got: dict, *, gate: str, local_s: float, unit: str = "units", share=None, runs=None,
         note: str = "") -> dict:
    return {"workload": workload, "unit": unit, "share": share, **got, "gate": gate,
            "local_gpu_min": round(local_s / 60, 2), "runs": runs or {}, "note": note}


# ---- the shadow replay (#1161), from its numbers-only summary

def summarise(out: Path) -> list[dict]:
    """A replay directory's numbers and labels only: units, every reply's grade, seconds and tokens, and the judge's
    grade of each session's own record. No prompt, reply, record or judge reason."""
    out = Path(out)
    packets = rp._jsonl(out / "packets.jsonl")
    if not packets:
        raise Refused(f"no packets.jsonl under the replay directory {out.name}")
    prepared = out / "prepared.json"
    meta = json.loads(prepared.read_text(encoding="utf-8")) if prepared.exists() else {}
    grades = {}
    for path in sorted(out.glob("grades-*.jsonl")):
        for g in rp._jsonl(path):
            grades[(g["id"], g.get("candidate", rp.ADOPTED), g.get("repeat", 1))] = (g.get("grade"), g.get("grader"))
    replies = []
    for path in sorted(out.glob("replies-*.jsonl")):
        for r in rp._jsonl(path):
            key = (r["id"], r.get("candidate", rp.ADOPTED), r.get("repeat", 1))
            grade, grader = grades.get(key, (None, None))
            replies.append({"kind": "reply", "id": key[0], "candidate": key[1], "repeat": key[2], "grade": grade,
                            "grader": grader, "seconds": r.get("seconds"), "prompt_tokens": r.get("prompt_tokens"),
                            "completion_tokens": r.get("completion_tokens"), "model": r.get("model") or "",
                            "error": bool(r.get("error"))})
    own = [{"kind": "self", "id": c["id"], "grade": c.get("grade")}
           for c in rp._jsonl(out / "calibration.jsonl") if c.get("plant") == rp.SELF]
    head = {"kind": "meta", "now": meta.get("now"), "seed": meta.get("seed"), "selected": meta.get("selected"),
            "missing": len(meta.get("missing") or []), "candidates": sorted({r["candidate"] for r in replies})}
    units = [{"kind": "unit", "id": p["id"], "shape": p["shape"], "lane": p.get("lane") or "",
              "control": bool(p.get("control"))} for p in packets]
    return ([head] + sorted(units, key=lambda u: u["id"])
            + sorted(replies, key=lambda r: (r["candidate"], r["repeat"], r["id"])) + sorted(own, key=lambda s: s["id"]))


def save(records: list[dict], path: Path) -> None:
    Path(path).write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in records), encoding="utf-8")


def load_summary(path: Path) -> list[dict]:
    return rp._jsonl(Path(path))


def _first(records: list[dict], candidate: str) -> dict:
    mine = [r for r in records if r["kind"] == "reply" and r["candidate"] == candidate]
    if not mine:
        return {}
    first = min(r["repeat"] for r in mine)
    return {r["id"]: r for r in mine if r["repeat"] == first and r.get("grade")}


def agreement(records: list[dict], candidate: str = rp.ADOPTED) -> dict | None:
    """How often the first two replays of each unit got the same grade."""
    by = defaultdict(dict)
    for r in records:
        if r["kind"] == "reply" and r["candidate"] == candidate and r.get("grade"):
            by[r["repeat"]][r["id"]] = r["grade"]
    reps = sorted(by)[:2]
    if len(reps) < 2:
        return None
    a, b = by[reps[0]], by[reps[1]]
    both = sorted(set(a) & set(b))
    return {**_rate(sum(a[i] == b[i] for i in both), len(both)), "needs": rp.AGREE_MIN}


def replay_rows(records: list[dict], manifest: list[dict], strata: dict, candidate: str = rp.ADOPTED) -> list[dict]:
    """One row per census shape among the fitting units, then all fitting units: the local candidate's first replay,
    the session's own Claude record as the same blind judge graded it, and the review gate (local kept when graded
    usable, else Claude's record). Claude tokens are what the session spent, from the census manifest."""
    units = {r["id"]: r for r in records if r["kind"] == "unit"}
    reply = _first(records, candidate)
    own = {r["id"]: r.get("grade") for r in records if r["kind"] == "self"}
    man = {m["id"]: m for m in manifest}
    labels = {m["id"]: m.get("final") or {} for m in manifest}
    tokens = {i: (man[i].get("tokens_in") or 0, man[i].get("tokens_out") or 0) for i in units if i in man}
    fit = [u for u in units.values() if not u["control"] and u["id"] in reply]

    def item(u):
        local = reply[u["id"]]["grade"] in USABLE
        claude = None if own.get(u["id"]) is None else own[u["id"]] in USABLE
        return {"case": u["id"], "local": local, "claude": claude, "keep": local}

    def share(cell):
        try:
            return round(demand.estimate(manifest, strata, labels, cell, "tokens_out"), 4) if manifest else None
        except (KeyError, ZeroDivisionError):
            return None

    def row(name, group, cell):
        secs = sum(reply[u["id"]].get("seconds") or 0.0 for u in group)
        return _row(f"replay {name}", cascade([item(u) for u in group], tokens), gate="review", local_s=secs,
                    share=share(cell), runs={"replay": candidate})
    shapes = defaultdict(list)
    for u in fit:
        shapes[u["shape"]].append(u)
    rows = [row(s, g, lambda lab, s=s: lab.get("shape") == s and lab.get("fit") in rp.FITTING)
            for s, g in shapes.items()]
    rows.sort(key=lambda r: (-(r["share"] or 0.0), r["workload"]))
    if fit:
        rows.append(row("all fitting", fit, lambda lab: lab.get("fit") in rp.FITTING))
    return rows


# ---- lanes, from the store

def _newest(conn, lane: str, *, claude: bool, digest: str | None = None, candidate_id: int | None = None):
    sql = ("SELECT r.id FROM runs r WHERE r.lane = ? AND r.tier = 'measure' AND EXISTS (SELECT 1 FROM results x "
           "WHERE x.run_id = r.id AND x.candidate " + ("LIKE" if claude else "NOT LIKE") + " ?")
    args: list = [lane, f"{CLAUDE}%"]
    if candidate_id is not None:
        sql += " AND x.candidate_id = ?"
        args.append(candidate_id)
    sql += ")"
    if digest is not None:
        sql += " AND r.cases_digest = ?"
        args.append(digest)
    got = conn.execute(sql + " ORDER BY COALESCE(r.generated_at, r.recorded_at) DESC, r.id DESC LIMIT 1",
                       args).fetchone()
    return got[0] if got else None


def _adopted(conn, lane: str):
    got = conn.execute("SELECT candidate_id FROM adoptions WHERE lane = ? ORDER BY adopted_at DESC, id DESC LIMIT 1",
                       (lane,)).fetchone()
    return got[0] if got else None


def _load(conn, run_id: int, candidate: str) -> dict:
    """case -> the first-repeat row of one candidate in one run."""
    out = {}
    for case, rep, passed, fc, sec, metrics, detail in conn.execute(
            "SELECT case_id, repeat_index, passed, failure_class, seconds, metrics, detail FROM results "
            "WHERE run_id = ? AND candidate = ? ORDER BY seq", (run_id, candidate)):
        base, nth = _split_case(case)
        if (rep or 1) != 1 or nth != 1:
            continue
        m = json.loads(metrics or "{}")
        out[base] = {"passed": bool(passed), "applied": bool(m.get("patch_applied")), "failure_class": fc or "",
                     "p2p_broken": "pass_to_pass broken" in (detail or ""), "seconds": float(sec or 0.0),
                     "metrics": m}
    return out


def _cost(m: dict) -> tuple[int, int]:
    return (int(m.get("prompt_tokens") or 0) + int(m.get("cache_read_tokens") or 0)
            + int(m.get("cache_creation_tokens") or 0), int(m.get("completion_tokens") or 0))


def _locals(conn, run_id: int, adopted) -> list[str]:
    if adopted is not None:
        got = conn.execute("SELECT DISTINCT candidate FROM results WHERE run_id = ? AND candidate_id = ?",
                           (run_id, adopted)).fetchall()
        if got:
            return [g[0] for g in got]
    return [g[0] for g in conn.execute("SELECT DISTINCT candidate FROM results WHERE run_id = ? AND candidate NOT "
                                       "LIKE ? ORDER BY candidate", (run_id, f"{CLAUDE}%"))]


def _fields(rows: dict) -> bool:
    return bool(rows) and all(isinstance(r["metrics"].get("decisions"), list) for r in rows.values())


def _lane(lane: str, name: str, lrows: dict, crows: dict | None, gate: float, runs: dict) -> dict:
    by = {"local": lrows, **({"cloud": crows} if crows is not None else {})}
    cases, never, _ = repo_routing.shared(by)
    tokens = {k: _cost(crows[k]["metrics"]) for k in cases} if crows is not None else {}
    secs = sum(lrows[k]["seconds"] for k in cases)
    note = "" if crows is not None else "no stored claude run"
    if never:
        note = "; ".join(x for x in (note, f"{len(never)} never ran") if x)
    if not cases:
        note = "; ".join(x for x in (note, "no case both runs ran on their first repeat") if x)
    if crows is not None and cases and not any(tokens[k][0] for k in cases) and any(tokens[k][1] for k in cases):
        note = "; ".join(x for x in (note, "claude input tokens not stored") if x)
    if lane == "decide" and _fields({k: lrows[k] for k in cases}):
        items = []
        for k in cases:
            theirs = crows[k]["metrics"].get("decisions") or [] if crows is not None else []
            for i, (p, ok) in enumerate(lrows[k]["metrics"]["decisions"]):
                claude = (bool(theirs[i][1]) if i < len(theirs) else False) if crows is not None else None
                items.append({"case": k, "local": bool(ok), "claude": claude, "keep": float(p) >= gate})
        return _row(name, cascade(items, tokens), gate=f"confidence >= {gate:g}", local_s=secs, unit="fields",
                    runs=runs, note=note)
    if lane == "repo":
        items = [{"case": k, "local": lrows[k]["passed"], "claude": crows[k]["passed"] if crows is not None else None,
                  "keep": repo_routing.gate(lrows[k], "visible")} for k in cases]
        return _row(name, cascade(items, tokens), gate="visible (#891)", local_s=secs, runs=runs, note=note)
    items = [{"case": k, "local": lrows[k]["passed"], "claude": crows[k]["passed"] if crows is not None else None,
              "keep": True} for k in cases]
    return _row(name, _no_gate(cascade(items, tokens)), gate="none", local_s=secs, runs=runs, note=note)


def lane_rows(conn, lanes, gate: float = DECIDE_GATE) -> list[dict]:
    """Per lane: the newest Claude run, and the local run on its exam holding the lane's adopted candidate (else the
    newest local run there); with no Claude run, the newest local run alone."""
    rows = []
    for lane in lanes:
        cloud = _newest(conn, lane, claude=True)
        digest = conn.execute("SELECT cases_digest FROM runs WHERE id = ?", (cloud,)).fetchone()[0] if cloud else None
        adopted = _adopted(conn, lane)
        local = ((_newest(conn, lane, claude=False, digest=digest, candidate_id=adopted) if adopted is not None
                  else None) or _newest(conn, lane, claude=False, digest=digest))
        if local is None:
            rows.append(_row(lane, _no_gate(cascade([], {})), gate="none", local_s=0.0,
                             note="no stored run" + (f" on the exam of claude run {cloud}" if cloud else "")))
            continue
        crows = None
        if cloud:
            (ckey,) = conn.execute("SELECT candidate FROM results WHERE run_id = ? AND candidate LIKE ? LIMIT 1",
                                   (cloud, f"{CLAUDE}%")).fetchone()
            crows = _load(conn, cloud, ckey)
        names = _locals(conn, local, adopted)
        for cand in names:
            name = lane if len(names) == 1 else f"{lane} {cand}"
            runs = {"local": local, **({"claude": cloud} if cloud else {}), "candidate": cand}
            rows.append(_lane(lane, name, _load(conn, local, cand), crows, gate, runs))
    return rows


# ---- the table

def verdict(rate: dict | None, bar: float | None) -> str:
    """keep where the local interval's lower bound clears the bar, return where its upper bound falls short."""
    if bar is None:
        return ""
    if not rate or not rate["n"]:
        return "undecided"
    lo, hi = rate["ci"]
    return "keep" if lo >= bar else "return" if hi < bar else "undecided"


def run(*, store=None, summary=None, replay=None, manifest=None, strata=None, lanes=LANES, gate: float = DECIDE_GATE,
        candidate: str = rp.ADOPTED, bar: float | None = None) -> dict:
    from harness import live_audit
    from harness import memory_store as ms
    records = summarise(Path(replay)) if replay else (
        load_summary(Path(summary or SUMMARY)) if Path(summary or SUMMARY).exists() else [])
    man = rp._jsonl(Path(manifest or MANIFEST))
    strata_path = Path(strata or STRATA)
    st = json.loads(strata_path.read_text(encoding="utf-8")).get("strata", {}) if strata_path.exists() else {}
    path = Path(store) if store else ms.db_path()
    if not path.exists():
        raise Refused(f"no store at {path.name}")
    conn = live_audit.open_readonly(path)
    try:
        rows = replay_rows(records, man, st, candidate) + lane_rows(conn, lanes, gate)
    finally:
        conn.close()
    for r in rows:
        r["verdict"] = verdict(r["local"], bar)
    meta = next((r for r in records if r["kind"] == "meta"), {})
    return {"rows": rows, "bar": bar, "gate": gate,
            "sources": {"replay": {"candidate": candidate, "units": sum(r["kind"] == "unit" for r in records),
                                   "now": meta.get("now"), "agreement": agreement(records, candidate)},
                        "store": "mode=ro"}}


def _pct(r: dict | None) -> str:
    if r is None:
        return "-"
    if not r["n"]:
        return "0/0"
    return f"{r['k']}/{r['n']} {100 * r['rate']:.0f}% [{100 * r['ci'][0]:.0f}, {100 * r['ci'][1]:.0f}]"


def _tok(t: dict | None) -> str:
    def h(x):
        return f"{x / 1e6:.1f}M" if x >= 1e6 else f"{x / 1e3:.1f}k" if x >= 1e3 else str(x)
    return "-" if t is None else f"{h(t['in'])}/{h(t['out'])}"


def _hybrid(r: dict) -> str:
    if r["hybrid"] is not None:
        return _pct(r["hybrid"])
    if r.get("hybrid_bounds"):
        lo, hi = r["hybrid_bounds"]
        return f"between {lo} and {hi} of {r['n']}"
    return "-"


COLUMNS = ("workload", "share", "n", "local usable [95%]", "claude [95%]", "hybrid [95%]", "gate", "to claude",
           "acc.wrong", "GPU min", "claude tok in/out", "hybrid tok in/out", "bar", "note")


def text(rep: dict) -> str:
    table = [COLUMNS]
    for r in rep["rows"]:
        claude = _pct(r["claude"]) if r["claude"] is not None else "no stored run"
        table.append((r["workload"], "-" if r["share"] is None else f"{100 * r['share']:.1f}%",
                      f"{r['n']} {r['unit']}" if r["unit"] != "units" else str(r["n"]), _pct(r["local"]), claude,
                      _hybrid(r), r["gate"], "-" if r["to_claude"] is None else str(r["to_claude"]),
                      "-" if r["accepted_wrong"] is None else str(r["accepted_wrong"]), f"{r['local_gpu_min']:.1f}",
                      _tok(r["claude_tokens"]), _tok(r["hybrid_tokens"]), r.get("verdict") or "", r["note"]))
    widths = [max(len(row[i]) for row in table) for i in range(len(COLUMNS))]
    out = ["  ".join(c.ljust(w) for c, w in zip(row, widths)).rstrip() for row in table]
    src = rep.get("sources", {})
    rp_ = src.get("replay") or {}
    a = rp_.get("agreement")
    bar = rep.get("bar")
    out += ["",
            "usable: replay rows count usable as is or with edits (blind judge, #1161); lane rows count resolved or "
            "passed cases, decide counts fields.",
            "claude on replay rows: the session's own Claude record as the same blind judge graded it; its tokens "
            "are the session's, from the #1151 manifest (output estimated, input includes cache reads).",
            "hybrid: review = the local answer kept when graded usable, else Claude; visible = the #891 "
            "applicability gate; a gate with no stored Claude arm prints bounds. GPU min = local request seconds "
            "summed.",
            f"bar: {'not set; Eric sets it (soh baseline --bar RATE)' if bar is None else f'{bar:g}, applied to the local interval'}"]
    if a:
        out.append(f"replay grading agreement, first two replays: {_pct(a)} (needs {100 * a['needs']:.0f}%: "
                   f"{'PASS' if a['rate'] is not None and a['rate'] >= a['needs'] else 'FAIL'})")
    lanes = [f"{r['workload']} local run {r['runs']['local']}" + (f", claude run {r['runs']['claude']}"
                                                                  if r["runs"].get("claude") else "")
             for r in rep["rows"] if r["runs"].get("local")]
    if lanes:
        out.append("runs: " + "; ".join(lanes))
    return "\n".join(out)
