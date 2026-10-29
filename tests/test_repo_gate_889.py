"""The repo lane gates code adoption: repo comparisons run first, and a code one runs only after a repo win. #889."""
import argparse
import sys

import pytest

from harness import memory_store as ms
from harness import repo_gate
from harness.commands import loop as loop_cmd


@pytest.fixture
def store(tmp_path):
    conn = ms.connect(tmp_path / "s.db")
    yield conn
    conn.close()


@pytest.fixture
def held(monkeypatch):
    """The gate as it holds on a machine that has validated enough repo tasks."""
    monkeypatch.setattr(repo_gate, "active", lambda: True)


def _screened(conn, name, lane="code"):
    ms.record(conn, ms.Seen(name=name, source="t", resolved=name, kind="weights",
                            registry=ms.HUGGINGFACE, lane=lane))
    ms.decide(conn, name, "screened", tier=ms.SCREEN, detail="ok")


def _adopt_verdict(conn, name, lane, won):
    ms.decide(conn, name, "measured" if won else "declined", tier=ms.ADOPT, detail=f"{lane}: x")


def test_every_code_row_gets_a_repo_comparison_just_ahead_of_it(store, held):
    rows = [{"name": "a", "lane": "code"}, {"name": "img", "lane": "image"}, {"name": "b", "lane": "code"}]
    got = repo_gate.order(rows, store)
    assert [(r["name"], r["lane"]) for r in got] == [
        ("a", "repo"), ("a", "code"), ("img", "image"), ("b", "repo"), ("b", "code")]


def test_a_queued_repo_measurement_is_not_doubled_and_goes_ahead_of_its_code_row(store, held):
    rows = [{"name": "a", "lane": "code"}, {"name": "a", "lane": "repo"}]
    got = repo_gate.order(rows, store)
    assert [(r["name"], r["lane"]) for r in got] == [("a", "repo"), ("a", "code")]


def test_a_sweep_scoped_to_another_lane_adds_no_repo_row(store, held):
    rows = [{"name": "a", "lane": "code"}]
    assert repo_gate.order(rows, store, want="web") == rows
    assert repo_gate.order(rows, store, want="repo") == rows


def test_without_enough_valid_tasks_the_order_is_untouched(store, monkeypatch):
    monkeypatch.setattr(repo_gate, "valid_tasks", lambda machine=None: set(range(repo_gate.MIN_TASKS - 1)))
    rows = [{"name": "a", "lane": "code"}]
    assert repo_gate.order(rows, store) == rows
    assert repo_gate.blocked(store, rows[0]) == ""


def test_the_gate_holds_at_min_tasks_on_a_mac_with_the_sandbox(monkeypatch):
    from evals import repo
    monkeypatch.setattr(repo_gate.sys, "platform", "darwin")
    monkeypatch.setattr(repo, "SANDBOX_EXEC", sys.executable)
    monkeypatch.setattr(repo_gate, "valid_tasks", lambda machine=None: set(range(repo_gate.MIN_TASKS)))
    assert repo_gate.active()
    monkeypatch.setattr(repo_gate.sys, "platform", "linux")
    assert not repo_gate.active()


@pytest.mark.gauntlet("state-is-whichever-row-came-last", site="harness/repo_gate.py:verdict")
def test_a_code_comparison_waits_on_a_repo_win(store, held):
    _screened(store, "a")
    row = {"name": "a", "lane": "code"}
    assert "not measured there" in repo_gate.blocked(store, row)
    _adopt_verdict(store, "a", "repo", won=False)
    assert "declined" in repo_gate.blocked(store, row)
    _adopt_verdict(store, "a", "repo", won=True)
    assert repo_gate.blocked(store, row) == ""
    assert repo_gate.blocked(store, {"name": "a", "lane": "repo"}) == ""
    _adopt_verdict(store, "a", "code", won=True)
    assert repo_gate.blocked(store, row) == "", "a later code verdict is not a repo verdict"
    _adopt_verdict(store, "a", "repo", won=False)
    assert "declined" in repo_gate.blocked(store, row), "a retest that lost the repo lane holds the gate again"


def test_a_code_verdict_does_not_count_as_the_repo_win(store, held):
    _screened(store, "a")
    _adopt_verdict(store, "a", "code", won=True)
    assert repo_gate.blocked(store, {"name": "a", "lane": "code"})


def test_a_repo_winner_whose_code_comparison_never_ran_is_owed_it_next_sweep(store, held):
    _screened(store, "a")
    _screened(store, "b")
    _adopt_verdict(store, "a", "repo", won=True)
    _adopt_verdict(store, "b", "repo", won=False)
    assert [r["name"] for r in repo_gate.owed(store)] == ["a"]
    got = repo_gate.order(repo_gate.join([], store), store)
    assert [(r["name"], r["lane"]) for r in got] == [("a", "code")]
    _adopt_verdict(store, "a", "code", won=True)
    assert repo_gate.owed(store) == []


def test_a_repo_row_is_measured_in_the_repo_lane_even_in_a_sweep_scoped_to_code():
    a = argparse.Namespace(lane="code", top=0)
    got = repo_gate.args_for(a, {"name": "x", "lane": "repo"})
    assert got.lane == "repo" and got.top == 0 and a.lane == "code"
    assert repo_gate.args_for(a, {"name": "x", "lane": "code"}) is a


def test_the_measure_step_skips_a_gated_row_and_measures_the_repo_row_in_the_repo_lane(monkeypatch, held):
    conn = ms.connect()
    try:
        _screened(conn, "a")
    finally:
        conn.close()
    seen = []

    def fake(a, row, sweep=None):
        seen.append((row["name"], row["lane"], a.lane))
        return 0

    monkeypatch.setattr(loop_cmd.measure_cmd, "_measure_and_adopt", fake)
    a = argparse.Namespace(lane="code")
    rc = loop_cmd._measure_all(a, [{"name": "a", "lane": "repo"}, {"name": "a", "lane": "code"}], None, [])
    assert rc == 0 and seen == [("a", "repo", "repo")]


def test_a_repo_win_in_the_same_sweep_lets_its_code_comparison_run(monkeypatch, held):
    conn = ms.connect()
    try:
        _screened(conn, "a")
    finally:
        conn.close()
    seen = []

    def fake(a, row, sweep=None):
        seen.append((row["name"], row["lane"], a.lane))
        if row["lane"] == "repo":
            conn = ms.connect()
            try:
                _adopt_verdict(conn, "a", "repo", won=True)
            finally:
                conn.close()
        return 0

    monkeypatch.setattr(loop_cmd.measure_cmd, "_measure_and_adopt", fake)
    loop_cmd._measure_all(argparse.Namespace(lane=""), [{"name": "a", "lane": "repo"}, {"name": "a", "lane": "code"}],
                          None, [])
    assert seen == [("a", "repo", "repo"), ("a", "code", "")]
