"""#2174: the checks before and after the fetch ask one question of the memory, and only a decided verdict lifts the refetch block."""
from __future__ import annotations

import time

import pytest
from test_refetch_2161 import BASE, EDGE, _downloaded, _last, _queued, home  # noqa: F401 - the refetch fixtures of #2161
from test_screen_fetch_window_2127 import _row, _screen, screening  # noqa: F401 - the screen with its fetch recorded
from test_screen_window_2045 import planted  # noqa: F401 - the Studio of #2045

from harness import discovery_flow, fetching, memory, pipeline_yield, refetch, screen_window
from harness import memory_store as ms

PINNED = 32.8


def _state(monkeypatch, free, pinned):
    monkeypatch.setattr(memory, "available_gb", lambda: free)
    monkeypatch.setattr(memory, "pinned_gb", lambda: pinned)


@pytest.mark.parametrize("free", [8.0, 20.1, 28.0, 31.0, 40.0, 52.9, 70.0])
@pytest.mark.parametrize("need", [10.0, 30.0, 48.9, 60.0])
def test_before_and_after_the_fetch_the_same_memory_state_gets_the_same_answer(planted, monkeypatch, free, need):
    _state(monkeypatch, free, PINNED)
    before = screen_window.wanted(need) or not memory.held_back(need)
    after = not screen_window.still_short(need)
    assert before == after


def test_the_logged_state_refuses_48_9_both_ways_with_the_logged_numbers(planted, monkeypatch):
    _state(monkeypatch, 20.1, PINNED)
    assert not screen_window.wanted(48.9)
    _state(monkeypatch, 52.9, 0.0)
    assert memory.released_gb() == pytest.approx(34.9)
    assert "needs 48.9 GB but only 34.9 GB is safely available" in screen_window.still_short(48.9)
    assert "52.9 GB free" in screen_window.still_short(48.9) and "3.8 GB Docker VM" in screen_window.still_short(48.9)


def test_the_pins_released_and_the_pins_counted_budget_the_same_total(planted, monkeypatch):
    _state(monkeypatch, 20.1, PINNED)
    held = memory.released_gb()
    _state(monkeypatch, 20.1 + PINNED, 0.0)
    assert memory.released_gb() == pytest.approx(held)


def test_a_48_9_gib_screen_the_released_memory_cannot_hold_downloads_nothing(screening, monkeypatch):
    conn, fetched = screening
    _state(monkeypatch, 20.1, PINNED)
    assert _screen(conn, 48.9, monkeypatch, 900.0) == (False, "queued", None)
    assert fetched == []
    assert conn.execute("SELECT count(*) FROM downloads").fetchone()[0] == 0
    assert _last(conn, "Org/Big-27B")[1:3] == ("queued", "memory")


def test_a_screen_whose_window_opened_but_whose_memory_fell_short_is_queued_not_run(screening, monkeypatch):
    conn, fetched = screening
    _state(monkeypatch, 40.0, PINNED)
    monkeypatch.setattr(screen_window, "still_short", lambda need: "still short with the pinned set released: needs 48.9 GB")
    monkeypatch.setattr("harness.commands.screen._fetched", lambda conn, row: (fetched.append(row["name"]) or "", False))
    got = _screen(conn, 48.9, monkeypatch, 900.0)
    assert got == (False, "queued", None)
    assert _last(conn, "Org/Big-27B")[1] == "queued"


def test_a_queued_verdict_between_two_downloads_leaves_the_second_refused_with_a_mark(monkeypatch):
    fetched = []
    monkeypatch.setattr(fetching, "download", lambda repo, **k: fetched.append(repo) or f"/x/{repo}")
    monkeypatch.setattr(fetching, "requires", lambda name, conn=None: [])
    conn = ms.connect()
    try:
        _queued(conn, EDGE)
        _downloaded(conn, EDGE, ago_s=3600)
        ms.decide(conn, EDGE, "queued", tier=ms.SCREEN, detail="not screened: needs memory", reason="memory", until="room_gb:>48.9")
        conn.commit()
        why = fetching.ensure(conn, EDGE, free=900 * 1024 ** 3, floor=0, via="screen")
        assert fetched == [] and "no verdict was written since" in why
        assert EDGE in refetch.read()
    finally:
        conn.close()


@pytest.mark.parametrize("outcome,tier", [("declined", "screen"), ("broken", "screen"), ("screened", "screen"),
                                          ("measured", "measure")])
def test_each_decided_verdict_between_two_downloads_lets_the_second_go(monkeypatch, outcome, tier):
    conn = ms.connect()
    try:
        _queued(conn, EDGE)
        _downloaded(conn, EDGE, ago_s=3600)
        ms.decide(conn, EDGE, outcome, tier=tier, detail="decided", reason="candidate")
        conn.commit()
        assert refetch.refusal(conn, EDGE, "screen") == ""
    finally:
        conn.close()


def test_one_decided_set_serves_the_refetch_block_the_wasted_gib_and_the_yield():
    assert discovery_flow.DECIDED is refetch.DECIDED
    assert set(refetch.DECIDED) == {"declined", "broken", "measured", "adopted"}
    assert "queued" not in refetch.LIFTS and set(refetch.LIFTS) == set(refetch.DECIDED) | {"screened"}
    assert pipeline_yield.ADOPTED in refetch.DECIDED
