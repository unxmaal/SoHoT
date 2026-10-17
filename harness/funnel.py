"""Where every proposal waits, since when, and why. #925."""
from __future__ import annotations

import math
import time

from harness import fetching, lanes as L
from harness.memory_store.schema import TERMINAL

STAGES = ("seen", "inspected", "ranked", "fetched", "screened", "measured", "adopted", "declined")
DAY = 86400.0
#: How many of each stage's longest waiters the summary names.
OLDEST = 5


def entered(history: list[dict], state: str) -> float | None:
    """When `state` began: its first row after the last terminal or reopen row, never the newest row."""
    start = 0
    for i, v in enumerate(history):
        if v["outcome"] in TERMINAL or v["reopen_kind"]:
            start = i
    return next((v["decided_at"] for v in history[start:] if v["outcome"] == state), None)


def stage_of(state: str, tier: str, *, downloaded: bool, ranked: bool) -> str:
    if not state:
        return "seen"
    if state == "measured":
        return "adopted" if tier == "adopt" else "measured"
    if state in TERMINAL:
        return "declined"
    if state == "screened":
        return "screened"
    if downloaded:
        return "fetched"
    return "ranked" if ranked else "inspected"


def _histories(conn) -> dict[int, list[dict]]:
    out: dict[int, list[dict]] = {}
    for v in conn.execute("SELECT proposal_id, id, outcome, tier, detail, decided_at, "
                          "COALESCE(reopen_kind, '') AS reopen_kind FROM verdicts "
                          "WHERE proposal_id IS NOT NULL ORDER BY proposal_id, id"):
        out.setdefault(v["proposal_id"], []).append(dict(v))
    return out


def _downloads(conn) -> dict[int, dict]:
    """Per proposal: how many download rows it has, and when a complete one still present finished."""
    out: dict[int, dict] = {}
    for d in conn.execute("SELECT proposal_id, COUNT(*) AS n, MAX(CASE WHEN complete = 1 AND removed_at IS NULL "
                          "THEN finished_at END) AS landed FROM downloads WHERE proposal_id IS NOT NULL "
                          "GROUP BY proposal_id"):
        out[d["proposal_id"]] = {"rows": d["n"], "landed": d["landed"]}
    return out


def _reason(row: dict, *, budget, backlog, top, position: int | None) -> tuple[str, str]:
    """Why a queued, undownloaded proposal waits: fetch's own why_not, else its place in fetch order."""
    got = fetching.why_not(row, budget=budget, backlog=backlog, top=top)
    if got:
        return got
    if position is not None and position < top:
        return "next", f"nothing holds it: {position + 1} of the rows a sweep tries, which downloads up to {top}"
    return "queue", f"{(position or 0) + 1} in fetch order, and a sweep downloads at most {top}"


def _unfetchable(p) -> tuple[str, str]:
    """Why fetch's queue does not hold a queued proposal at all."""
    from harness import memory_store as ms, methods
    if methods.is_method(p["name"]):
        return "method", "a method crossing downloads nothing; the screen takes it as it is"
    if p["registry"] == ms.GITHUB:
        return "repo", "a repo is installed and screened, never fetched"
    if p["tier"] not in fetching.FETCHABLE_TIERS:
        return "not fetchable", f"queued at {p['tier'] or 'no tier'}; only inspect or fetch queues a download"
    return "not fetchable", "fetch's queue does not hold it"


def _said(history: list[dict], since: float) -> str:
    """The fetch tier's newest answer since the state began, dated, or ''."""
    said = [v for v in history if v["tier"] == "fetch" and v["decided_at"] >= since]
    if not said:
        return ""
    return f"{said[-1]['detail']} ({time.strftime('%Y-%m-%d', time.localtime(said[-1]['decided_at']))})"


def proposals(conn, *, lane: str = "", since: float | None = None, now: float | None = None,
              budget: int | None = None, backlog: int = 0, top: int = 3) -> list[dict]:
    """One row per proposal: stage, entry into its state, age since first sighting, and why it waits."""
    from harness import downloads, rank, report
    now = time.time() if now is None else now
    budget = int(fetching.budget_gib() * fetching.GIB) if budget is None else budget
    histories, dls = _histories(conn), _downloads(conn)
    per_lane: dict[str, list[str]] = {}
    for r in report.ranked(conn):
        per_lane.setdefault(rank.lane_of(r), []).append(r["name"])
    lane_rank = {n: i for names in per_lane.values() for i, n in enumerate(names)}
    order = fetching.queued(conn)
    fetchable, position, tried = {r["name"]: r for r in order}, {}, 0
    for r in order:
        got = fetching.why_not(r, budget=budget, backlog=backlog, top=top)
        if not got or got[0] == fetching.FAILED:
            position[r["name"]], tried = tried, tried + 1
    out = []
    for p in conn.execute("SELECT p.id, p.name, p.resolved, p.lane, p.registry, p.state, p.first_seen, "
                          "p.state_verdict_id, "
                          "st.tier, st.detail, st.decided_at AS state_at FROM proposals p "
                          "LEFT JOIN verdicts st ON st.id = p.state_verdict_id ORDER BY p.id"):
        if lane and not L.serves(p["lane"], lane):
            continue
        if since is not None and (p["first_seen"] or 0) < since:
            continue
        history = [v for v in histories.get(p["id"], []) if v["id"] <= (p["state_verdict_id"] or 0)]
        state = p["state"] or ""
        dl = dls.get(p["id"], {})
        downloaded = bool(state == "queued" and downloads.have(p["resolved"] or p["name"], conn))
        stage = stage_of(state, p["tier"] or "", downloaded=downloaded, ranked=p["name"] in lane_rank)
        start = (entered(history, state) if state else None) or p["state_at"] or p["first_seen"]
        if stage == "fetched" and dl.get("landed"):
            start = max(start, dl["landed"])
        row = {"id": p["id"], "name": p["name"], "lane": L.canonical(p["lane"]), "state": state,
               "tier": p["tier"] or "", "stage": stage, "entered": start,
               "in_state_days": round((now - start) / DAY, 2), "first_seen": p["first_seen"],
               "age_days": round((now - (p["first_seen"] or now)) / DAY, 2),
               "lane_rank": lane_rank[p["name"]] + 1 if p["name"] in lane_rank else None,
               "downloaded": downloaded, "download_rows": dl.get("rows", 0),
               "fetch_verdicts": sum(v["tier"] == "fetch" for v in histories.get(p["id"], [])),
               "raw_lane": p["lane"] or "", "reason": "", "why": "", "fetch_said": _said(history, start)}
        if state == "queued" and not downloaded:
            got = fetchable.get(p["name"])
            row["reason"], row["why"] = _reason(got, budget=budget, backlog=backlog, top=top,
                                                position=position.get(p["name"])) if got else _unfetchable(p)
        out.append(row)
    return out


def _pct(xs: list[float], q: float) -> float | None:
    """Nearest-rank percentile of sorted `xs`."""
    return xs[max(0, math.ceil(len(xs) * q) - 1)] if xs else None


def _summary(rows: list[dict]) -> dict:
    days = sorted(r["in_state_days"] for r in rows)
    oldest = sorted(rows, key=lambda r: -r["in_state_days"])[:OLDEST]
    return {"count": len(rows), "median_days": _pct(days, 0.5), "p90_days": _pct(days, 0.9),
            "oldest_days": days[-1] if days else None,
            "oldest": [{"name": r["name"], "lane": r["lane"], "in_state_days": r["in_state_days"],
                        "reason": r["reason"]} for r in oldest]}


def stages(rows: list[dict]) -> list[dict]:
    """Per stage, in ladder order: count, median, p90 and oldest time in state, and the longest waiters."""
    return [{"stage": s, **_summary([r for r in rows if r["stage"] == s])} for s in STAGES]


def by_lane(rows: list[dict]) -> list[dict]:
    keys = sorted({(STAGES.index(r["stage"]), r["lane"]) for r in rows})
    return [{"stage": STAGES[i], "lane": lane,
             **_summary([r for r in rows if r["stage"] == STAGES[i] and r["lane"] == lane])}
            for i, lane in keys]


def untried(rows: list[dict]) -> int:
    """Queued proposals with a lane and no fetch verdict or download row of any kind."""
    return sum(r["state"] == "queued" and r["raw_lane"] != "" and not r["fetch_verdicts"]
               and not r["download_rows"] for r in rows)


def stalls(rows: list[dict], days: float, head: int) -> list[dict]:
    """The ranked head of each wanted lane with nothing downloaded, waiting in its state past `days`."""
    wanted = {L.canonical(w) for w in L.WANTED}
    return [r for r in rows if r["lane"] in wanted and r["lane_rank"] and r["lane_rank"] <= head
            and r["stage"] in ("ranked", "inspected") and r["in_state_days"] >= days]


def gather(conn, **kw) -> dict:
    rows = proposals(conn, **kw)
    return {"stages": stages(rows), "by_lane": by_lane(rows), "untried": untried(rows), "proposals": rows}
