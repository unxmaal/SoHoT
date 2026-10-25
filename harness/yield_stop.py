"""Stop a task once continuing is worth less than starting the next one: a lane-model's stop point in generated tokens (#1127)."""
from __future__ import annotations

import hashlib
import json

from harness import convertible, knobs, reasons

#: Stop once the tasks still running at a point pass at less than this share of the lane-model's base pass rate. #1127.
STOP_RATIO = 0.25
#: The share of a run's tasks, drawn by case id and run, let past the stop point to the budget, so the curve still sees past it. #1127.
EXPLORE_SHARE = 0.1
#: The limit a stopped row records, as yield_stop>N tokens.
LIMIT = "yield_stop"


def explored(case_id: str, seed: str, share: float | None = None) -> bool:
    """Whether this case runs past the stop point in the run `seed` names; the same answer every time it is asked."""
    share = EXPLORE_SHARE if share is None else float(share)
    draw = int(hashlib.sha256(f"{seed}\0{case_id}".encode("utf-8")).hexdigest()[:8], 16) / 2 ** 32
    return draw < share


def _field(row, name):
    try:
        return row[name]
    except (KeyError, IndexError):
        return None


def _json(value, empty):
    if isinstance(value, str):
        try:
            return json.loads(value or "null") or empty
        except ValueError:
            return empty
    return value or empty


def tokens_of(row) -> int | None:
    """Tokens a stored reply generated: its usage, else the budget or stop point it was cut at, else its last attempt's."""
    got = _json(_field(row, "metrics"), {}).get("completion_tokens")
    if got:
        return int(got)
    limit = _field(row, "hit_limit") or _field(row, "limit") or ""
    if _field(row, "failure_class") in reasons.CUT and ">" in limit:
        name, _, n = limit.rpartition(">")
        if n.isdigit() and (name.startswith("max_tokens") or name == LIMIT):
            return int(n)
    tries = _json(_field(row, "attempts"), [])
    last = tries[-1].get("tokens") if tries else None
    return int(last) if last else None


def stopped_at(row) -> int | None:
    """The stop point a row stopped at, from its yield_stop>N limit; None for a row the stop did not cut."""
    limit = _field(row, "hit_limit") or _field(row, "limit") or ""
    if _field(row, "failure_class") == reasons.STOPPED_LOW_YIELD and limit.startswith(LIMIT + ">"):
        n = limit.rpartition(">")[2]
        return int(n) if n.isdigit() else None
    return None


def _weights(rows) -> list[float]:
    """Per row: a stopped row 0, as its outcome past the stop is unknown; an explored one stands for the stopped rows of its run."""
    out = [1.0] * len(rows)
    by: dict = {}
    for i, r in enumerate(rows):
        by.setdefault(_field(r, "run_id"), []).append(i)
    for idx in by.values():
        stops = [n for n in (stopped_at(rows[i]) for i in idx) if n is not None]
        if not stops:
            continue
        at = max(stops)
        cut = [i for i in idx if stopped_at(rows[i]) is not None]
        past = [i for i in idx if i not in cut and (tokens_of(rows[i]) or 0) > at]
        for i in cut:
            out[i] = 0.0
        for i in past:
            out[i] = (len(cut) + len(past)) / len(past)
    return out


def points(rows, budget: int | None = None) -> tuple[list[tuple[int, bool, float]], int]:
    """(tokens, passed, weight) per row under a reply budget, a pass past it a cut; and how many rows said no token count."""
    rows = list(rows)
    out, unknown = [], 0
    for r, w in zip(rows, _weights(rows)):
        n = tokens_of(r)
        if n is None:
            unknown += 1
            continue
        if not w:
            continue
        passed = bool(_field(r, "passed"))
        if budget and n > budget:
            n, passed = budget, False
        out.append((n, passed, w))
    return out, unknown


def stop_point(pts, ratio: float | None = None) -> dict:
    """The fewest generated tokens past which the tasks still running pass below ratio x the base pass rate; None when never."""
    ratio = STOP_RATIO if ratio is None else float(ratio)
    pts = sorted((p[0], bool(p[1]), p[2] if len(p) > 2 else 1.0) for p in pts)
    n, won = sum(w for *_, w in pts), sum(w for _, p, w in pts if p)
    base = won / n if n else 0.0
    got = {"tokens": None, "base": round(base, 4), "rows": len(pts), "passes": round(won, 2), "ratio": ratio}
    if not won:
        return got
    left, i, at = n, 0, 0
    while i < len(pts):
        if won < ratio * base * left - 1e-9:
            return {**got, "tokens": at, "running": round(left, 2), "running_passed": round(won, 2),
                    "rate": round(won / left, 4)}
        at = pts[i][0]
        while i < len(pts) and pts[i][0] == at:
            left, won, i = left - pts[i][2], won - pts[i][2] * pts[i][1], i + 1
    return got


def rescore(rows, tokens: int | None) -> dict:
    """Each row as the stop at `tokens` would have graded it, without re-running; with passes kept and lost and seconds saved."""
    out, kept, lost, stopped, saved, total = [], 0, 0, 0, 0.0, 0.0
    for r in rows:
        row = dict(r)
        n, secs = tokens_of(r), float(_field(r, "seconds") or 0.0)
        total += secs
        if tokens is not None and n is not None and n > tokens:
            stopped += 1
            lost += bool(row.get("passed"))
            saved += secs * (1 - tokens / n)
            row.update(passed=False, failure_class=reasons.STOPPED_LOW_YIELD)
            row["hit_limit" if "hit_limit" in row else "limit"] = knobs.limit(LIMIT, tokens, "tokens")
        else:
            kept += bool(row.get("passed"))
        out.append(row)
    return {"rows": out, "kept": kept, "lost": lost, "stopped": stopped,
            "seconds": round(total, 1), "saved_s": round(saved, 1), "saved_share": round(saved / total, 4) if total else 0.0}


def stored(conn, lane: str, budget: int | None = None) -> dict[str, list[dict]]:
    """Every unflagged measured row in `lane` by base model, from runs that gave a reply at least `budget` tokens."""
    from harness import completion, reverify, runs
    budget = completion.budget(lane) if budget is None else budget
    flagged = reverify._flagged_runs(conn)
    sql = ("SELECT runs.id AS run_id, runs.receipt, COALESCE(c.spec, res.candidate) AS spec, res.case_id, "
           "res.passed, res.seconds, res.failure_class, res.hit_limit, res.metrics, res.attempts "
           "FROM results res JOIN runs ON res.run_id = runs.id LEFT JOIN candidates c ON c.id = res.candidate_id "
           "WHERE runs.lane = ? AND runs.tier = ?")
    by_run: dict = {}
    for r in conn.execute(sql, (lane, runs.MEASURE)):
        if r["run_id"] not in flagged:
            by_run.setdefault(r["run_id"], []).append(dict(r))
    out: dict = {}
    for rows in by_run.values():
        top = convertible._top(json.loads(rows[0]["receipt"] or "{}"), rows)
        # A run that gave less room cut replies the lane's budget would have let finish.
        if top is None or top < budget:
            continue
        for r in rows:
            out.setdefault(convertible.base_of(r["spec"]), []).append(r)
    return out


def point(conn, lane: str, spec: str, ratio: float | None = None, budget: int | None = None, found=None) -> dict:
    """The stop point a run of `spec` in `lane` uses: its model's curve, else the lane's pooled one. #1127."""
    from harness import completion
    budget = completion.budget(lane) if budget is None else budget
    found = stored(conn, lane, budget) if found is None else found
    base = convertible.base_of(spec)
    mine = found.get(base) or []
    rows, source = (mine, "model") if mine else ([r for rs in found.values() for r in rs], "lane")
    pts, unknown = points(rows, budget)
    got = stop_point(pts, ratio)
    return {**got, "lane": lane, "model": base, "from": source, "budget": budget, "unknown": unknown,
            "runs": sorted({r["run_id"] for r in rows})}


def said(p: dict) -> str:
    """One line on a stop point and where it came from."""
    where = f"{'its own' if p['from'] == 'model' else 'the lane pooled'} {p['rows']} rows, {p['passes']:g} passed"
    if p["tokens"] is None:
        return f"no stop below the {p['budget']}-token budget ({where})"
    return (f"stops at {p['tokens']} tokens: {p['running_passed']:g} of {p['running']:g} still running pass, "
            f"under {p['ratio']:g} x the base {p['base']:.3f} ({where})")


def report(conn, served: dict | None = None) -> list[dict]:
    """Each served text lane-model's stop point and the share of its stored GPU time the stop would have saved. #1127."""
    from harness import completion, reverify
    served = reverify.served(conn) if served is None else served
    out = []
    for lane, item in sorted(served.items()):
        spec = item.get("spec") or ""
        if not completion.budget(lane) or lane == "decide" or not spec:
            continue
        found = stored(conn, lane)
        p = point(conn, lane, spec, found=found)
        got = rescore(found.get(p["model"]) or [], p["tokens"])
        out.append({**p, "kept": got["kept"], "lost": got["lost"], "saved_share": got["saved_share"],
                    "saved_s": got["saved_s"], "seconds": got["seconds"]})
    return out


def line(r: dict) -> str:
    """One report line: the stop point and what it saves on the model's own stored rows."""
    return (f"{r['lane']:<9} {r['model'][:40]}: {said(r)}; saves {r['saved_share']:.0%} of its "
            f"{r['seconds'] / 3600:.1f} stored GPU-h, {r['kept']} passes kept, {r['lost']} lost")
