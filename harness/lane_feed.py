"""One lane's discovery findings as a versioned document, with a cursor over its events. #1200."""
from __future__ import annotations

import json
import time

from harness import memory_store as ms

#: Bumped whenever the document's shape changes; tests/test_lane_feed.py pins the shape per version.
SCHEMA_VERSION = 1
#: Verdicts from the screen tier on are findings; inspect, judge and fetch come before a candidate exists.
FINDING_TIERS = tuple(t for t in ms.TIERS if ms.LADDER[t] >= ms.LADDER[ms.SCREEN])
STATUSES = ("adopted", "rejected", "measured", "screened", "pending")
#: Every funnel stage -> the status a consumer reads; a stage funnel adds must be placed here.
STATUS = {"seen": "pending", "inspected": "pending", "ranked": "pending", "fetched": "pending",
          "screened": "screened", "measured": "measured", "adopted": "adopted", "declined": "rejected"}
#: Order of events that share a timestamp.
KINDS = ("screen", "verdict", "adoption", "knob")


class UnknownLane(ValueError):
    pass


def _now() -> float:
    return time.time()


def event_id(at: float) -> int:
    """Microseconds since the epoch of the row's own time: derived, never stored, and rising as rows are written."""
    return int(round(float(at or 0) * 1_000_000))


def _event(kind: str, at, **kw) -> dict:
    from harness.publish import _iso
    base = {"id": 0, "at": _iso(at), "kind": kind, "candidate": "", "outcome": "", "tier": "",
            "reason": "", "detail": "", "run_id": None, "knob": "", "chosen": None, "how": "",
            "incumbent": ""}
    return {**base, **kw, "_t": float(at or 0)}


def status_of(state: str, tier: str) -> str:
    from harness.funnel import stage_of
    return STATUS[stage_of(state or "", tier or "", downloaded=False, ranked=False)]


def _json(text):
    try:
        return json.loads(text) if text not in (None, "") else None
    except (TypeError, ValueError):
        return text


def _case_set(lane: str) -> dict:
    """How many cases, their digest, and each numeric param's values (for video: width, height, frames)."""
    from evals import core
    from harness import baseline
    cases = baseline.exam_cases(lane) or []
    params: dict[str, set] = {}
    for c in cases:
        for k, v in dict(c.params).items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                params.setdefault(str(k), set()).add(v)
    return {"cases": len(cases), "cases_digest": core.cases_digest(cases) if cases else "",
            "params": {k: sorted(v) for k, v in sorted(params.items())}}


def _machine(conn, mid, here: bool) -> dict:
    from harness import publish
    if mid is None:
        return {"label": "", "slug": ""}
    label = publish.identity(conn, mid, here)[2]
    return {"label": label, "slug": publish.slug(label)}


def _served(conn, mid, lane: str, held: dict, now: float) -> tuple[dict, list[dict]]:
    from harness import publish, winners
    typed = winners.typed()
    if mid is None:
        row = {"serves": held.get("spec") or typed.get(lane, ""), "adopted": bool(held),
               "adopted_how": held.get("how", ""), "pass_rate": None, "median_s": None,
               "metrics": {}, "measured_at": "", "not_run": "", "exams": []}
        row["serves_model"] = publish._serves_model(row["serves"], conn)
        from harness import lanes as L
        row["parked"], row["parked_until"] = L.parked(lane)
        row["stale"] = False
    else:
        row = publish._lane(conn, mid, lane, held, typed, now)
    incumbent = ""
    if held.get("incumbent_id"):
        got = conn.execute("SELECT spec FROM candidates WHERE id = ?", (held["incumbent_id"],)).fetchone()
        incumbent = got["spec"] if got else ""
    served = {k: row.get(k) for k in ("serves", "serves_model", "adopted", "adopted_how", "not_run",
                                       "pass_rate", "median_s", "metrics", "measured_at", "parked",
                                       "parked_until", "stale")}
    served["adopted_at"] = publish._iso(held.get("adopted_at")) if held else ""
    served["incumbent"] = incumbent
    return served, row.get("exams") or []


def _lane_candidates(conn, lane: str, exam_keys: set[str], held: dict) -> list[dict]:
    from harness import lanes as L
    rows = conn.execute(
        "SELECT c.id, c.spec, c.receipt_key, c.lane AS clane, c.proposal_id, p.name, p.lane AS plane, "
        "p.state, v.tier, v.outcome, v.reason, v.detail, v.until, v.run_id, v.decided_at "
        "FROM candidates c LEFT JOIN proposals p ON p.id = c.proposal_id "
        "LEFT JOIN verdicts v ON v.id = p.state_verdict_id ORDER BY c.id").fetchall()
    out = []
    for r in rows:
        r = dict(r)
        mine = L.canonical(r["clane"] or r["plane"] or "") == lane
        if not (mine or r["receipt_key"] in exam_keys or r["spec"] in exam_keys
                or r["id"] == held.get("candidate_id")):
            continue
        if r["proposal_id"] is None:
            v = conn.execute("SELECT outcome, tier, reason, detail, until, run_id, decided_at FROM verdicts "
                             "WHERE candidate_id = ? ORDER BY decided_at DESC, id DESC LIMIT 1",
                             (r["id"],)).fetchone()
            r.update(dict(v) if v else {})
            r["state"] = r.get("outcome") or ""
        out.append(r)
    return out


def _candidates(conn, lane: str, exams: list[dict], held: dict) -> tuple[list[dict], list[int], list[int]]:
    from harness.publish import _iso
    latest: dict[str, dict] = {}
    for exam in exams:
        for row in exam["rows"]:
            latest.setdefault(row["candidate"], {**row, "cases": exam["cases"], "repeat": exam["repeat"]})
    found = _lane_candidates(conn, lane, set(latest), held)
    out = []
    for r in found:
        out.append({
            "candidate": r["spec"], "receipt_key": r["receipt_key"], "proposal": r.get("name") or "",
            "status": status_of(r.get("state") or "", r.get("tier") or ""),
            "outcome": r.get("outcome") or "", "tier": r.get("tier") or "",
            "reason": r.get("reason") or "", "detail": r.get("detail") or "", "until": r.get("until") or "",
            "run_id": r.get("run_id"), "decided_at": _iso(r.get("decided_at")),
            "serves": r["id"] == held.get("candidate_id"),
            "exam": latest.get(r["receipt_key"]) or latest.get(r["spec"])})
    out.sort(key=lambda c: (STATUSES.index(c["status"]), c["candidate"]))
    return out, [r["id"] for r in found], [r["proposal_id"] for r in found if r["proposal_id"] is not None]


def _knobs(conn, mid, lane: str) -> list[dict]:
    from harness import lanes as L
    from harness.publish import _iso
    rows = conn.execute(
        "SELECT * FROM knob_sweeps WHERE settled_at IS NOT NULL AND (machine_id IS NULL OR machine_id = ?) "
        "ORDER BY settled_at, id", (mid,)).fetchall()
    return [{"id": r["id"], "knob": r["knob"], "candidate": r["spec"], "outcome": r["outcome"],
             "chosen": _json(r["chosen"]), "detail": r["detail"], "queued_at": _iso(r["queued_at"]),
             "settled_at": _iso(r["settled_at"]), "_t": r["settled_at"]}
            for r in rows if L.canonical(r["lane"]) == lane]


def _adoptions(conn, mid, lane: str) -> list[dict]:
    from harness import lanes as L
    rows = conn.execute(
        "SELECT a.id, a.lane, a.adopted_at, a.how, a.verdict_id, a.run_id, c.spec, i.spec AS incumbent, "
        "v.reason, v.detail, v.outcome, v.tier FROM adoptions a JOIN candidates c ON c.id = a.candidate_id "
        "LEFT JOIN candidates i ON i.id = a.incumbent_id LEFT JOIN verdicts v ON v.id = a.verdict_id "
        "WHERE a.machine_id = ? OR a.all_machines = 1 OR a.machine_id IS NULL ORDER BY a.adopted_at, a.id",
        (mid,)).fetchall()
    return [dict(r) for r in rows if L.canonical(r["lane"]) == lane]


def _events(conn, lane: str, cids: list[int], pids: list[int], adoptions: list[dict],
            knobs: list[dict]) -> list[dict]:
    events = []
    folded = {a["verdict_id"] for a in adoptions if a["verdict_id"] is not None}
    for a in adoptions:
        events.append((KINDS.index("adoption"), a["id"], _event(
            "adoption", a["adopted_at"], candidate=a["spec"], outcome=a["outcome"] or "", tier=a["tier"] or "",
            reason=a["reason"] or "", detail=a["detail"] or "", run_id=a["run_id"], how=a["how"],
            incumbent=a["incumbent"] or "")))
    for k in knobs:
        events.append((KINDS.index("knob"), k["id"], _event(
            "knob", k["_t"], candidate=k["candidate"], outcome=k["outcome"], detail=k["detail"],
            knob=k["knob"], chosen=k["chosen"])))
    if cids or pids:
        tiers = ",".join("?" * len(FINDING_TIERS))
        cm, pm = ",".join("?" * len(cids)) or "NULL", ",".join("?" * len(pids)) or "NULL"
        rows = conn.execute(
            "SELECT v.id, v.outcome, v.tier, v.reason, v.detail, v.run_id, v.decided_at, "
            "COALESCE(c.spec, p.name, '') AS name FROM verdicts v "
            "LEFT JOIN candidates c ON c.id = v.candidate_id LEFT JOIN proposals p ON p.id = v.proposal_id "
            f"WHERE v.tier IN ({tiers}) AND (v.candidate_id IN ({cm}) OR v.proposal_id IN ({pm})) "
            "ORDER BY v.id", (*FINDING_TIERS, *cids, *pids)).fetchall()
        for v in rows:
            if v["id"] in folded:
                continue
            kind = "screen" if v["tier"] == "screen" else "verdict"
            events.append((KINDS.index(kind), v["id"], _event(
                kind, v["decided_at"], candidate=v["name"], outcome=v["outcome"], tier=v["tier"],
                reason=v["reason"] or "", detail=v["detail"] or "", run_id=v["run_id"])))
    events.sort(key=lambda e: (e[2]["_t"], e[0], e[1]))
    last = 0
    out = []
    for _, _, e in events:
        last = max(event_id(e.pop("_t")), last + 1)
        out.append({**e, "id": last})
    return out


def lane_feed(conn, lane: str, since: int | None = None, machine_id: int | None = None,
              now: float | None = None) -> dict:
    """The lane's served model, candidates, exams, settled knobs and events after `since`, scrubbed. Reads only."""
    from harness import adopt, lanes as L, publish
    name = L.canonical(lane)
    if not L.known(name):
        raise UnknownLane(f"no lane named {lane!r}; lanes are {', '.join(L.ALL)}")
    now = _now() if now is None else now
    with ms.lend(conn):
        mid = machine_id if machine_id is not None else ms.machine_row(conn)
        held = adopt.current(conn, mid if mid is not None else ()).get(name) or {}
        served, exams = _served(conn, mid, name, held, now)
        candidates, cids, pids = _candidates(conn, name, exams, held)
        knobs = _knobs(conn, mid, name)
        events = _events(conn, name, cids, pids, _adoptions(conn, mid, name), knobs)
        doc = {
            "schema_version": SCHEMA_VERSION,
            "generated_at": publish._iso(now),
            "lane": {"name": name, "wanted": name in L.WANTED, **_case_set(name)},
            "machine": _machine(conn, mid, machine_id is None),
            "served": served,
            "candidates": candidates,
            "exams": exams,
            "knobs": [{k: v for k, v in r.items() if k != "_t"} for r in knobs],
            "since": int(since or 0),
            "cursor": max([int(since or 0)] + [e["id"] for e in events]),
            "events": [e for e in events if since is None or e["id"] > since],
        }
    return publish.scrub(doc)


def open_store(store: str = ""):
    """The store read-only: a named file, else this home's discovery.db, else the Postgres store."""
    from pathlib import Path

    from harness import ledger, store as backend
    from harness import memory_store as ms
    if store:
        if not Path(store).is_file():
            raise FileNotFoundError(f"no store at {store}")
        return ledger.open_ro(Path(store))
    if backend.backend() == backend.POSTGRES:
        return ms.connect()
    if not ms.db_path().is_file():
        raise FileNotFoundError(f"no store at {ms.db_path()}")
    return ledger.open_ro(ms.db_path())


def read(lane: str, since: int | None = None, store: str = "") -> dict:
    conn = open_store(store)
    try:
        return lane_feed(conn, lane, since)
    finally:
        conn.close()
