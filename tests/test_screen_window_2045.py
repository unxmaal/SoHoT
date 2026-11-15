"""A screen that needs more than the free share takes a window: the pinned set released, interactive work to the cloud, the set restored. #2045."""
from __future__ import annotations

import asyncio
import importlib
import importlib.util
from pathlib import Path

import pytest

from harness import completion, containers, delegate, gateway_switch, interactive, memory, routes, screen_window
from harness.watchdog import Finding  # noqa: F401 - interactive.finding imports it

REPO = Path(__file__).resolve().parents[1]
URL = "http://127.0.0.1:18083"
GIB = 1024 ** 3
CODE = "Ornith-1.5-35B-Q4_K_M"
DECIDE = "imajev-4b-Q8_0"
REAL_STANDING = memory.standing_gb


class Server:
    """The interactive server's router: /models, /slots and load/unload, in memory."""

    def __init__(self, loads=True, busy=0):
        self.status = {CODE: "loaded", DECIDE: "loaded"}
        self.loads, self.busy, self.calls = loads, busy, []

    def get(self, path):
        if path.startswith("/slots"):
            return [{"is_processing": True}] * self.busy
        return {"data": [{"id": k, "status": {"value": v}} for k, v in self.status.items()]}

    def post(self, path, body):
        self.calls.append((path, body["model"]))
        if path == "/models/unload":
            self.status[body["model"]] = "unloaded"
        elif self.loads:
            self.status[body["model"]] = "loaded"


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


@pytest.fixture
def planted(monkeypatch):
    """The Studio of #2045: 77.8 GB ceiling, 18.0 reserve, 32.8 GiB pinned, 3.8 GiB Docker VM, so 23.2 GiB is the most a load gets."""
    entry = lambda stem, gib: {"stem": stem, "bytes": int(gib * GIB), "served": f"llamacpp:{stem}", "ctx": 32768}  # noqa: E731
    interactive.write({"url": URL, "bytes": int(32.8 * GIB),
                       "lanes": {"code": entry(CODE, 27.7), "decide": entry(DECIDE, 5.1)}})
    monkeypatch.setattr(memory, "ceiling_gb", lambda: 77.8)
    monkeypatch.setattr(memory, "measured_reserve_gb", lambda: 18.0)
    monkeypatch.setattr(containers, "vm_gb", lambda: 3.8)
    monkeypatch.setattr(interactive, "key", lambda environ=None: "")
    monkeypatch.setattr(interactive, "_served", lambda config=None: {})
    monkeypatch.setattr(memory, "standing_gb", REAL_STANDING)


def _open(server, clock, hold_s=900.0):
    return screen_window.opened(hold_s, "a screen window for gemma-4-31B", get=server.get, post=server.post,
                                sleep=clock.sleep, clock=clock, say=lambda m: None)


def test_a_25_gib_candidate_is_held_back_by_the_pinned_set_and_a_window_would_let_it_load(planted):
    assert memory.standing_gb() == pytest.approx(23.2)
    assert memory.held_back(25.0)
    assert screen_window.wanted(25.0)
    assert not screen_window.wanted(20.0), "a candidate that fits beside the pinned set needs no window"
    assert not screen_window.wanted(60.0), "releasing 32.8 GiB cannot fit 60 GiB, so no window is taken for it"


def test_the_window_releases_the_pinned_set_serves_the_lane_from_the_cloud_and_restores_it(planted):
    server, clock = Server(), Clock()
    with _open(server, clock) as released:
        assert released == [CODE, DECIDE]
        assert set(server.status.values()) == {"unloaded"}
        assert interactive.windowed()
        assert memory.pinned_gb() == 0.0 and not memory.held_back(25.0), "the screen is admitted in the window"
        spec, where = interactive.route("code", get=server.get)
        assert (spec, where.model, where.base) == (routes.CLOUD, routes.CLOUD, completion.gateway_url())
        assert interactive.finding(type("W", (), {"interactive": {"planned": True, "up": True,
                                                                  "missing": [CODE]}})()) == [], \
            "the watchdog does not restart the interactive unit for a window's released set"
    assert set(server.status.values()) == {"loaded"}
    assert not interactive.windowed()
    assert memory.pinned_gb() == pytest.approx(32.8)


def test_a_screen_that_raises_still_gets_the_pinned_set_back(planted):
    server, clock = Server(), Clock()
    with pytest.raises(OSError):
        with _open(server, clock):
            raise OSError("the screen could not start")
    assert set(server.status.values()) == {"loaded"} and not interactive.windowed()


def test_the_window_is_refused_when_the_pinned_set_is_not_all_loaded_before_it(planted):
    server, clock = Server(), Clock()
    server.status[DECIDE] = "unloaded"
    with pytest.raises(screen_window.Refused, match="restore could not be confirmed"):
        with _open(server, clock):
            pytest.fail("the window opened")
    assert not interactive.windowed() and ("/models/unload", CODE) not in server.calls


def test_a_restore_that_cannot_be_confirmed_refuses_the_window_and_lifts_the_flag(planted):
    server, clock = Server(loads=False), Clock()
    with pytest.raises(screen_window.Refused, match="did not load back"):
        with _open(server, clock):
            pass
    assert clock.t >= interactive.WARM_WAIT_S
    assert not interactive.windowed(), "the watchdog's interactive_down then restarts the unit"


def test_an_interactive_request_in_flight_is_never_cut_the_window_is_refused_after_the_drain(planted):
    server, clock = Server(busy=1), Clock()
    with pytest.raises(screen_window.Refused, match="in flight"):
        with _open(server, clock):
            pytest.fail("the window opened over a request in flight")
    assert not any(p == "/models/unload" for p, _ in server.calls)
    assert clock.t >= screen_window.DRAIN_S and not interactive.windowed()


def test_the_drain_flag_expires_past_the_screen_deadline_so_a_dead_screen_cannot_hold_it(planted):
    server, clock = Server(), Clock()
    with _open(server, clock, hold_s=900.0):
        import time
        end = time.time() + screen_window.DRAIN_S + 900.0 + interactive.WARM_WAIT_S
        assert interactive.windowed(now=end - 5) and not interactive.windowed(now=end + 5)


def test_a_cloud_delegation_in_the_window_never_waits_on_the_screens_lock(planted, monkeypatch):
    monkeypatch.setattr(delegate, "held_now", lambda who="delegate": pytest.fail("asked the machine lock"))
    where = interactive.serving.Route(completion.gateway_url(), routes.CLOUD, {}, {})
    assert delegate._gate(where) is True


def _served():
    spec = importlib.util.spec_from_file_location("served_model_2045", REPO / "gateway" / "served_model.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_gateway_sends_a_lane_alias_the_interactive_server_answers_to_the_cloud_in_the_window(
        planted, tmp_path, monkeypatch):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(f"""model_list:
  - model_name: sohot-code
    litellm_params:
      model: openai/{CODE}
      api_base: {URL}/v1
      api_key: not-needed
  - model_name: eval-4b
    litellm_params:
      model: openai/eval-4b
      api_base: http://127.0.0.1:8082/v1
      api_key: not-needed
  - model_name: {routes.CLOUD}
    litellm_params:
      model: anthropic/claude
""", encoding="utf-8")
    monkeypatch.setenv("GATEWAY_CONFIG", str(cfg))
    served = _served()

    def send(model):
        data = {"model": model}
        return asyncio.run(served.proxy_handler_instance.async_pre_call_hook(None, None, data, "acompletion"))["model"]
    assert send("sohot-code") == "sohot-code"
    gateway_switch.start_drain(node=interactive.WINDOW)
    assert send("sohot-code") == routes.CLOUD, "an interactive request in the window is answered, not dropped"
    assert send("eval-4b") == "eval-4b", "the eval router's names are not the window's"
    gateway_switch.stop_drain(node=interactive.WINDOW)
    assert send("sohot-code") == "sohot-code"


def test_a_planted_25_gib_candidate_with_32_8_gib_pinned_is_screened_in_a_window_and_the_set_is_back(
        planted, monkeypatch):
    import contextlib
    import functools
    import subprocess

    from harness import candidates, heartbeat, router, screen
    from harness import memory_store as ms
    from harness.commands import measure as measure_cmd
    from harness.commands import screen as screen_cmd
    server, clock, ran, decided = Server(), Clock(), [], []
    monkeypatch.setattr(memory, "need_gb", lambda *a, **k: 25.0)
    monkeypatch.setattr(memory, "available_gb", lambda: 70.0)
    monkeypatch.setattr(memory, "total_gb", lambda: 96.0)
    monkeypatch.setattr(screen_window, "opened", functools.partial(
        screen_window.opened, get=server.get, post=server.post, sleep=clock.sleep, clock=clock, say=lambda m: None))
    monkeypatch.setattr(screen, "deadline_s", lambda candidate: 900.0)
    monkeypatch.setattr(heartbeat, "held", lambda *a, **k: contextlib.nullcontext())
    for name, value in (("known_killer", None), ("_fetched", ("", False)), ("snapshot_gap", "")):
        monkeypatch.setattr(screen_cmd, name, lambda *a, _v=value, **k: _v)
    monkeypatch.setattr(screen_cmd, "harness_stuck", lambda conn, name, verdict: verdict)
    monkeypatch.setattr(screen_cmd, "verdict_of_run", lambda *a, **k: screen.Verdict("screened", "ran", ""))
    monkeypatch.setattr(measure_cmd, "_receipt_at", lambda out, conn=None: {})
    monkeypatch.setattr(candidates, "from_receipt", lambda *a, **k: None)
    monkeypatch.setattr(candidates, "ensure", lambda *a, **k: 1)
    monkeypatch.setattr(candidates, "key_for", lambda *a, **k: "")
    monkeypatch.setattr(ms, "decide_or_skip", lambda store, name, outcome, **k: decided.append(outcome))
    monkeypatch.setattr(router, "release_spec", lambda *a, **k: [])

    def run(argv, **kw):
        ran.append((memory.pinned_gb(), set(server.status.values()), interactive.windowed()))
        return subprocess.CompletedProcess(argv, 0, "", "")
    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(screen, "argv", lambda r, outdir=None: ["true"])
    for mod in ("mlx_server", "audio_models"):
        monkeypatch.setattr(importlib.import_module(f"harness.{mod}"), "release_spec", lambda *a, **k: [])
    row = {"name": "google/gemma-4-31B-it", "candidate": "hf-text:google/gemma-4-31B-it", "modality": "text"}
    assert screen_cmd._screen_one(None, None, row) == (True, "screened", None)
    assert ran == [(0.0, {"unloaded"}, True)], "the screen ran with the pinned set released"
    assert decided == ["screened"]
    assert set(server.status.values()) == {"loaded"} and not interactive.windowed()
    assert memory.pinned_gb() == pytest.approx(32.8)
