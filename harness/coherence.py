"""Re-decide terminal verdicts whose reason contradicts their outcome or that nothing can reopen. #991."""
from __future__ import annotations

from pathlib import Path

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
                  "v.run_path, v.run_id, v.candidate_id, coalesce(c.spec, p.name) AS spec, "
                  "coalesce(r.path, v.run_path, '') AS run_dir FROM proposals p "
                  "JOIN verdicts v ON v.id = p.state_verdict_id LEFT JOIN candidates c ON c.id = v.candidate_id "
                  "LEFT JOIN runs r ON r.id = v.run_id "
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


DRAFTER_ROWS = ("SELECT v.id, p.name, p.state, p.card_tags, v.tier, v.reason, v.until, v.detail, v.run_path, "
                "v.run_id, v.candidate_id FROM proposals p JOIN verdicts v ON v.id = p.state_verdict_id "
                "WHERE p.attaches_to = '' AND p.state IN ('queued', 'declined', 'broken') ORDER BY v.id")


def drafters(conn) -> list[dict]:
    """Proposals not yet held as attachments whose card or llama.cpp load log says drafter. #1039."""
    import json

    from harness import reasons, screen
    out = []
    for r in conn.execute(DRAFTER_ROWS).fetchall():
        try:
            tags = json.loads(r["card_tags"] or "[]")
        except ValueError:
            tags = []
        why = ("its load log says it needs a target model's context" if reasons.needs_target(r["detail"])
               else "its card names a speculative-decoding drafter" if screen.is_drafter(tags) else "")
        if why:
            out.append({"verdict_id": r["id"], "name": r["name"], "why": why,
                        "was": [r["state"], r["tier"], r["reason"], r["until"]],
                        "now": ["declined", "fetch", reasons.CANDIDATE, ""], "attach": screen.DRAFTER,
                        "run_path": r["run_path"], "run_id": r["run_id"], "candidate_id": r["candidate_id"],
                        "failure_class": reasons.ATTACHMENT,
                        "detail": f"re-decided (#1039): {screen.DRAFTER} in its own card or load log: this "
                                  f"attaches to a model rather than being one, and no lane can run it alone"})
    return out


def _reclassed(conn, r: dict, logs=None, root=None) -> dict:
    """A misclassed broken screen re-decided from its detail as screen.decide_class decides that class now."""
    from harness import load_log, reasons, screen
    why = (r["detail"] or "").removeprefix("it ran and passed nothing: ")
    v = screen.decide_class(r["class"], why, r["spec"], card=r)
    base = {"verdict_id": r["id"], "name": r["name"], "why": f"its detail classes as {r['class']}",
            "was": ["broken", "screen", "candidate", ""]}
    where = load_log._run_dir(r["run_dir"], root)
    ex = load_log.find(reasons.llamacpp_alias(r["detail"]), logs) if (
        r["class"] == reasons.LOAD_LOG_UNREAD and where) else None
    if ex is not None:
        # The router log says why llama-server could not load it; the cut is kept with the run. #1021.
        v = load_log.decided(r["detail"], ex, r["spec"], r["name"], conn,
                             f"{load_log.source(ex)}, cut after the verdict, not kept by the run")
        return {**base, "now": [v.outcome, "screen", v.reason, v.until], "run_path": str(where),
                "run_id": r["run_id"], "candidate_id": r["candidate_id"], "failure_class": v.failure_class,
                "excerpt": ex, "detail": f"re-decided from the router log (#1021): {v.detail}"[:600]}
    if v.outcome == "queued":
        return {**base, "now": ["queued", "screen", v.reason, ""],
                "detail": f"re-decided (#1008): {v.detail}"[:600]}
    return {**base, "now": [v.outcome, "screen", v.reason, v.until], "run_path": r["run_path"],
            "run_id": r["run_id"], "candidate_id": r["candidate_id"], "failure_class": v.failure_class,
            "detail": f"re-decided (#1008): {v.detail}"[:600]}


def scoped(until: str, lane: str) -> str:
    """`limit:name>N` as the lane-scoped `limit:name.<lane>>N` when that limit exists; #628 scoped them."""
    from harness import knobs, reasons
    head, sep, want = (until or "").partition(">")
    name = head.removeprefix("limit:")
    if not sep or head == name or "." in name or not lane:
        return until or ""
    if f"{name}.{lane}" not in reasons.limits():
        return until
    return f"limit:{knobs.limit(f'{name}.{lane}', knobs.number(want), knobs.limit_units().get(name, ''))}"


def changes(conn, logs=None, root=None) -> list[dict]:
    """What each incoherent verdict becomes: declined with an until, requeued for inspect, or skipped."""
    from harness import inspect as ins
    from harness import reasons
    from harness.memory_store.schema import INSPECT
    from harness.memory_store.transitions import CONDITIONAL, RETEST_TIERS
    found = lane_bound(conn) + past_growth(conn)
    bound = {c["verdict_id"] for c in found}
    for r in incoherent(conn):
        if r["id"] in bound:
            continue
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
    held = {c["verdict_id"] for c in found}
    # A drafter is an attachment whatever else its detail says, so it never reopens to fail again. #1047.
    attach = [c for c in drafters(conn) if c["verdict_id"] not in held]
    named = {c["verdict_id"] for c in attach}
    return found + [_reclassed(conn, r, logs, root) for r in misclassed(conn) if r["id"] not in named] + attach


def lane_bound(conn) -> list[dict]:
    """Adopt nulls and futility stops whose stored plan says the lane is too small: they wait on its cases. #1049, #1452."""
    import json

    from harness import adopt, reasons
    from harness.memory_store.schema import ADOPT
    out = []
    for r in conn.execute(HELD).fetchall():
        lane = r["lane"] or (r["detail"] or "").partition(":")[0].strip()
        futile = r["reason"] == reasons.CANDIDATE and not r["failure_class"] and _futility(r["detail"], lane)
        if (r["state"], r["tier"]) != ("declined", ADOPT) or r["until"] \
                or (r["reason"] != reasons.LIMIT and not futile) or r["failure_class"] == reasons.LANE_TOO_SMALL:
            continue
        try:
            plan = json.loads(r["power"] or "{}")
        except ValueError:
            plan = {}
        limit = adopt.lane_limit(lane, plan, r["name"]) if lane and plan else None
        if limit is None:
            continue
        more, why = limit
        until = adopt.cases_until(lane, adopt.decided_cases(lane, plan=plan), more)
        out.append({"verdict_id": r["id"], "name": r["name"], "why": why,
                    "was": [r["state"], r["tier"], r["reason"], r["until"]],
                    "now": ["declined", ADOPT, reasons.LIMIT, until], "run_path": r["run_path"],
                    "run_id": r["run_id"], "candidate_id": r["candidate_id"],
                    "failure_class": reasons.LANE_TOO_SMALL,
                    "evidence": {"power": r["power"], "split_version": r["split_version"]},
                    "detail": f"{lane}: re-decided ({'#1452' if futile else '#1049'}): {why}; {r['detail']}"[:600]})
    return out


def _futility(detail: str, lane: str) -> bool:
    return (detail or "").removeprefix(f"{lane}:").lstrip().startswith("futility:")


def past_growth(conn) -> list[dict]:
    """Adopt limits waiting on more lane cases than the lane can have had when they were decided. #1053."""
    import json
    import math

    from harness import adopt, holdout, reasons
    from harness.memory_store.schema import ADOPT
    out = []
    for r in conn.execute(HELD).fetchall():
        lane = r["lane"] or (r["detail"] or "").partition(":")[0].strip()
        head, _, n = (r["until"] or "").partition(">")
        if (r["state"], r["tier"], r["reason"]) != ("declined", ADOPT, reasons.LIMIT) \
                or head != f"cases:{lane}" or not n.isdigit():
            continue
        try:
            plan = json.loads(r["power"] or "{}")
        except ValueError:
            plan = {}
        held = int(plan.get("cases") or 0)
        if plan.get("side") == "all" and plan.get("cases_run"):
            most = int(plan["cases_run"])
        elif held:
            # Three standard deviations of the holdout draw above the cases a holdout this size comes from.
            most = math.ceil((held + 3 * math.sqrt(held)) / holdout.FRACTION)
        else:
            continue
        limit = adopt.lane_limit(lane, plan, r["name"])
        more = limit[0] if limit else adopt.more_cases(held, plan.get("cases_needed"))
        if int(n) <= most + more - 1:
            continue
        until = adopt.cases_until(lane, adopt.decided_cases(lane, plan=plan), more)
        out.append({"verdict_id": r["id"], "name": r["name"], "why": f"{r['until']} is past the {most} cases "
                    f"the {lane} lane can have had when it was decided",
                    "was": [r["state"], r["tier"], r["reason"], r["until"]],
                    "now": ["declined", ADOPT, reasons.LIMIT, until], "run_path": r["run_path"],
                    "run_id": r["run_id"], "candidate_id": r["candidate_id"],
                    "failure_class": r["failure_class"] or "",
                    "evidence": {"power": r["power"], "split_version": r["split_version"]},
                    "detail": f"{lane}: re-decided (#1053): {r['until']} counted the lane after it grew; "
                              f"{r['detail']}"[:600]})
    return out


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
    until = adopt.cases_until(lane, adopt.decided_cases(lane, plan=plan),
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
        if c.get("attach"):
            ms.set_attachment(conn, c["name"], c["attach"])
            if c["was"][0] != "queued":
                # The ladder refuses a fetch verdict over a screen one; the retraction is the way back. #1039.
                ids.append(ms.retract(conn, c["name"], f"a {c['attach']} loads only beside its target (#1039)"))
        if c.get("excerpt"):
            from harness import load_log
            load_log.write(Path(c["run_path"]), c["excerpt"])
        vid = ms.decide(conn, c["name"], outcome, tier=tier, reason=reason, until=until,
                        detail=c["detail"], run_path=c["run_path"] or "", run_id=c["run_id"],
                        candidate_id=c["candidate_id"], failure_class=c.get("failure_class", ""))
        if c.get("evidence"):
            conn.execute("UPDATE verdicts SET power = ?, split_version = ? WHERE id = ?",
                         (c["evidence"]["power"], c["evidence"]["split_version"] or "", vid))
        ids.append(vid)
    conn.commit()
    return ids
