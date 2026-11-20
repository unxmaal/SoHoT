"""A sweep releases an idle interactive server's pinned set for a load the fit check refuses, never one used in the last IDLE_S. #2087."""
from __future__ import annotations

import time

import pytest

from harness import containers, interactive, memory, screen_window
from harness import memory_store as ms
from harness.commands import loop as loop_cmd
from harness.commands import measure as measure_cmd

URL = "http://127.0.0.1:18083"
GIB = 1024 ** 3
CODE = "Ornith-1.5-35B-Q4_K_M"
DECIDE = "imajev-4b-Q8_0"
NOW = time.time()
REAL_STANDING = memory.standing_gb


class Server:
    def __init__(self):
        self.status = {CODE: "loaded", DECIDE: "loaded"}
        self.calls = []

    def get(self, path):
        if path.startswith("/slots"):
            return []
        return {"data": [{"id": k, "status": {"value": v}} for k, v in self.status.items()]}

    def post(self, path, body):
        self.calls.append((path, body["model"]))
        self.status[body["model"]] = "unloaded" if path == "/models/unload" else "loaded"


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


@pytest.fixture
def night(monkeypatch):
    """The 2026-11-20 sweep: 32.8 GiB pinned, 32.9 GiB free beside it, so a 20.2 GiB screen gets 14.9 GiB."""
    entry = lambda stem, gib: {"stem": stem, "bytes": int(gib * GIB), "served": f"llamacpp:{stem}", "ctx": 32768}  # noqa: E731
    interactive.write({"url": URL, "bytes": int(32.8 * GIB),
                       "lanes": {"code": entry(CODE, 27.7), "decide": entry(DECIDE, 5.1)}})
    monkeypatch.setattr(memory, "ceiling_gb", lambda: 77.8)
    monkeypatch.setattr(memory, "measured_reserve_gb", lambda: 18.0)
    monkeypatch.setattr(memory, "available_gb", lambda: 32.9 + _freed())
    monkeypatch.setattr(containers, "vm_gb", lambda: 3.8)
    monkeypatch.setattr(interactive, "key", lambda environ=None: "")
    monkeypatch.setattr(interactive, "_served", lambda config=None: {})
    monkeypatch.setattr(memory, "standing_gb", REAL_STANDING)


def _freed() -> float:
    """What a window gave back: the pinned GiB no longer held."""
    return 32.8 - memory.pinned_gb() if interactive.windowed() else 0.0


def _asked(at, lane="code", alias="sohot-code", purpose="work", total_s=30.0):
    conn = ms.connect()
    try:
        conn.execute("INSERT INTO gateway_requests (at, alias, lane, served, purpose, total_s) VALUES (?,?,?,?,?,?)",
                     (at, alias, lane, CODE, purpose, total_s))
        conn.commit()
    finally:
        conn.close()


def _fits(need):
    return memory.fits(need, memory.available_gb(), memory.ceiling_gb(), 0.0, memory.measured_reserve_gb(),
                       memory.pinned_gb(), containers.vm_gb())


def _window(server, clock, keep=()):
    return screen_window.idle_release(3600.0, "the measure step", keep=keep, now=NOW, get=server.get,
                                      post=server.post, sleep=clock.sleep, clock=clock, say=lambda m: None)


def test_the_fit_plan_of_the_night_refuses_the_screen_beside_the_pinned_set(night):
    ok, why = _fits(20.2)
    assert not ok and "only 14.9 GB" in why and "32.8 GB held by the interactive server" in why
    assert not memory.held_back(20.2), "it fits the standing share, so the #2045 window never took it"


def test_an_idle_interactive_holder_is_freed_and_the_candidate_admitted(night):
    _asked(NOW - 2 * screen_window.IDLE_S)
    assert screen_window.wanted(20.2, now=NOW)
    server, clock = Server(), Clock()
    with _window(server, clock) as released:
        assert released == [CODE, DECIDE]
        assert set(server.status.values()) == {"unloaded"}
        ok, why = _fits(20.2)
        assert ok, why
    assert set(server.status.values()) == {"loaded"} and not interactive.windowed()


def test_a_request_in_the_last_idle_s_keeps_the_pinned_set(night):
    _asked(NOW - screen_window.IDLE_S / 2)
    assert not screen_window.wanted(20.2, now=NOW)
    server, clock = Server(), Clock()
    with _window(server, clock) as released:
        assert released == []
        assert not _fits(20.2)[0]
    assert server.calls == [] and not interactive.windowed()


def test_a_long_request_that_ended_inside_idle_s_counts_from_its_end(night):
    _asked(NOW - 2 * screen_window.IDLE_S, total_s=1.5 * screen_window.IDLE_S)
    assert not screen_window.wanted(20.2, now=NOW)


def test_eval_smoke_and_watchdog_traffic_does_not_count_as_use(night):
    for p in ("eval", "smoke", "watchdog"):
        _asked(NOW - 60, purpose=p)
    _asked(NOW - 60, lane="web", alias="sohot-web")
    assert screen_window.quiet_s(now=NOW) == float("inf")
    assert screen_window.wanted(20.2, now=NOW)


def test_a_window_cannot_fit_what_releasing_the_set_would_not(night):
    assert not screen_window.wanted(60.0, now=NOW)


def test_a_kept_incumbent_stays_loaded_counted_and_answered_in_the_window(night):
    server, clock = Server(), Clock()
    with _window(server, clock, keep={CODE}) as released:
        assert released == [DECIDE]
        assert server.status == {CODE: "loaded", DECIDE: "unloaded"}
        assert memory.pinned_gb() == pytest.approx(27.7)
        with interactive.answer() as arms:
            assert list(arms) == [CODE], "a released stem is never asked of the interactive server"
    assert memory.pinned_gb() == pytest.approx(32.8)


def test_the_measure_step_keeps_the_pinned_incumbents_of_its_queued_lanes(night, monkeypatch):
    from harness import adopt, screen, winners
    monkeypatch.setattr(winners, "typed", lambda: {})
    monkeypatch.setattr(adopt, "default_for", lambda lane, typed="": {"code": f"llamacpp:{CODE}",
                                                                        "decide": f"llamacpp:{DECIDE}"}.get(lane, ""))
    monkeypatch.setattr(screen, "candidate_for", lambda lane, spec: spec)
    assert loop_cmd._pinned_incumbents({"code", "web"}) == {CODE}
    seen = {}

    def release(hold_s, why, keep=(), **kw):
        seen.update(hold_s=hold_s, keep=set(keep))
        return screen_window.contextlib.nullcontext([])

    monkeypatch.setattr(screen_window, "idle_release", release)
    monkeypatch.setattr(measure_cmd, "take_incumbents", lambda want: None)
    monkeypatch.setattr(loop_cmd, "_queued_lanes", lambda store, want, top: {"code"})
    monkeypatch.setattr(loop_cmd, "measure_queue", lambda *a, **k: [])
    sweep = type("S", (), {"remaining": lambda self: 900.0, "stopped": ""})()
    loop_cmd._measure(type("A", (), {"top": 0, "lane": ""})(), sweep, [])
    assert seen == {"hold_s": 900.0, "keep": {CODE}}


@pytest.mark.gauntlet("a-copy-whose-key-leaves-out-an-input-or-that-nothing-invalidates",
                      site="harness/interactive.py:keep_in_window")
def test_a_kept_record_outliving_its_window_is_ignored(night):
    interactive.keep_in_window([CODE])
    assert not interactive.windowed() and interactive.window_kept() == set()
    assert memory.pinned_gb() == pytest.approx(32.8), "a stale record never shrinks the pinned set"


def test_an_unreadable_kept_record_counts_the_whole_set_held_not_released(night):
    from harness import gateway_switch
    gateway_switch.start_drain(NOW + 600, node=interactive.WINDOW)
    try:
        interactive.keep_in_window([])
        assert interactive.window_kept() == set() and memory.pinned_gb() == 0.0
        interactive._kept_path().write_text("{not json", encoding="utf-8")
        assert interactive.window_kept() == {CODE, DECIDE}
        assert memory.pinned_gb() == pytest.approx(32.8)
    finally:
        gateway_switch.stop_drain(node=interactive.WINDOW)
        interactive.keep_in_window(None)


def test_a_load_that_fits_now_takes_no_window(night, monkeypatch):
    monkeypatch.setattr(memory, "available_gb", lambda: 64.0)
    assert not screen_window.wanted(20.2, now=NOW)
