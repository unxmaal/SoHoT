"""A served model with no request past the day or night limit is given back, never one a running eval names (#1157)."""
import io
import json
import time

import pytest

from harness import idle_unload, knobs, mlx_server, router
from harness import memory_store as ms
from harness import watchdog as wd
from tests.test_watchdog import Fake, P

DAY = time.mktime((2026, 10, 12, 12, 0, 0, 0, 0, -1))
NIGHT = time.mktime((2026, 10, 12, 23, 30, 0, 0, 0, -1))
ORNITH = "Ornith-1.5-35B-Q4_K_M"
DISCOVER = "/bin/bash scripts/serve-discover.sh discover --loop"
SCREEN = "/usr/bin/python3 -m evals.run --modality code --candidates llamacpp:Qwopus"


class Served(Fake):
    """Ornith loaded on the router, asked last at `asked`; optionally a running eval naming `specs`."""

    def __init__(self, tmp_path, asked=None, in_flight=False, specs=None, progress=True, extra=(), **kw):
        procs, runs = [], []
        if specs is not None:
            procs = [P(236, 1, 236, 4000, DISCOVER), P(237, 236, 237, 600, SCREEN)]
            if progress:
                runs = [{"state": "running", "pid": 237, "done": 2, "total": 5, "started_at": 0,
                         "last_progress_at": 0, "_dir": str(tmp_path), "specs": specs}]
        super().__init__(tmp_path, procs=procs, discover=236 if specs is not None else None, progress=runs, **kw)
        self._served = [{"server": "router", "model": ORNITH, "in_flight": in_flight}, *extra]
        self._asked = {} if asked is None else {ORNITH: asked}

    def served(self):
        return list(self._served)

    def last_use(self, conn, since):
        return {m: at for m, at in self._asked.items() if at >= since}


def _seen(tmp_path, at):
    """A wake long before that saw Ornith loaded, so only its last request decides."""
    wd.observe(Served(tmp_path), None, at)


def _found(fake, now):
    world = wd.observe(fake, None, now)
    found, skipped = wd.judge(world)
    return [f for f in found if f.criterion == "idle_unload"], skipped


def test_a_lane_model_with_no_request_past_the_day_limit_is_given_back(tmp_path):
    limit = wd.IDLE_UNLOAD_DAY_S
    _seen(tmp_path, DAY - 86400)
    assert _found(Served(tmp_path, asked=DAY - limit + 1), DAY)[0] == []
    [f] = _found(Served(tmp_path, asked=DAY - limit), DAY)[0]
    assert f.evidence == {"server": "router", "model": ORNITH, "idle_s": round(limit), "limit_s": limit, "day": True}


def test_at_night_the_limit_is_the_router_s_own_sleep(tmp_path):
    night = float(knobs.KNOBS["serve_idle_unload_s"].default())
    assert wd.unload_after(NIGHT) == night > wd.IDLE_UNLOAD_DAY_S == wd.unload_after(DAY)
    _seen(tmp_path, NIGHT - 86400)
    assert _found(Served(tmp_path, asked=NIGHT - wd.IDLE_UNLOAD_DAY_S - 1), NIGHT)[0] == []
    assert _found(Served(tmp_path, asked=NIGHT - night + 1), NIGHT)[0] == []
    [f] = _found(Served(tmp_path, asked=NIGHT - night), NIGHT)[0]
    assert f.evidence["limit_s"] == night and f.evidence["day"] is False


def test_a_model_a_running_eval_names_is_pinned_and_its_clock_starts_when_the_run_ends(tmp_path):
    old = DAY - 10 * wd.IDLE_UNLOAD_DAY_S
    _seen(tmp_path, DAY - 86400)
    assert _found(Served(tmp_path, asked=old, specs={"o": f"llamacpp:{ORNITH}"}), DAY)[0] == []
    # The run is gone: the last wake that saw it named is when its idleness began.
    later = DAY + wd.IDLE_UNLOAD_DAY_S - 1
    assert _found(Served(tmp_path, asked=old), later)[0] == []
    assert len(_found(Served(tmp_path, asked=old), DAY + wd.IDLE_UNLOAD_DAY_S)[0]) == 1


def test_an_eval_with_no_progress_file_makes_nothing_idle(tmp_path):
    _seen(tmp_path, DAY - 86400)
    fake = Served(tmp_path, asked=DAY - 10 * wd.IDLE_UNLOAD_DAY_S, specs={}, progress=False)
    assert _found(fake, DAY)[0] == []
    assert _found(Served(tmp_path), DAY + wd.IDLE_UNLOAD_DAY_S - 1)[0] == []


def test_another_model_is_given_back_while_an_eval_runs(tmp_path):
    fake = Served(tmp_path, asked=DAY - 10 * wd.IDLE_UNLOAD_DAY_S, specs={"q": "llamacpp:Qwopus3.6-27B"})
    wd.observe(fake, None, DAY - 10 * wd.IDLE_UNLOAD_DAY_S)
    assert [f.subject.detail["model"] for f in _found(fake, DAY)[0]] == [ORNITH]


@pytest.mark.parametrize("in_flight", [True, None])
def test_a_request_in_flight_or_an_unknown_one_keeps_the_model(tmp_path, in_flight):
    wd.observe(Served(tmp_path), None, DAY - 10 * wd.IDLE_UNLOAD_DAY_S)
    assert _found(Served(tmp_path, in_flight=in_flight), DAY)[0] == []


def test_a_model_first_seen_now_waits_a_whole_limit(tmp_path):
    assert _found(Served(tmp_path), DAY)[0] == []
    assert _found(Served(tmp_path), DAY + wd.IDLE_UNLOAD_DAY_S - 1)[0] == []
    assert len(_found(Served(tmp_path), DAY + wd.IDLE_UNLOAD_DAY_S)[0]) == 1


def test_a_residency_that_ended_starts_over(tmp_path):
    wd.observe(Served(tmp_path), None, DAY - 10 * wd.IDLE_UNLOAD_DAY_S)
    gone = Served(tmp_path)
    gone._served = []
    wd.observe(gone, None, DAY - 1)
    assert _found(Served(tmp_path), DAY)[0] == []


def test_an_unreadable_server_is_a_gap_not_a_lost_wake(tmp_path):
    class Broken(Served):
        def served(self):
            raise OSError("router gone")
    found, skipped = _found(Broken(tmp_path), DAY)
    assert found == [] and "router gone" in skipped["idle_unload"]


def test_probe_and_smoke_requests_are_not_use(tmp_path):
    conn = ms.connect()
    try:
        rows = [(DAY - 50, "openai/" + ORNITH, "watchdog"), (DAY - 40, ORNITH, "smoke"),
                (DAY - 900, "openai/" + ORNITH, "work"), (DAY - 30, "openai/mlx-community/X-4bit", "eval"),
                (DAY - 5000, "openai/Old", "work")]
        conn.executemany("INSERT INTO gateway_requests (at, served, purpose) VALUES (?, ?, ?)", rows)
        conn.commit()
        assert wd.Probes().last_use(conn, DAY - 3600) == {ORNITH: DAY - 900, "mlx-community/X-4bit": DAY - 30}
        used = idle_unload.uses(conn, DAY - 3600)
        assert sorted(used) == [ORNITH, "mlx-community/X-4bit"] and used[ORNITH] == [(DAY - 900, DAY - 900)]
    finally:
        conn.close()
    assert wd.Probes().last_use(None, 0) == {}


def test_the_served_probe_reads_loaded_router_models_their_slots_and_a_non_boot_mlx_model(monkeypatch):
    models = {"data": [{"id": ORNITH, "status": {"value": "loaded"}}, {"id": "Asleep", "status": {"value": "sleeping"}},
                       {"id": "Busy", "status": {"value": "loaded"}}, {"id": "Shy", "status": {"value": "loaded"}}]}
    slots = {ORNITH: [{"is_processing": False}], "Busy": [{"is_processing": True}], "Shy": {}}

    def get(path, base=""):
        return models if path == "/models" else slots[path.split("model=")[1]]
    monkeypatch.setattr(router, "_get", get)
    monkeypatch.setattr(wd.Probes, "launchd_loaded", lambda self, s: s == "mlx")
    held = {"model": "mlx-community/Q3-30B", "boot": "mlx-community/Q7B", "in_flight": 0}
    monkeypatch.setattr(mlx_server, "activity", lambda base, timeout: held)
    assert wd.Probes().served() == [
        {"server": "router", "model": ORNITH, "in_flight": False}, {"server": "router", "model": "Busy", "in_flight": True},
        {"server": "router", "model": "Shy", "in_flight": None},
        {"server": "mlx", "model": "mlx-community/Q3-30B", "in_flight": False}]
    held.update(model="mlx-community/Q7B")
    assert [m["server"] for m in wd.Probes().served()] == ["router"] * 3
    held.update(model="mlx-community/Q3-30B", boot=None, in_flight=None)
    assert wd.Probes().served()[-1] == {"server": "mlx", "model": "mlx-community/Q3-30B", "in_flight": None}


def test_unload_gives_back_a_lane_s_own_model_past_the_eval_lock(monkeypatch):
    asked = []
    monkeypatch.setattr(router, "release", lambda stems, why, **kw: asked.append(
        ("router", stems, kw["keep"], kw["proven_idle"], why)) or stems)
    monkeypatch.setattr(mlx_server, "release", lambda model, why, **kw: asked.append(("mlx", model, kw["keep"])) or True)
    ev = {"server": "router", "model": ORNITH, "idle_s": 700, "limit_s": 600.0, "day": True}
    out = wd.Hands().do(wd.UNLOAD, wd.Finding("idle_unload", wd.Subject("model", f"router {ORNITH}", "t"), ev))
    ev2 = {**ev, "server": "mlx", "model": "mlx-community/Q3-30B"}
    wd.Hands().do(wd.UNLOAD, wd.Finding("idle_unload", wd.Subject("model", "mlx m", "t"), ev2))
    assert asked == [("router", [ORNITH], set(), True, "watchdog: no request for 700s, past 600s"),
                     ("mlx", "mlx-community/Q3-30B", set())]
    assert out == f"unloaded router {ORNITH}"


def test_a_wake_records_the_unload_and_one_that_does_not_take_is_notified(tmp_path):
    conn = ms.connect()
    done = []

    class Hands(wd.Hands):
        def do(self, action, f):
            done.append((f.criterion, action))
            return "ok"
    _seen(tmp_path, DAY - 86400)
    try:
        for i in range(4):
            wd.wake(conn, Served(tmp_path, asked=DAY - 3600), Hands(), act=True, now=DAY + i * 300, say=lambda *_: None)
        rows = [dict(r) for r in conn.execute("SELECT criterion, action, evidence FROM watchdog_actions")]
    finally:
        conn.close()
    assert done == [("idle_unload", wd.UNLOAD)] * 2 + [("idle_unload", wd.NOTIFY)] * 2
    assert json.loads(rows[0]["evidence"])["model"] == ORNITH


class _Handler:
    """mlx_lm's APIHandler, as far as serve_loaded touches it."""

    def __init__(self, path, provider, during=None):
        self.path, self.during, self.wfile = path, during, io.BytesIO()
        self.response_generator = type("G", (), {"model_provider": provider})()
        self.sent = []

    def send_response(self, code):
        self.sent.append(code)

    def send_header(self, *a):
        pass

    def end_headers(self):
        pass

    def do_GET(self):
        return "own"

    def do_POST(self):
        return self.during() if self.during else None


def test_the_mlx_wrapper_says_its_boot_model_and_the_requests_in_flight():
    class H(_Handler):
        pass
    provider = type("Prov", (), {"model_key": ("mlx-community/Q3-30B",), "_model_map": {},
                                 "cli_args": type("A", (), {"model": "mlx-community/Q7B"})()})()
    mlx_server.serve_loaded(H)

    def loaded():
        h = H(mlx_server.LOADED_PATH, provider)
        h.do_GET()
        return json.loads(h.wfile.getvalue())
    assert loaded() == {"model": "mlx-community/Q3-30B", "boot": "mlx-community/Q7B", "in_flight": 0}
    seen = []
    H("/v1/chat/completions", provider, during=lambda: seen.append(loaded()["in_flight"])).do_POST()
    assert seen == [1] and loaded()["in_flight"] == 0
    with pytest.raises(RuntimeError):
        H("/v1/chat/completions", provider, during=lambda: (_ for _ in ()).throw(RuntimeError("x"))).do_POST()
    assert loaded()["in_flight"] == 0
    assert H("/other", provider).do_GET() == "own"


def test_activity_reads_old_and_new_wrappers():
    def opener(body):
        class R(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False
        return lambda url, timeout: R(json.dumps(body).encode())
    assert mlx_server.activity("http://x", 1, opener({"model": "m"})) == {"model": "m", "boot": None, "in_flight": None}
    got = mlx_server.activity("http://x", 1, opener({"model": "m", "boot": "b", "in_flight": 2}))
    assert got == {"model": "m", "boot": "b", "in_flight": 2}

    def refused(url, timeout):
        raise OSError("refused")
    assert mlx_server.activity("http://x", 1, refused) is None


LOG = """\
0.01.000.000 I srv          load: spawning server instance with name=Ornith-1.5-35B-Q4_K_M on port 62170
[62170] 0.29.514.031 I srv  llama_server: model loaded
0.02.000.000 I srv          load: spawning server instance with name=imajev-4b-Q8_0 on port 64817
[64817] 1.04.356.714 I srv  llama_server: model loaded
[64817] 1.05.000.000 I srv  llama_server: model loaded
[99999] 0.01.000.000 I srv  llama_server: model loaded
"""


def test_cold_load_seconds_are_read_off_each_child_s_own_uptime():
    got = idle_unload.load_seconds(LOG.splitlines())
    assert got == {ORNITH: [29.514], "imajev-4b-Q8_0": [64.356]}
    assert idle_unload.summary([1.0, 2.0, 30.0]) == {"n": 3, "median_s": 2.0, "p90_s": 30.0, "max_s": 30.0}
    assert idle_unload.summary([1.0, 9.0])["p90_s"] == 9.0


def test_a_limit_costs_a_load_per_gap_past_it_and_idle_hours_up_to_it():
    spans = [(0.0, 10.0), (100.0, 110.0), (2000.0, 2010.0)]
    assert idle_unload.cost(spans, 600, days=1) == {"loads_per_day": 2, "idle_h_per_day": round((90 + 600 + 600) / 3600, 2)}
    assert idle_unload.cost(spans, 3600, days=1) == {"loads_per_day": 1,
                                                     "idle_h_per_day": round((90 + 1890 + 3600) / 3600, 2)}
    assert idle_unload.cost([], 600, days=1) == {"loads_per_day": 0, "idle_h_per_day": 0.0}


def test_a_new_request_starts_a_new_spell_that_is_unloaded_afresh(tmp_path):
    _seen(tmp_path, DAY - 86400)
    [first] = _found(Served(tmp_path, asked=DAY - 3000), DAY)[0]
    [again] = _found(Served(tmp_path, asked=DAY - 3000), DAY + 300)[0]
    [fresh] = _found(Served(tmp_path, asked=DAY + 400), DAY + 400 + wd.IDLE_UNLOAD_DAY_S)[0]
    assert first.subject.key == again.subject.key != fresh.subject.key
    assert wd.fingerprint(first) == wd.fingerprint(fresh)
