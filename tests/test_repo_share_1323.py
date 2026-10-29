"""#1323: the repo gate orders a code row's repo comparison by gain per GPU-minute instead of ahead of every lane."""
import pytest

from harness import measure_gain, measure_replay, repo_gate
from harness import memory_store as ms
from harness.commands import loop
from harness.commands import measure as measure_cmd
from tests.test_measure_gain_1315 import DAY, NOW, paired_run


@pytest.fixture
def conn(tmp_path):
    c = ms.connect(tmp_path / "s.db")
    yield c
    c.close()


@pytest.fixture
def price(monkeypatch):
    """Minutes per (name, lane), set by each test; a pair left out is unpriced."""
    got: dict = {}
    monkeypatch.setattr(measure_gain, "minutes", lambda conn, row, lane: (got.get((row["name"], lane)), "unpriced"))
    monkeypatch.setattr(measure_gain, "incumbent_rates", lambda conn, lane: {})
    return got


@pytest.fixture
def gate(monkeypatch):
    monkeypatch.setattr(repo_gate, "active", lambda: True)
    monkeypatch.setattr(measure_cmd.methods, "runs_in", lambda name, lane: True)


def queue(conn, rows, monkeypatch, paused=()):
    monkeypatch.setattr(measure_cmd, "measurable", lambda store, top, want="", **kw: list(rows))
    monkeypatch.setattr(measure_cmd, "resume_first", lambda store, fresh, want="": list(paused) + [
        r for r in fresh if r["name"] not in {p["name"] for p in paused}])
    said: list[str] = []
    got = loop.measure_queue(conn, "", 0, room=lambda row: (True, None, ""), slots=0, say=said.append)
    return [(r["name"], r["lane"]) for r in got], said


def test_a_cheap_high_gain_row_in_another_lane_starts_before_a_repo_slice_of_lower_gain_per_minute(
        conn, price, gate, monkeypatch):
    paired_run(conn, "p/Filter", 5, 0, 11, lane="pii")
    price.update({("p/Filter", "pii"): 13.0, ("x/Code-27B", "code"): 300.0, ("x/Code-27B", "repo"): 600.0})
    got, _ = queue(conn, [{"name": "x/Code-27B", "lane": "code"}, {"name": "p/Filter", "lane": "pii"}], monkeypatch)
    assert got == [("p/Filter", "pii"), ("x/Code-27B", "repo"), ("x/Code-27B", "code")]


def test_a_gated_code_rows_repo_comparison_runs_right_before_it_keyed_as_the_pair(conn, price, gate, monkeypatch):
    paired_run(conn, "b/Strong-27B", 12, 1, 30)
    price.update({("a/Plain-27B", "code"): 300.0, ("a/Plain-27B", "repo"): 300.0,
                  ("b/Strong-27B", "code"): 300.0, ("b/Strong-27B", "repo"): 600.0})
    rows = [{"name": "a/Plain-27B", "lane": "code"}, {"name": "b/Strong-27B", "lane": "code"}]
    got, said = queue(conn, rows, monkeypatch)
    assert got == [("b/Strong-27B", "repo"), ("b/Strong-27B", "code"), ("a/Plain-27B", "repo"), ("a/Plain-27B", "code")]
    assert any("b/Strong-27B (code)" in s and "after its repo comparison" in s for s in said)
    ctx = measure_gain.context(conn)
    first = measure_gain.score(ctx, {"name": "b/Strong-27B", "lane": "repo"})
    alone = measure_gain.score(ctx, rows[1])
    pair = measure_gain.score(ctx, rows[1], gated=True)
    assert pair.key == pytest.approx(max(first.key, (first.expected + alone.expected) / (first.minutes + alone.minutes)))
    assert pair.key < alone.key, "the pair is priced with the repo minutes it waits on"


def test_a_paused_run_stays_ahead_of_every_repo_comparison(conn, price, gate, monkeypatch):
    price.update({("a/Plain-27B", "code"): 300.0, ("a/Plain-27B", "repo"): 300.0, ("p/Paused-9B", "ocr"): 300.0})
    paused = [{"name": "p/Paused-9B", "lane": "ocr"}]
    got, _ = queue(conn, [{"name": "a/Plain-27B", "lane": "code"}], monkeypatch, paused=paused)
    assert got[0] == ("p/Paused-9B", "ocr")
    assert [g for g in got if g[1] == "repo"] == [("a/Plain-27B", "repo")]


def test_a_repo_winner_owed_its_code_comparison_is_ordered_by_its_key(conn, price, gate, monkeypatch):
    paired_run(conn, "w/Winner-9B", 9, 0, 20)
    ms.decide(conn, "w/Winner-9B", "measured", tier=ms.ADOPT, reason="candidate", detail="repo: won")
    price.update({("w/Winner-9B", "code"): 30.0, ("a/Plain-27B", "code"): 300.0, ("a/Plain-27B", "repo"): 300.0})
    got, _ = queue(conn, [{"name": "a/Plain-27B", "lane": "code"}], monkeypatch)
    assert got == [("w/Winner-9B", "code"), ("a/Plain-27B", "repo"), ("a/Plain-27B", "code")]


def test_the_replay_says_the_minutes_each_lane_takes(conn, monkeypatch):
    night = {"start": NOW - DAY, "measure_at": NOW - DAY, "window_s": 3600.0, "queued": 2, "held": [], "began": [],
             "survivors": {"taken": [{"name": "a", "lane": "repo", "spend_s": 3000.0},
                                     {"name": "b", "lane": "pii", "spend_s": 600.0}], "cut": []},
             "gain": {"taken": [{"name": "b", "lane": "pii", "spend_s": 780.0},
                                {"name": "c", "lane": "pii", "spend_s": 60.0},
                                {"name": "a", "lane": "repo", "spend_s": 2760.0}], "cut": []}}
    monkeypatch.setattr(measure_replay, "replay", lambda conn, days, **kw: [night])
    lines = measure_replay.report(conn, 1)
    assert "  minutes:        repo 50, pii 10" in lines
    assert "  minutes:        repo 46, pii 14" in lines


def test_the_replay_leaves_out_a_row_the_gate_holds_that_night(conn, gate):
    got = measure_replay.queue(conn, [{"name": "a/Plain-27B", "lane": "code"}, {"name": "o/Ocr-1B", "lane": "ocr"}],
                               [], now=NOW, gate=True)
    assert [(r["name"], r["lane"]) for r in got] == [("a/Plain-27B", "repo"), ("o/Ocr-1B", "ocr")]


def test_the_replay_owes_a_code_comparison_only_from_its_repo_win(conn, gate):
    paired_run(conn, "w/Winner-9B", 9, 0, 20, at=NOW - 3 * DAY)
    ms.decide(conn, "w/Winner-9B", "measured", tier=ms.ADOPT, at=NOW - DAY, reason="candidate", detail="repo: won")
    assert measure_replay.owed_at(conn, NOW - 2 * DAY) == []
    assert [(r["name"], r["lane"]) for r in measure_replay.owed_at(conn, NOW)] == [("w/Winner-9B", "code")]
    assert measure_replay.owed_at(conn, float("inf")) == repo_gate.owed(conn), "the replay and the loop owe the same rows"
    row ={"name": "w/Winner-9B", "lane": "code"}
    assert repo_gate.needs(conn, row, before=NOW - 2 * DAY) and not repo_gate.needs(conn, row, before=NOW)
