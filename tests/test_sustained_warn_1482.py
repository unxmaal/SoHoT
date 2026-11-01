"""Sustained memory warn gives back served models nothing uses, then pauses once; no load past the headroom (#1482)."""
import argparse
import json

import pytest

from evals import watch
from evals.core import Case
from evals.runners.base import RunnerError
from evals.runners.text import CompletionRunner
from harness import completion, cuts, memory, mlx_server, reasons, router, serving
from harness import memory_store as ms
from harness import watchdog as wd
from harness.commands import loop as loop_cmd
from harness.commands import measure as measure_cmd
from tests.test_resume_813 import _sweep
from tests.test_watchdog import NIGHT, Fake, P, Pressure

DISCOVER = "/bin/bash scripts/serve-discover.sh discover --loop"
REPO = "/usr/bin/python3 -m evals.run --modality repo --candidates llamacpp:Ornith-1.5-35B-Q4_K_M,Qwen/Qwen3-0.6B"
ORNITH, SMALL, SPARE = "Ornith-1.5-35B-Q4_K_M", "Qwen/Qwen3-0.6B", "Qwen2.5-7B-Instruct-Q4_K_M"
WARN = Pressure(level=2, alarming=True, swapouts=0)


class Repo(Fake):
    """The 2026-10-31 night: the repo measure pairs Ornith on the router with Qwen3-0.6B on mlx, both in use."""

    def __init__(self, tmp_path, pressure=WARN, spare=False):
        progress = {"state": "running", "pid": 237, "done": 9, "total": 144, "started_at": NIGHT - 1800,
                    "last_progress_at": NIGHT - 30, "_dir": str(tmp_path), "pause_file": str(tmp_path / "pause"),
                    "specs": {"o": f"llamacpp:{ORNITH}", "q": SMALL}}
        super().__init__(tmp_path, procs=[P(236, 1, 236, 4000, DISCOVER), P(237, 236, 237, 1800, REPO)],
                         discover=236, progress=[progress], pressure=pressure)
        self._held = SMALL
        self._served = [{"server": "router", "model": ORNITH, "in_flight": True},
                        {"server": "mlx", "model": SMALL, "in_flight": True}]
        if spare:
            self._served.append({"server": "router", "model": SPARE, "in_flight": False})

    def mlx_held(self):
        return self._held

    def protected(self):
        return {ORNITH}

    def served(self):
        return list(self._served)

    def last_use(self, conn, since):
        return {}


class Hands(wd.Hands):
    def __init__(self):
        super().__init__(run=None, environ={})
        self.done = []

    def unload(self, f):
        self.done.append((f.criterion, wd.UNLOAD))
        return "ok"

    def notify(self, f):
        self.done.append((f.criterion, wd.NOTIFY))
        return f"{wd.NOTIFIED}: {f.criterion}"

    def pause(self, f):
        self.done.append((f.criterion, wd.PAUSE))
        return super().pause(f)


def _wakes(tmp_path, pressures, spare=False, late=(), fake=None):
    conn, hands = ms.connect(), Hands()
    try:
        for i, p in enumerate(pressures):
            at = NIGHT + i * 300 + (900 if i in late else 0)
            wd.wake(conn, fake or Repo(tmp_path, p, spare=spare), hands, act=True, now=at, say=lambda *_: None)
        rows = [dict(r) for r in conn.execute("SELECT criterion, action, evidence, outcome FROM watchdog_actions "
                                              "ORDER BY id")]
    finally:
        conn.close()
    return hands.done, rows


def _acts(rows):
    return [(r["criterion"], r["action"]) for r in rows]


def test_three_warn_samples_with_a_served_model_nothing_uses_give_it_back(tmp_path):
    done, rows = _wakes(tmp_path, [WARN] * 3, spare=True)
    assert _acts(rows) == [("memory_warn", wd.NOTIFY)] * 2 + [("memory_sustained", wd.UNLOAD)]
    assert done[-1] == ("memory_sustained", wd.UNLOAD)
    ev = json.loads(rows[-1]["evidence"])
    assert ev["spare"] == [{"server": "router", "model": SPARE}]
    assert ev["samples"] == 3 and ev["limit_samples"] == wd.WARN_SUSTAINED


def test_with_nothing_to_give_back_the_sweep_pauses_with_its_reason_and_one_push(tmp_path):
    done, rows = _wakes(tmp_path, [WARN] * 5)
    assert _acts(rows) == [("memory_warn", wd.NOTIFY)] * 2 + [("memory_stuck", wd.PAUSE)] * 2 + [
        ("memory_stuck", wd.NOTIFY)]
    # The escalation's notice is held: the first pause already put it on the desktop.
    assert [d for d in done if d[0] == "memory_stuck"] == [
        ("memory_stuck", wd.PAUSE), ("memory_stuck", wd.NOTIFY), ("memory_stuck", wd.PAUSE)]
    assert watch.pause_reason(tmp_path) == "memory_stuck"
    assert "memory_stuck" in measure_cmd.MEMORY_PAUSES
    assert sum(wd.NOTIFIED in r["outcome"] for r in rows if r["criterion"] == "memory_stuck") == 1
    # The no-op "nothing idle to unload" stops repeating once the warn is sustained.
    assert [r["criterion"] for r in rows[2:]] == ["memory_stuck"] * 3


def test_a_wake_without_warn_starts_the_count_again(tmp_path):
    _, rows = _wakes(tmp_path, [WARN, WARN, Pressure(), WARN, WARN], spare=True)
    assert [c for c, _ in _acts(rows)] == ["memory_warn"] * 4


def test_a_missed_wake_breaks_the_run(tmp_path):
    _, rows = _wakes(tmp_path, [WARN] * 3, spare=True, late=(2,))
    assert [c for c, _ in _acts(rows)] == ["memory_warn"] * 3


def test_an_idle_model_is_still_the_first_thing_a_warn_gives_back(tmp_path):
    fake = Repo(tmp_path, spare=True)
    fake._held = "Edge0/Edge0-35B-A3B-preview"
    _, rows = _wakes(tmp_path, [WARN] * 3, fake=fake)
    assert [c for c, _ in _acts(rows)] == ["memory_warn"] * 3


def test_a_model_with_a_request_in_flight_or_unknown_is_not_spare(tmp_path):
    fake = Repo(tmp_path, spare=True)
    fake._served += [{"server": "router", "model": "Busy-4B", "in_flight": True},
                     {"server": "router", "model": "Unread-4B", "in_flight": None}]
    assert wd.spare(wd.observe(fake, None, NIGHT)) == [{"server": "router", "model": SPARE}]


def test_a_sustained_warn_gives_back_a_lane_model_too(monkeypatch):
    asked = []
    monkeypatch.setattr(router, "release", lambda stems, why, **kw: asked.append((stems, kw.get("keep"))) or stems)
    monkeypatch.setattr(mlx_server, "release", lambda model, why, **kw: asked.append((model, kw.get("keep"))) or True)
    f = wd.Finding("memory_sustained", wd.Subject("discover", "discover pid 236", "t"),
                   {"samples": 3, "spare": [{"server": "router", "model": SPARE}, {"server": "mlx", "model": "m"}]})
    assert wd.Hands().do(wd.UNLOAD, f) == f"unloaded router {SPARE}; unloaded mlx m"
    assert asked == [([SPARE], set()), ("m", set())]


def test_the_sustained_warn_records_its_knob(tmp_path, monkeypatch):
    got = []
    monkeypatch.setattr(cuts, "cut", lambda knob, what, **kw: got.append(knob))
    _wakes(tmp_path, [WARN] * 3)
    assert "watchdog_warn_sustained" in got


def test_the_measure_loop_takes_no_measurement_while_headroom_is_negative(monkeypatch):
    started, got = [], []
    monkeypatch.setattr(measure_cmd, "_measure_and_adopt", lambda a, row, sweep: started.append(row["name"]) or 0)
    monkeypatch.setattr(loop_cmd, "_gated", lambda row, want: "")
    monkeypatch.setattr(cuts, "cut", lambda knob, what, **kw: got.append((knob, kw.get("dropped"))))
    sweep = _sweep()
    rows = [{"name": SMALL, "lane": "repo"}, {"name": "b", "lane": "code"}]
    loop_cmd._measure_all(argparse.Namespace(lane=""), rows, sweep, [], headroom=lambda: -2.7)
    assert started == []
    assert sweep.waiting == 2 and "only -2.7 GB is safely available" in sweep.stopped
    assert ("min_headroom_gb", 2) in got
    loop_cmd._measure_all(argparse.Namespace(lane=""), rows, _sweep(), [], headroom=lambda: 0.5)
    assert started == [SMALL, "b"]


def _runner(monkeypatch, room=50.0, per=114688, screening=False):
    sent, got = [], []
    monkeypatch.setattr(completion, "complete_full", lambda *a, **kw: sent.append(kw) or None)
    monkeypatch.setattr(memory, "mlx_kv_bytes_per_token", lambda repo: per)
    monkeypatch.setattr(cuts, "cut", lambda knob, what, **kw: got.append(knob))
    r = CompletionRunner(serving.MLX_URL, SMALL, max_tokens=1000)
    r.headroom = lambda: room
    r.screening = screening
    return r, sent, got


def _case(chars):
    return Case(id="c1", modality="code", prompt="x " * (chars // 2))


def test_a_prompt_past_mlx_request_ctx_records_a_cut_and_is_not_sent(monkeypatch):
    r, sent, got = _runner(monkeypatch)
    row = r.run(_case(serving.MLX_REQUEST_CTX * 4))
    assert sent == []
    assert row.failure_class == reasons.CONTEXT_EXCEEDED
    assert row.limit == f"mlx_request_ctx>{serving.MLX_REQUEST_CTX}"
    assert got == ["mlx_request_ctx"]


def test_a_case_whose_kv_would_spend_the_headroom_is_deferred_not_run(monkeypatch):
    r, sent, got = _runner(monkeypatch, room=1.0)
    with pytest.raises(watch.Deferred) as e:
        r.run(_case(60000))
    assert sent == [] and got == ["min_headroom_gb"]
    assert e.value.why.startswith("paused on request") and e.value.reason == watch.MEMORY_HEADROOM
    assert watch.MEMORY_HEADROOM in measure_cmd.MEMORY_PAUSES


def test_a_screen_case_that_would_spend_the_headroom_is_a_row_that_never_ran(monkeypatch):
    r, sent, _ = _runner(monkeypatch, room=1.0, screening=True)
    row = r.run(_case(60000))
    assert sent == [] and row.failure_class == reasons.MEMORY_DEFERRED
    assert reasons.MEMORY_DEFERRED in reasons.NEVER_RAN
    assert reasons.CLASSES[reasons.MEMORY_DEFERRED] == ("queued", reasons.MEMORY)


def test_a_case_that_fits_is_sent(monkeypatch):
    r, sent, got = _runner(monkeypatch, room=50.0)
    with pytest.raises((RunnerError, AttributeError, TypeError)):
        r.run(_case(6000))
    assert len(sent) == 1 and got == []


def test_a_runner_off_mlx_is_not_checked(monkeypatch):
    r, sent, got = _runner(monkeypatch, room=-5.0)
    r.gateway = serving.LLAMACPP_URL
    with pytest.raises((RunnerError, AttributeError, TypeError)):
        r.run(_case(serving.MLX_REQUEST_CTX * 4))
    assert len(sent) == 1 and got == []
