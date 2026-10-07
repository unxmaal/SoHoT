"""Proposal state and the one writer that moves it (#409): decide, retract, _write."""
from __future__ import annotations

from pathlib import Path
import time

# Patched names are read through the package, so one patch reaches every caller. #484.
from harness import memory_store as ms

from harness.memory_store.machines import remember_machine
from harness.memory_store.schema import (ADOPT, INSPECT, LADDER, MEASURE, SCREEN,
    TERMINAL, VERDICTS, WAYPOINTS, _columns)


class IllegalTransition(ValueError):
    """A write the state machine refuses. A named reopen is the way back. #409."""


#: Named reopens: kind -> the states it may reopen, None meaning any. Only
#: these move a terminal state back to a waypoint, and each records why.
RETRACTION = "retraction"


RETEST = "retest"


REOPENS: dict = {RETRACTION: None, RETEST: ("broken", "declined")}


#: A screen or measure rejection is asked again this often, this many times. #431.
RETEST_AFTER_SECONDS = 7 * 86400


RETESTS = 3


#: Tiers whose rejection can be the harness's fault; the measure step records
#: its verdict at adopt. Inspect and fetch decide facts.
RETEST_TIERS = (SCREEN, MEASURE, ADOPT)


def retest_eligible(state: str, tier: str, until: str = "") -> bool:
    """A rejection a retest may reopen; one waiting on `until` reopens through it."""
    return (state in REOPENS[RETEST] and tier in RETEST_TIERS
            and not (until or "").strip())


def _schedule_retest(conn, pid: int, row: dict, reopen: str) -> None:
    """Keep retest_count and next_retest_at in step with the state just written."""
    if reopen == RETEST:
        conn.execute("UPDATE proposals SET retest_count = retest_count + 1, "
                     "next_retest_at = NULL WHERE id = ?", (pid,))
        return
    due = None
    if retest_eligible(row["outcome"], row.get("tier", ""), row.get("until", "")):
        spent = conn.execute("SELECT retest_count FROM proposals WHERE id = ?",
                             (pid,)).fetchone()[0]
        if spent < RETESTS:
            due = float(row["decided_at"]) + RETEST_AFTER_SECONDS
    conn.execute("UPDATE proposals SET next_retest_at = ? WHERE id = ?",
                 (due, pid))


def transition_refused(state: str, held_tier: str, outcome: str,
                       tier: str, reopen: str = "") -> str:
    """Why `tier` may not move `state` to `outcome`, or '' if it may. #409."""
    if reopen:
        if reopen not in REOPENS:
            return f"{reopen!r} is not a reopen; known: {', '.join(REOPENS)}"
        allowed = REOPENS[reopen]
        if allowed is not None and state not in allowed:
            return f"a {reopen} cannot reopen {state or 'nothing'}"
        return ""
    if not state or state == "queued":
        return ""
    if state in TERMINAL and outcome in WAYPOINTS:
        return (f"{outcome} at {tier or '-'} would reopen {state} at "
                f"{held_tier or '-'}; only a named reopen does that")
    if LADDER.get(tier, 0) < LADDER.get(held_tier, 0):
        return (f"{tier or '-'} comes before {held_tier} on the ladder, so its "
                f"{outcome} cannot replace {state}")
    return ""


def fold(events) -> tuple[str, str]:
    """(state, tier) after (outcome, tier, reopen) events, refused ones skipped."""
    state, held = "", ""
    for outcome, tier, reopen in events:
        if not transition_refused(state, held, outcome, tier, reopen):
            state, held = outcome, tier
    return state, held


def _held(conn, pid: int):
    return conn.execute(
        "SELECT p.state, p.state_verdict_id AS id, v.tier, v.outcome, v.detail, "
        "v.score, v.run_path, v.run_id FROM proposals p LEFT JOIN verdicts v "
        "ON v.id = p.state_verdict_id WHERE p.id = ?", (pid,)).fetchone()


def _write(conn, pid: int, name: str, row: dict, reopen: str = "",
           why: str = "") -> int:
    """Insert one verdict and move the proposal's state, or refuse. #409."""
    if reopen and not why.strip():
        raise IllegalTransition(f"{name}: a {reopen} must say why")
    for _ in range(8):
        held = _held(conn, pid)
        # A deterministic tier restating its state is not a second fact (#184);
        # compared with the state row, so a retraction is never undone (#225).
        if (held["id"] and not reopen and row.get("score") is None
                and not row.get("run_path") and not row.get("run_id")
                and held["tier"] == row["tier"]
                and held["outcome"] == row["outcome"]
                and held["detail"] == row["detail"] and held["score"] is None
                and not held["run_path"] and not held["run_id"]):
            return held["id"]
        why = transition_refused(held["state"], held["tier"] or "",
                                 row["outcome"], row["tier"], reopen)
        if why:
            raise IllegalTransition(f"{name}: {why}")
        cols = {**row, "proposal_id": pid}
        if reopen:
            cols.update(reopens=held["id"], reopen_kind=reopen)
        vid = conn.execute(
            f"INSERT INTO verdicts ({', '.join(cols)}) "
            f"VALUES ({', '.join('?' * len(cols))})",
            tuple(cols.values())).lastrowid
        moved = conn.execute(
            "UPDATE proposals SET state = ?, state_verdict_id = ? "
            "WHERE id = ? AND COALESCE(state_verdict_id, 0) = ?",
            (row["outcome"], vid, pid, held["id"] or 0)).rowcount
        if moved == 1:
            _schedule_retest(conn, pid, row, reopen)
            return vid
        # Another writer moved the state first; re-check against theirs.
        conn.execute("DELETE FROM verdicts WHERE id = ?", (vid,))
    raise RuntimeError(f"{name}: the state kept moving under this write")


def _migration_retraction(conn, pid: int, name: str, outcome: str, tier: str,
                          detail: str, until: str = "") -> int:
    """A migration's retraction, in whatever columns this schema has yet."""
    row = {"outcome": outcome, "tier": tier, "detail": detail,
           "decided_at": time.time()}
    if "machine_id" in _columns(conn, "verdicts"):
        row["machine_id"] = remember_machine(conn)
    if until:
        row["until"] = until
    if "reason" in _columns(conn, "verdicts"):
        row["reason"] = "reopened"
    return _write(conn, pid, name, row, reopen=RETRACTION, why=detail)


def retract(conn, name: str, why: str, *, outcome: str = "queued",
            tier: str = INSPECT, until: str = "") -> int:
    """Reopen or reclassify a decided name, saying why. #409."""
    detail = why if why.startswith("retracted:") else f"retracted: {why}"
    return ms.decide(conn, name, outcome, tier=tier, until=until, detail=detail,
                     reopen=RETRACTION, reopen_why=why)


def decide_or_skip(conn, name: str, outcome: str, **kw) -> int | None:
    """decide() for a tier loop: a refused move says so and returns None."""
    try:
        return ms.decide(conn, name, outcome, **kw)
    except IllegalTransition as exc:
        print(f"  skipped {exc}", flush=True)
        return None


def state_audit(conn) -> dict:
    """Proposals whose history the transition table would fold differently,
    and those once terminal and now open, for a person to decide. #409."""
    events: dict = {}
    once_terminal = set()
    for r in conn.execute(
            "SELECT proposal_id, outcome, tier, reopen_kind, detail "
            "FROM verdicts WHERE proposal_id IS NOT NULL ORDER BY id"):
        # Before #409 a retraction was only its prose.
        kind = r["reopen_kind"] or (
            RETRACTION if str(r["detail"] or "").startswith("retracted:") else "")
        events.setdefault(r["proposal_id"], []).append(
            (r["outcome"], r["tier"] or "", kind))
        if r["outcome"] in TERMINAL:
            once_terminal.add(r["proposal_id"])
    differs, reopened = [], []
    for p in conn.execute("SELECT id, name, state FROM proposals ORDER BY id"):
        folded, _ = fold(events.get(p["id"], []))
        if folded != p["state"]:
            differs.append({"name": p["name"], "state": p["state"],
                            "folded": folded})
        if p["id"] in once_terminal and p["state"] not in TERMINAL:
            reopened.append({"name": p["name"], "state": p["state"]})
    return {"folds_differently": differs, "terminal_then_open": reopened}


def decide(conn: sqlite3.Connection, name: str, outcome: str, *, tier: str = "",
           detail: str = "", run_path: str = "",
           score: float | None = None, rubric: str = "", judge: str = "",
           at: float | None = None, until: str = "",
           size_bytes: int = 0, upstream_idle_days: float = 0.0,
           candidate_id: int | None = None, reopen: str = "",
           reopen_why: str = "", reason: str = "",
           run_id: int | None = None) -> int:
    """Record what happened to a proposal, and move its state.

    The single write path for a verdict and for proposals.state. A move
    transition_refused() names raises IllegalTransition; a named `reopen`
    (a kind in REOPENS) with its `reason` is the only way back from a
    terminal state. #409.

    THE MACHINE IS RECORDED HERE AND NOWHERE ELSE. Issue #266.

    `until` is what would make this verdict worth asking again, as a
    PREDICATE rather than a sentence, written by the caller. See until_met().
    `reason` is why, from reasons.REASONS; a named reopen is `reopened`. #408.
    """
    from harness import reasons
    if outcome not in VERDICTS:
        raise ValueError(f"unknown outcome {outcome!r}; "
                         f"known: {', '.join(VERDICTS)}")
    if reopen:
        reason = reasons.REOPENED
    if reason and reason not in reasons.REASONS:
        raise ValueError(f"unknown reason {reason!r}; "
                         f"known: {', '.join(reasons.REASONS)}")
    # A RUN PATH THAT IS NOT A PATH IS NOT EVIDENCE. #266.
    if run_path and not (Path(run_path).is_absolute() or "/" in run_path
                         or "\\" in run_path):
        raise ValueError(
            f"run_path {run_path!r} is not a path. It names the run whose "
            f"receipt backs this verdict, and a verdict whose evidence cannot "
            f"be found again cannot be re-judged.")
    row = conn.execute("SELECT id FROM proposals WHERE name = ?",
                       (name,)).fetchone()
    if not row and not (candidate_id and not name):
        raise KeyError(f"no proposal named {name!r}")
    pid = row["id"] if row else None
    if pid is None and score is None and not run_path and not run_id:
        # A candidate no proposal names has no state to compare with. #184.
        same = conn.execute(
            "SELECT id, tier, outcome, detail, score, run_path, run_id "
            "FROM verdicts WHERE candidate_id = ? ORDER BY id DESC LIMIT 1",
            (candidate_id,)).fetchone()
        if (same and same["tier"] == tier and same["outcome"] == outcome
                and same["detail"] == detail and same["score"] is None
                and not same["run_path"] and not same["run_id"]):
            return same["id"]
    fields = {"outcome": outcome, "tier": tier, "detail": detail,
              "run_path": run_path, "score": score,
              "rubric": rubric, "judge": judge,
              "decided_at": time.time() if at is None else at,
              # Unknown is recorded as unknown, never omitted. #266.
              "machine_id": remember_machine(conn), "until": until,
              "size_bytes": int(size_bytes or 0),
              "upstream_idle_days": float(upstream_idle_days or 0.0),
              "candidate_id": candidate_id, "run_id": run_id,
              "reason": reason}
    if pid is None:
        cols = {**fields, "proposal_id": None}
        vid = conn.execute(
            f"INSERT INTO verdicts ({', '.join(cols)}) "
            f"VALUES ({', '.join('?' * len(cols))})",
            tuple(cols.values())).lastrowid
    else:
        vid = _write(conn, pid, name, fields, reopen=reopen, why=reopen_why)
    conn.commit()
    return vid
