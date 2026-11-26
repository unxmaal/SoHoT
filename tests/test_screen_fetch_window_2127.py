"""The screen decides its window before it fetches: a candidate that cannot be tested is not downloaded. #2127."""
from __future__ import annotations

import functools

import pytest
from test_screen_window_2045 import Server, planted  # noqa: F401 - the Studio of #2045

from harness import memory, screen, screen_window
from harness import memory_store as ms
from harness.commands import screen as screen_cmd


@pytest.fixture
def screening(planted, monkeypatch):  # noqa: F811
    server, fetched = Server(), []
    monkeypatch.setattr(memory, "available_gb", lambda: 70.0)
    monkeypatch.setattr(memory, "total_gb", lambda: 96.0)
    monkeypatch.setattr(screen_window, "refusal", functools.partial(screen_window.refusal, get=server.get))
    monkeypatch.setattr(screen_cmd, "known_killer", lambda *a, **k: None)

    def fetch(conn, row):
        fetched.append(row["name"])
        return "stop here", False
    monkeypatch.setattr(screen_cmd, "_fetched", fetch)
    conn = ms.connect()
    yield conn, fetched
    conn.close()


def _row(name="Org/Big-27B"):
    return {"name": name, "candidate": f"hf-text:{name}", "modality": "text"}


def _screen(conn, need, monkeypatch, deadline):
    monkeypatch.setattr(memory, "need_gb", lambda *a, **k: need)
    monkeypatch.setattr(screen, "deadline_s", lambda candidate: deadline)
    row = _row()
    ms.record(conn, ms.Seen(name=row["name"], source="t", kind="weights", lane="text", why="seeded"))
    return screen_cmd._screen_one(None, conn, row)


def test_a_candidate_over_the_ceiling_with_no_window_to_grant_is_never_fetched(screening, monkeypatch):
    conn, fetched = screening
    got = _screen(conn, 48.1, monkeypatch, None)
    assert got == (False, "queued", None)
    assert fetched == []
    assert ms.latest(conn, "Org/Big-27B")["outcome"] == "queued"


def test_a_candidate_over_the_ceiling_even_with_the_pins_released_is_never_fetched(screening, monkeypatch):
    conn, fetched = screening
    assert _screen(conn, 179.2, monkeypatch, 900.0) == (False, "queued", None)
    assert fetched == []


def test_a_candidate_whose_window_would_be_refused_because_the_pinned_set_is_not_loaded_is_never_fetched(
        screening, monkeypatch):
    conn, fetched = screening
    server = Server()
    server.status = {k: "unloaded" for k in server.status}
    monkeypatch.setattr(screen_window, "refusal", functools.partial(screen_window.refusal.func, get=server.get))
    assert _screen(conn, 48.1, monkeypatch, 900.0) == (False, "queued", None)
    assert fetched == []


def test_a_candidate_that_fits_in_a_grantable_window_is_fetched(screening, monkeypatch):
    conn, fetched = screening
    _screen(conn, 25.0, monkeypatch, 900.0)
    assert fetched == ["Org/Big-27B"]


def test_a_candidate_that_fits_beside_the_pinned_set_is_fetched(screening, monkeypatch):
    conn, fetched = screening
    _screen(conn, 10.0, monkeypatch, None)
    assert fetched == ["Org/Big-27B"]
