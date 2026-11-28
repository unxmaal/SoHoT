"""#2202: the check before a fetch and the check after it see the same free memory, the fetch's own bytes counted."""
from __future__ import annotations

import pytest
from test_refetch_2161 import _last, home  # noqa: F401 - the refetch fixtures of #2161
from test_screen_fetch_window_2127 import _screen, screening  # noqa: F401 - the screen with its fetch recorded
from test_screen_window_2045 import planted  # noqa: F401 - the Studio of #2045

from harness import memory, screen_window

PINNED = 32.8


def _state(monkeypatch, free, pinned):
    monkeypatch.setattr(memory, "available_gb", lambda: free)
    monkeypatch.setattr(memory, "pinned_gb", lambda: pinned)


def test_a_fetch_still_to_land_takes_its_bytes_from_the_free_memory_the_screen_will_see(planted, monkeypatch):
    _state(monkeypatch, 40.0, PINNED)
    assert memory.can_load(48.9)[0] == "window"
    assert memory.can_load(48.9, landing=48.9)[0] == "never"
    assert memory.can_load(10.0, landing=10.0)[0] == "now"


def test_the_one_answer_is_now_window_or_never_by_the_same_budgets(planted, monkeypatch):
    _state(monkeypatch, 52.9, 0.0)
    assert memory.can_load(30.0)[0] == "now"
    assert memory.can_load(48.9)[0] == "never"
    assert "34.9 GB is safely available" in memory.can_load(48.9)[1]
    _state(monkeypatch, 20.1, PINNED)
    assert memory.can_load(25.0)[0] == "window"
    assert memory.can_load(60.0)[0] == "never"


def test_wanted_and_still_short_agree_with_can_load_once_the_landing_is_counted(planted, monkeypatch):
    _state(monkeypatch, 40.0, PINNED)
    assert screen_window.wanted(48.9) and not screen_window.wanted(48.9, landing=48.9)
    _state(monkeypatch, 40.0 - 48.9, 0.0)
    assert screen_window.still_short(48.9)


def test_a_candidate_between_the_two_figures_is_refused_before_it_is_downloaded(screening, monkeypatch):
    conn, fetched = screening
    _state(monkeypatch, 40.0, PINNED)
    assert memory.released_gb() >= 48.9
    assert _screen(conn, 48.9, monkeypatch, 900.0) == (False, "queued", None)
    assert fetched == []
    assert conn.execute("SELECT count(*) FROM downloads").fetchone()[0] == 0
    assert _last(conn, "Org/Big-27B")[1:3] == ("queued", "memory")


def test_a_candidate_whose_copy_is_on_disk_lands_nothing(planted, monkeypatch):
    monkeypatch.setattr(memory, "cache_path", lambda repo: "/cache/x")
    assert memory.landing_gb("Org/Big-27B", 48.9) == 0.0
    monkeypatch.setattr(memory, "cache_path", lambda repo: None)
    assert memory.landing_gb("Org/Big-27B", 48.9) == pytest.approx(48.9)
    assert memory.landing_gb("Org/Big-27B", "ds4: unchecked") == 0.0
