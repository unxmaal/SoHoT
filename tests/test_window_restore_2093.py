"""A screen window's restore loads each released stem back and sees it loaded before it says restored; smoke reloads a missing pin. #2093."""
from __future__ import annotations

from pathlib import Path

import pytest

from harness import containers, interactive, memory, monitor, screen_window

REPO = Path(__file__).resolve().parents[1]
URL = "http://127.0.0.1:18083"
GIB = 1024 ** 3
CODE = "Ornith-1.5-35B-Q4_K_M"
DECIDE = "imajev-4b-Q8_0"
LAG_S = 0.5


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


class LaggingRouter:
    """llama.cpp's router: an unload answers before its instance stops, a load of a stem still loaded does nothing,
    and nothing loads on its own."""

    def __init__(self, clock, refuse=(), lag_s=LAG_S):
        self.clock, self.refuse, self.lag_s = clock, set(refuse), lag_s
        self.status = {CODE: "loaded", DECIDE: "loaded"}
        self.stopping, self.calls = {}, []

    def get(self, path):
        if path.startswith("/slots"):
            return []
        for stem, at in list(self.stopping.items()):
            if self.clock() >= at + self.lag_s:
                self.status[stem] = "unloaded"
                del self.stopping[stem]
        return {"data": [{"id": k, "status": {"value": v}} for k, v in self.status.items()]}

    def post(self, path, body):
        stem = body["model"]
        self.calls.append((path, stem))
        if path == "/models/unload":
            self.stopping[stem] = self.clock()
        elif stem in self.refuse:
            raise OSError(f"{stem} failed to load")
        elif self.status[stem] not in ("loaded", "loading"):
            self.status[stem] = "loaded"


@pytest.fixture
def planted(monkeypatch):
    entry = lambda stem, gib: {"stem": stem, "bytes": int(gib * GIB), "served": f"llamacpp:{stem}", "ctx": 32768}  # noqa: E731
    interactive.write({"url": URL, "bytes": int(32.8 * GIB),
                       "lanes": {"code": entry(CODE, 27.7), "decide": entry(DECIDE, 5.1)}})
    monkeypatch.setattr(memory, "ceiling_gb", lambda: 77.8)
    monkeypatch.setattr(memory, "measured_reserve_gb", lambda: 18.0)
    monkeypatch.setattr(memory, "available_gb", lambda: 64.0)
    monkeypatch.setattr(containers, "vm_gb", lambda: 3.8)
    monkeypatch.setattr(interactive, "key", lambda environ=None: "")
    monkeypatch.setattr(interactive, "_served", lambda config=None: {})
    alerts = []
    monkeypatch.setattr(monitor, "alert", lambda kind, environ=None, **kw: alerts.append((kind, dict(environ))) or {})
    return alerts


def _open(server, clock, said):
    return screen_window.opened(900.0, "a screen window for Qwen/Qwen-Image-2.1", get=server.get, post=server.post,
                                sleep=clock.sleep, clock=clock, say=said.append)


def test_an_unload_that_lands_after_its_answer_is_waited_for_and_each_stem_is_loaded_back(planted):
    clock, said = Clock(), []
    server = LaggingRouter(clock)
    with _open(server, clock, said) as released:
        assert released == [CODE, DECIDE]
        assert set(server.status.values()) == {"unloaded"}, "the window opens only once the router shows them gone"
    assert server.status == {CODE: "loaded", DECIDE: "loaded"}, "the pinned set is loaded, not claimed"
    assert ("/models/load", CODE) in server.calls and ("/models/load", DECIDE) in server.calls
    assert said[-1].strip() == f"window: restored {CODE}, {DECIDE}" and planted == []



@pytest.mark.gauntlet("a-wait-with-no-deadline-owner-or-end-state", site="harness/screen_window.py:_resident")
def test_an_unload_that_lands_after_the_window_gave_up_on_it_is_still_loaded_back_before_restored(planted):
    clock, said = Clock(), []
    server = LaggingRouter(clock, lag_s=screen_window.DRAIN_S + 30.0)
    with pytest.raises(screen_window.Refused, match="stayed resident"):
        with _open(server, clock, said):
            pytest.fail("the window opened over a resident set")
    assert server.status == {CODE: "loaded", DECIDE: "loaded"} and not server.stopping
    assert said[-1].strip() == f"window: restored {CODE}, {DECIDE}"

@pytest.mark.gauntlet("a-wait-with-no-deadline-owner-or-end-state", site="harness/screen_window.py:restore")
def test_a_stem_that_does_not_load_back_is_named_in_a_warn_and_an_alert_and_never_reported_restored(planted):
    clock, said = Clock(), []
    server = LaggingRouter(clock, refuse={CODE})
    with pytest.raises(screen_window.Refused, match=f"{CODE} did not load back"):
        with _open(server, clock, said):
            pass
    assert server.status == {CODE: "unloaded", DECIDE: "loaded"}
    assert not any("window: restored" in m for m in said)
    assert any(m.strip().startswith("WARN") and CODE in m and DECIDE not in m.split(":", 2)[-1] for m in said)
    assert [(k, e["MONIT_SERVICE"]) for k, e in planted] == [("service", "interactive")]
    assert CODE in planted[0][1]["MONIT_DESCRIPTION"]
    assert not interactive.windowed()


@pytest.mark.gauntlet("a-wait-with-no-deadline-owner-or-end-state", site="harness/interactive.py:repair")
@pytest.mark.gauntlet("one-default-tuned-for-one-member-applied-to-all", site="harness/interactive.py:repair(wait_s)")
def test_repair_loads_a_pinned_stem_the_server_is_up_without_and_waits_for_it(planted):
    clock = Clock()
    server = LaggingRouter(clock)
    server.status[CODE] = "unloaded"
    assert interactive.health(get=server.get)["missing"] == [CODE]
    assert interactive.repair(get=server.get, post=server.post, sleep=clock.sleep, clock=clock) == [CODE]
    assert interactive.health(get=server.get)["missing"] == []
    server.refuse, server.status[CODE] = {CODE}, "unloaded"
    assert interactive.repair(get=server.get, post=server.post, sleep=clock.sleep, clock=clock, wait_s=30.0) == []
    assert clock.t >= 30.0, "a stem that never loads is waited for only until the deadline"


def test_repair_leaves_a_window_s_released_set_alone(planted, monkeypatch):
    clock = Clock()
    server = LaggingRouter(clock)
    server.status[CODE] = "unloaded"
    monkeypatch.setattr(interactive, "windowed", lambda now=None: True)
    assert interactive.repair(get=server.get, post=server.post, sleep=clock.sleep, clock=clock) == []
    assert server.calls == []


def test_smoke_repairs_the_pinned_set_before_it_judges_it():
    text = (REPO / "scripts" / "smoke.sh").read_text(encoding="utf-8")
    line = next(ln for ln in text.splitlines() if ln.strip().startswith('PINNED="$('))
    assert "python -m harness.interactive health --repair" in line
