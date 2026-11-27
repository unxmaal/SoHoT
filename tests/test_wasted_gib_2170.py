"""Wasted GiB: a removal under a deferral (queued, screened) or a repo fetched again is waste; a decided removal kept once is not. #2170."""
from __future__ import annotations

import time

import pytest

from harness import discovery_flow as df
from harness import memory_store as ms
from harness import pipeline_yield as py

NOW = time.time()
GIB = 1 << 30


def _removal(conn, pid: int, outcome: str, tier: str, at: float) -> int:
    return conn.execute("INSERT INTO verdicts (proposal_id, tier, outcome, decided_at, machine_id, lane) VALUES (?,?,?,?,?, 'tts')",
                        (pid, tier, outcome, at, ms.remember_machine(conn))).lastrowid


def _fetch(conn, repo: str, gib: float, at: float, verdict: tuple[str, str] | None = None) -> int:
    pid = conn.execute("SELECT id FROM proposals WHERE name = ?", (repo,)).fetchone()
    pid = pid[0] if pid else conn.execute("INSERT INTO proposals (name, first_seen, last_seen, state, lane) VALUES (?,?,?,?, 'tts')",
                                          (repo, NOW - 9e5, NOW - 9e5, "queued")).lastrowid
    vid = _removal(conn, pid, verdict[0], verdict[1], at + 600) if verdict else None
    conn.execute("INSERT INTO downloads (proposal_id, repo, kind, path, origin, bytes, complete, state, started_at, finished_at, removed_at, "
                 "removed_by, removal_verdict_id, machine_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                 (pid, repo, "hub", f"/w/{repo}-{at}", "fetch", int(gib * GIB), 1, "removed" if verdict else "complete", at, at + 300,
                  at + 900 if verdict else None, "test" if verdict else "", vid, ms.remember_machine(conn)))
    return pid


def _plant(conn) -> None:
    day = 86400
    _fetch(conn, "org/queued", 10, NOW - 3 * day, ("queued", "screen"))
    _fetch(conn, "org/screened", 20, NOW - 3 * day, ("screened", "screen"))
    _fetch(conn, "org/declined", 40, NOW - 3 * day, ("declined", "adopt"))
    _fetch(conn, "org/again-decided", 5, NOW - 3 * day, ("declined", "adopt"))
    _fetch(conn, "org/again-decided", 5, NOW - 2 * day)
    _fetch(conn, "org/again-queued", 7, NOW - 3 * day, ("queued", "fetch"))
    _fetch(conn, "org/again-queued", 7, NOW - 2 * day)


def _db(populate):
    conn = ms.connect()
    populate(conn)
    conn.commit()
    return conn


def test_the_exact_waste_and_each_component_over_a_planted_store():
    conn = _db(_plant)
    try:
        rows = df.wasted(conn, df._fetched(conn, NOW - 7 * 86400))
        got = df.waste_gib(rows)
    finally:
        conn.close()
    assert {r["repo"] for r in rows} == {"org/queued", "org/screened", "org/again-decided", "org/again-queued"}
    assert (got["gib"], got["undecided_gib"], got["again_gib"], got["n"]) == (42.0, 37.0, 12.0, 4)


def test_a_decided_removal_fetched_once_is_not_waste():
    def plant(conn):
        _fetch(conn, "org/kept", 40, NOW - 86400, ("declined", "adopt"))
        _fetch(conn, "org/measured", 9, NOW - 86400, ("measured", "adopt"))
        _fetch(conn, "org/broken", 3, NOW - 86400, ("broken", "screen"))
    conn = _db(plant)
    try:
        assert df.wasted(conn, df._fetched(conn, NOW - 7 * 86400)) == []
    finally:
        conn.close()


def test_the_yield_and_the_flow_leak_report_the_same_waste():
    conn = _db(_plant)
    try:
        t = py.gather(conn, NOW)["windows"]["7"]["total"]
        leak = df.gather(conn, NOW)["leaks"]
    finally:
        conn.close()
    assert (t["gib"], t["wasted_gib"], t["wasted_undecided_gib"], t["wasted_again_gib"]) == (94.0, 42.0, 37.0, 12.0)
    deleted = next(x for x in leak if x["key"] == "deleted")
    assert (deleted["n"], deleted["undecided_gib"], deleted["again_gib"]) == (42.0, 37.0, 12.0)
    assert "37.0 GiB removed with no decision" in deleted["text"] and "12.0 GiB fetched again" in deleted["text"]


@pytest.mark.parametrize("outcome,waste", [("queued", 10.0), ("screened", 10.0), ("declined", 0.0), ("broken", 0.0), ("measured", 0.0)])
def test_only_a_deferral_makes_a_removal_waste(outcome, waste):
    conn = _db(lambda c: _fetch(c, "org/x", 10, NOW - 86400, (outcome, "screen")))
    try:
        assert df.waste_gib(df.wasted(conn, df._fetched(conn, NOW - 7 * 86400)))["gib"] == waste
    finally:
        conn.close()
