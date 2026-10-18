"""Re-decide terminal verdicts whose reason contradicts their outcome or that nothing can reopen. #991."""
from __future__ import annotations

HELD = ("SELECT v.id, p.name, p.lane, p.state, v.tier, v.reason, v.until, v.detail, v.decided_at, "
        "v.run_path, v.run_id, v.candidate_id, p.next_retest_at FROM proposals p "
        "JOIN verdicts v ON v.id = p.state_verdict_id "
        "WHERE p.state IN ('broken', 'declined', 'ignored') ORDER BY v.id")


def incoherent(conn) -> list[dict]:
    """State-holding verdicts transitions.incoherent names, each with why."""
    from harness.memory_store.transitions import incoherent as why_of
    out = []
    for r in conn.execute(HELD).fetchall():
        why = why_of(r["state"], r["reason"], r["until"], retest=r["next_retest_at"] is not None)
        if why:
            out.append({**dict(r), "why": why})
    return out


def scoped(until: str, lane: str) -> str:
    """`limit:name>N` as the lane-scoped `limit:name.<lane>>N` when that limit exists; #628 scoped them."""
    from harness import reasons
    head, sep, want = (until or "").partition(">")
    name = head.removeprefix("limit:")
    if not sep or head == name or "." in name or not lane:
        return until or ""
    return f"limit:{name}.{lane}>{want}" if f"{name}.{lane}" in reasons.limits() else until


def changes(conn) -> list[dict]:
    """What each incoherent verdict becomes: declined with an until, requeued for inspect, or skipped."""
    from harness import inspect as ins
    from harness import reasons
    from harness.memory_store.schema import INSPECT
    from harness.memory_store.transitions import CONDITIONAL
    found = []
    for r in incoherent(conn):
        base = {"verdict_id": r["id"], "name": r["name"], "why": r["why"],
                "was": [r["state"], r["tier"], r["reason"], r["until"]]}
        until = scoped(r["until"], r["lane"])
        if not until and r["reason"] == reasons.UPSTREAM:
            until = ins.gone_until(r["decided_at"])
        if r["state"] == "broken" and r["reason"] in CONDITIONAL and until:
            found.append({**base, "now": ["declined", r["tier"], r["reason"], until],
                          "run_path": r["run_path"], "run_id": r["run_id"], "candidate_id": r["candidate_id"],
                          "detail": f"re-decided (#991): {r['why']}; {r['detail']}"[:600]})
        elif r["reason"] == reasons.HARNESS or (r["state"] != "broken" and r["tier"] in (INSPECT, "fetch")):
            found.append({**base, "now": ["queued", INSPECT, reasons.REOPENED, ""],
                          "detail": f"{r['why']}: inspect asks again with today's code (#991)"})
        else:
            found.append({**base, "skipped": "no repair names this kind; a person decides it"})
    return found


def apply(conn, found: list[dict]) -> list[int]:
    """Write each change through the one state writer."""
    from harness import memory_store as ms
    ids = []
    for c in found:
        if "now" not in c:
            continue
        outcome, tier, reason, until = c["now"]
        if outcome == "queued":
            ids.append(ms.retract(conn, c["name"], c["detail"], tier=tier))
            continue
        ids.append(ms.decide(conn, c["name"], outcome, tier=tier, reason=reason, until=until,
                             detail=c["detail"], run_path=c["run_path"] or "", run_id=c["run_id"],
                             candidate_id=c["candidate_id"]))
    conn.commit()
    return ids
