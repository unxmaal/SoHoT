"""Re-decide terminal verdicts whose reason contradicts their outcome or that nothing can reopen. #991."""
from __future__ import annotations

HELD = ("SELECT v.id, p.id AS pid, p.name, p.lane, p.state, v.tier, v.reason, v.until, v.detail, v.decided_at, "
        "v.run_path, v.run_id, v.candidate_id, v.failure_class, v.power, v.split_version, p.next_retest_at "
        "FROM proposals p "
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


BROKEN_SCREENS = ("SELECT v.id, p.name, p.hf_task, p.library, p.card_tags, p.model_type, p.remote_code, v.detail, "
                  "v.run_path, v.run_id, v.candidate_id, coalesce(c.spec, p.name) AS spec FROM proposals p "
                  "JOIN verdicts v ON v.id = p.state_verdict_id LEFT JOIN candidates c ON c.id = v.candidate_id "
                  "WHERE p.state = 'broken' AND v.tier = 'screen' AND v.reason = 'candidate' ORDER BY v.id")


def misclassed(conn) -> list[dict]:
    """Broken screens whose own detail today's classifier reads as a fault outside the candidate. #1008."""
    from harness import reasons
    out = []
    for r in conn.execute(BROKEN_SCREENS).fetchall():
        cls = reasons.classify(r["detail"] or "", reasons.RUNNER, r["spec"])
        if reasons.CLASSES.get(cls, ("", reasons.CANDIDATE))[1] != reasons.CANDIDATE:
            out.append({**dict(r), "class": cls})
    return out


def _reclassed(r: dict) -> dict:
    """A misclassed broken screen re-decided from its detail as screen.decide_class decides that class now."""
    from harness import screen
    why = (r["detail"] or "").removeprefix("it ran and passed nothing: ")
    v = screen.decide_class(r["class"], why, r["spec"], card=r)
    base = {"verdict_id": r["id"], "name": r["name"], "why": f"its detail classes as {r['class']}",
            "was": ["broken", "screen", "candidate", ""]}
    if v.outcome == "queued":
        return {**base, "now": ["queued", "screen", v.reason, ""],
                "detail": f"re-decided (#1008): {v.detail}"[:600]}
    return {**base, "now": [v.outcome, "screen", v.reason, v.until], "run_path": r["run_path"],
            "run_id": r["run_id"], "candidate_id": r["candidate_id"], "failure_class": v.failure_class,
            "detail": f"re-decided (#1008): {v.detail}"[:600]}


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
    from harness.memory_store.transitions import CONDITIONAL, RETEST_TIERS
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
        elif r["state"] == "declined" and r["tier"] in RETEST_TIERS and r["reason"] in CONDITIONAL and not until:
            found.append(_unreopenable(conn, r, base))
        else:
            found.append({**base, "skipped": "no repair names this kind; a person decides it"})
    return found + [_reclassed(r) for r in misclassed(conn)]


def _unreopenable(conn, r, base: dict) -> dict:
    """A retest-tier decline nothing reopens: schedule the retest it still has, or at adopt wait on the lane. #1001."""
    import json

    from harness import adopt, reasons
    from harness.memory_store.schema import ADOPT
    from harness.memory_store.transitions import RETEST_AFTER_SECONDS, retest_spent
    if not retest_spent(conn, r["pid"], r["tier"]):
        return {**base, "now": [r["state"], r["tier"], r["reason"], ""], "pid": r["pid"],
                "retest_at": float(r["decided_at"]) + RETEST_AFTER_SECONDS}
    lane = r["lane"] or (r["detail"] or "").partition(":")[0].strip()
    if r["tier"] != ADOPT or r["reason"] != reasons.LIMIT or not lane:
        return {**base, "skipped": "no repair names this kind; a person decides it"}
    try:
        plan = json.loads(r["power"] or "{}")
    except ValueError:
        plan = {}
    until = adopt.cases_until(lane, adopt.lane_cases(lane),
                              adopt.more_cases(plan.get("cases") or 0, plan.get("cases_needed")))
    return {**base, "now": ["declined", ADOPT, r["reason"], until], "run_path": r["run_path"],
            "run_id": r["run_id"], "candidate_id": r["candidate_id"], "failure_class": r["failure_class"] or "",
            "evidence": {"power": r["power"], "split_version": r["split_version"]},
            "detail": f"re-decided (#1001): {r['why']}; no retest is left, so it waits on the {lane} "
                      f"lane growing; {r['detail']}"[:600]}


def apply(conn, found: list[dict]) -> list[int]:
    """Write each change through the one state writer."""
    from harness import memory_store as ms
    ids = []
    from harness.memory_store.transitions import _schedule_retest
    for c in found:
        if "now" not in c:
            continue
        outcome, tier, reason, until = c["now"]
        if "retest_at" in c:
            _schedule_retest(conn, c["pid"], {"outcome": outcome, "tier": tier, "until": until,
                                              "decided_at": c["retest_at"] - ms.RETEST_AFTER_SECONDS}, "")
            continue
        if outcome == "queued":
            ids.append(ms.retract(conn, c["name"], c["detail"], tier=tier))
            continue
        vid = ms.decide(conn, c["name"], outcome, tier=tier, reason=reason, until=until,
                        detail=c["detail"], run_path=c["run_path"] or "", run_id=c["run_id"],
                        candidate_id=c["candidate_id"], failure_class=c.get("failure_class", ""))
        if c.get("evidence"):
            conn.execute("UPDATE verdicts SET power = ?, split_version = ? WHERE id = ?",
                         (c["evidence"]["power"], c["evidence"]["split_version"] or "", vid))
        ids.append(vid)
    conn.commit()
    return ids
