"""Retests: which refusals are due another look, and what came of them."""
from __future__ import annotations

import time

from harness.memory_store.schema import INSPECT
from harness.memory_store.transitions import (REOPENS, RETEST, RETESTS, decide_or_skip,
    retest_eligible)


def due_retests(conn, now: float | None = None) -> list[dict]:
    """Rejections whose next retest has come due, oldest first. #431."""
    now = time.time() if now is None else now
    rows = conn.execute(
        "SELECT p.name, p.state, p.retest_count, p.next_retest_at, v.tier, "
        "v.until FROM proposals p JOIN verdicts v ON v.id = p.state_verdict_id "
        "WHERE p.next_retest_at IS NOT NULL AND p.next_retest_at <= ? "
        "AND p.retest_count < ? ORDER BY p.next_retest_at, p.id",
        (now, RETESTS)).fetchall()
    return [dict(r) for r in rows
            if retest_eligible(r["state"], r["tier"], r["until"])]


def reopen_due_retests(conn, now: float | None = None) -> list[str]:
    """Reopen each due retest to queued at inspect, naming the attempt. #431."""
    now = time.time() if now is None else now
    names = []
    for r in due_retests(conn, now):
        why = f"retest {r['retest_count'] + 1}/{RETESTS}: {r['state']} at {r['tier']}"
        if decide_or_skip(conn, r["name"], "queued", tier=INSPECT, at=now,
                          detail=why, reopen=RETEST, reopen_why=why) is not None:
            names.append(r["name"])
    return names


def recovered_false_negatives(conn) -> list[dict]:
    """Candidates a screen or measure passed after a retest reopened them. #431."""
    return [dict(r) for r in conn.execute(
        "SELECT p.name, p.state, MAX(r.detail) AS attempt, "
        "MIN(w.decided_at) AS recovered_at FROM verdicts r "
        "JOIN proposals p ON p.id = r.proposal_id "
        "JOIN verdicts w ON w.proposal_id = r.proposal_id AND w.id > r.id "
        "AND w.outcome IN ('screened', 'measured') "
        "WHERE r.reopen_kind = ? GROUP BY p.id, p.name, p.state ORDER BY p.name",
        (RETEST,))]


def retest_counts(conn, now: float | None = None) -> dict:
    """Retests due now, scheduled later, spent for good, and recovered. #431."""
    now = time.time() if now is None else now
    pending = conn.execute(
        "SELECT COUNT(*) FROM proposals WHERE next_retest_at > ?",
        (now,)).fetchone()[0]
    final = conn.execute(
        "SELECT COUNT(*) FROM proposals WHERE retest_count >= ? "
        "AND next_retest_at IS NULL AND state IN (?, ?)",
        (RETESTS, *REOPENS[RETEST])).fetchone()[0]
    return {"due": len(due_retests(conn, now)), "pending": pending,
            "final": final, "recovered": len(recovered_false_negatives(conn))}
