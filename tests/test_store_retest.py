"""A screen or measure rejection is retested up to 3 times, a week apart. #431."""
import argparse

import pytest

from harness import cli
from harness import memory_store as ms

T = 2_000_000_000.0
WEEK = ms.RETEST_AFTER_SECONDS


@pytest.fixture
def store(tmp_path):
    conn = ms.connect(tmp_path / "s.db")
    yield conn
    conn.close()


def _see(conn, name):
    ms.record(conn, ms.Seen(name=name, source="t", resolved=name,
                            kind="weights", registry=ms.HUGGINGFACE, lane="code"))


def _row(conn, name):
    return dict(conn.execute(
        "SELECT p.state, p.retest_count, p.next_retest_at, v.tier, v.detail, "
        "v.reopen_kind, v.reopens FROM proposals p JOIN verdicts v "
        "ON v.id = p.state_verdict_id WHERE p.name = ?", (name,)).fetchone())


def _reject(conn, name, outcome="broken", tier=ms.SCREEN, at=T, detail="x"):
    _see(conn, name)
    return ms.decide(conn, name, outcome, tier=tier, at=at, detail=detail)


# --- who is eligible -------------------------------------------------------

@pytest.mark.parametrize("outcome,tier", [
    ("broken", ms.SCREEN), ("declined", ms.SCREEN),
    ("declined", ms.MEASURE), ("broken", ms.MEASURE), ("declined", ms.ADOPT)])
def test_a_screen_or_measure_rejection_is_scheduled(store, outcome, tier):
    _reject(store, "org/m", outcome, tier)
    assert _row(store, "org/m")["next_retest_at"] == T + WEEK


@pytest.mark.parametrize("outcome,tier,detail", [
    ("declined", ms.INSPECT, "too-big: weights from 40.0 to 60.0 GiB"),
    ("declined", ms.INSPECT, "a lora: it attaches to a model rather than being one"),
    ("declined", ms.INSPECT, "needs-cuda"),
    ("declined", ms.FETCH, "dead upstream"),
    ("broken", ms.INSPECT, "clone failed"),
    # A screen refusal that names its condition reopens through `until`.
    ("declined", ms.SCREEN, "needs-cuda"),
    ("measured", ms.SCREEN, "won"),
    ("ignored", ms.SCREEN, "by hand")])
def test_fact_based_and_non_rejections_are_never_scheduled(store, outcome, tier,
                                                           detail):
    _reject(store, "org/m", outcome, tier, detail=detail)
    assert _row(store, "org/m")["next_retest_at"] is None
    assert ms.due_retests(store, T + 100 * WEEK) == []
    assert ms.reopen_due_retests(store, T + 100 * WEEK) == []
    assert _row(store, "org/m")["state"] == outcome


# --- when ------------------------------------------------------------------

def test_due_a_week_after_the_rejection_and_not_before(store):
    _reject(store, "org/m")
    assert ms.due_retests(store, T + WEEK - 1) == []
    assert ms.reopen_due_retests(store, T + WEEK - 1) == []
    assert [r["name"] for r in ms.due_retests(store, T + WEEK)] == ["org/m"]


# --- how -------------------------------------------------------------------

def test_a_reopen_is_a_named_retest_with_its_attempt(store):
    vid = _reject(store, "org/m")
    assert ms.reopen_due_retests(store, T + WEEK) == ["org/m"]
    got = _row(store, "org/m")
    assert (got["state"], got["tier"]) == ("queued", ms.INSPECT)
    assert got["reopen_kind"] == ms.RETEST and got["reopens"] == vid
    assert got["detail"].startswith("retest 1/3")
    assert (got["retest_count"], got["next_retest_at"]) == (1, None)


def test_a_waypoint_still_cannot_reopen_a_rejection_without_the_kind(store):
    _reject(store, "org/m")
    with pytest.raises(ms.IllegalTransition):
        ms.decide(store, "org/m", "queued", tier=ms.INSPECT, detail="again")
    with pytest.raises(ms.IllegalTransition):
        ms.decide(store, "org/m", "queued", tier=ms.INSPECT, detail="again",
                  reopen=ms.RETEST, reason="")
    assert _row(store, "org/m")["state"] == "broken"


def test_a_retest_cannot_reopen_a_success(store):
    _reject(store, "org/m", "measured", ms.ADOPT)
    with pytest.raises(ms.IllegalTransition):
        ms.decide(store, "org/m", "queued", tier=ms.INSPECT, detail="r",
                  reopen=ms.RETEST, reason="r")


def test_three_retests_then_the_rejection_is_final(store):
    _reject(store, "org/m")
    at = T
    for n in (1, 2, 3):
        at += WEEK
        assert ms.reopen_due_retests(store, at) == ["org/m"]
        assert _row(store, "org/m")["detail"].startswith(f"retest {n}/3")
        ms.decide(store, "org/m", "broken", tier=ms.SCREEN, at=at, detail="x")
    got = _row(store, "org/m")
    assert (got["retest_count"], got["next_retest_at"]) == (3, None)
    assert ms.reopen_due_retests(store, at + 100 * WEEK) == []
    assert _row(store, "org/m")["state"] == "broken"
    assert ms.retest_counts(store, at)["final"] == 1


def test_the_next_retest_follows_the_newest_rejection(store):
    _reject(store, "org/m")
    ms.reopen_due_retests(store, T + WEEK)
    ms.decide(store, "org/m", "declined", tier=ms.ADOPT, at=T + 9 * 86400,
              detail="lost")
    assert _row(store, "org/m")["next_retest_at"] == T + 9 * 86400 + WEEK


# --- what it found ---------------------------------------------------------

def test_a_retest_that_screens_is_a_recovered_false_negative(store):
    _reject(store, "org/m")
    ms.reopen_due_retests(store, T + WEEK)
    ms.decide(store, "org/m", "screened", tier=ms.SCREEN, at=T + WEEK + 1,
              detail="1 passed")
    got = ms.recovered_false_negatives(store)
    assert [r["name"] for r in got] == ["org/m"]
    assert got[0]["attempt"].startswith("retest 1/3")
    assert ms.retest_counts(store, T + WEEK)["recovered"] == 1


def test_a_retraction_that_screens_is_not_a_recovered_retest(store):
    _reject(store, "org/m")
    ms.retract(store, "org/m", "harness fault")
    ms.decide(store, "org/m", "screened", tier=ms.SCREEN, detail="1 passed")
    assert ms.recovered_false_negatives(store) == []


def test_counts_due_and_scheduled(store):
    _reject(store, "org/old", at=T - 2 * WEEK)
    _reject(store, "org/new", at=T)
    c = ms.retest_counts(store, T)
    assert (c["due"], c["pending"], c["final"]) == (1, 1, 0)
    assert "1 due, 1 scheduled" in cli.retest_line(c)


# --- the migration ---------------------------------------------------------

def test_backfill_schedules_existing_rejections_from_their_decision(tmp_path):
    path = tmp_path / "old.db"
    conn = ms.connect(path)
    _reject(conn, "org/screened-out", at=T - 30 * 86400)
    _reject(conn, "org/fresh", "declined", ms.ADOPT, at=T)
    _reject(conn, "org/too-big", "declined", ms.INSPECT,
            detail="too-big: weights from 40.0 to 60.0 GiB", at=T - 30 * 86400)
    for col in ("retest_count", "next_retest_at"):
        conn.execute(f"ALTER TABLE proposals DROP COLUMN {col}")
    conn.execute("UPDATE meta SET value = '25' WHERE key = 'schema'")
    conn.commit()
    conn.close()
    conn = ms.connect(path)
    try:
        got = {r["name"]: (r["retest_count"], r["next_retest_at"])
               for r in conn.execute(
                   "SELECT name, retest_count, next_retest_at FROM proposals")}
        assert got == {"org/screened-out": (0, T - 30 * 86400 + WEEK),
                       "org/fresh": (0, T + WEEK),
                       "org/too-big": (0, None)}
        assert [r["name"] for r in ms.due_retests(conn, T)] == ["org/screened-out"]
    finally:
        conn.close()


# --- the loop --------------------------------------------------------------

def test_the_loop_reopens_due_retests_from_the_store(monkeypatch, capsys):
    conn = ms.connect()
    _reject(conn, "org/m", at=T - 2 * WEEK)
    conn.close()
    monkeypatch.setattr(ms.time, "time", lambda: T)
    assert cli._reopen_retests() == ["org/m"]
    assert "reopened 1 rejection(s) for a retest" in capsys.readouterr().out
    conn = ms.connect()
    try:
        assert _row(conn, "org/m")["state"] == "queued"
    finally:
        conn.close()


def test_the_loop_spend_calls_the_retest_step(monkeypatch):
    called = []
    monkeypatch.setattr(cli, "_reopen_retests", lambda *a, **k: called.append(1) or [])
    monkeypatch.setattr(cli, "screenable_backlog", lambda want="": ["a"])
    monkeypatch.setattr(cli, "cmd_discover", lambda a: 0)
    monkeypatch.setattr(cli, "measurable", lambda *a, **k: [])
    cli._loop_spend(argparse.Namespace(top=1, budget_gib=1.0, lane=""), 0)
    assert called == [1]


def test_the_queue_report_shows_retests(monkeypatch, capsys):
    conn = ms.connect()
    _reject(conn, "org/m", at=T - 2 * WEEK)
    conn.close()
    monkeypatch.setattr(ms.time, "time", lambda: T)
    cli._report_queue(argparse.Namespace(lane="", json=False, top=5))
    assert "retests: 1 due, 0 scheduled" in capsys.readouterr().out
