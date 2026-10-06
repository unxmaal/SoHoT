"""#483: an adoption re-points sohot-<lane> without cutting off a request in flight."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
import yaml

from harness import adopt, exclusive, gateway, gateway_switch as gs
from harness import memory_store as ms

STEM = "Ornith-1.5-35B-Q4_K_M"
MLX = "http://127.0.0.1:8081"
CONFIG = {"model_list": [
    {"model_name": "q3-4b", "litellm_params": {
        "model": "openai/mlx-community/Qwen3-4B-Instruct-2507-4bit",
        "api_base": f"{MLX}/v1", "api_key": "not-needed"}},
    {"model_name": "local-large", "litellm_params": {
        "model": "openai/mlx-community/Qwen2.5-7B-Instruct-4bit",
        "api_base": f"{MLX}/v1", "api_key": "not-needed"}},
]}


class FakeGateway:
    """LiteLLM's /health/backlog on port 0: the probe counts itself, as the middleware does."""

    def __init__(self, status=200):
        self.busy = 0
        self.status = status
        self.calls = []
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                fake.calls.append((self.path, dict(self.headers)))
                body = json.dumps({"in_flight_requests": fake.busy + 1}).encode()
                self.send_response(fake.status if self.path == "/health/backlog" else 404)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def gw():
    fake = FakeGateway()
    yield fake
    fake.close()


class Clock:
    """Time that moves only when the waiter sleeps, so no test races a wall clock."""

    def __init__(self, script=None, fake=None):
        self.t = 1000.0
        self.script = list(script or [])
        self.fake = fake

    def now(self):
        return self.t

    def sleep(self, s):
        self.t += s
        if self.fake is not None and self.script:
            self.fake.busy = self.script.pop(0)


@pytest.fixture(autouse=True)
def config(tmp_path, monkeypatch):
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(CONFIG), encoding="utf-8")
    monkeypatch.setenv(gateway.ENV_VAR, str(path))
    monkeypatch.delenv("LLAMACPP_PORT", raising=False)
    monkeypatch.delenv(gs.KEY_ENV, raising=False)
    return path


def adopt_for(lane, spec):
    conn = ms.connect()
    try:
        adopt.record(conn, adopt.Verdict(lane, "q3-4b", spec, True, "won",
                                         adopt.BY_HAND))
    finally:
        conn.close()


# ---- observing in-flight requests ----------------------------------------------

def test_in_flight_does_not_count_the_probe_itself(gw):
    assert gs.in_flight(gw.base) == 0
    gw.busy = 2
    assert gs.in_flight(gw.base) == 2


def test_a_gateway_that_is_not_listening_has_nothing_in_flight():
    assert gs.in_flight("http://127.0.0.1:9") == 0


def test_a_gateway_that_will_not_say_is_unobservable():
    fake = FakeGateway(status=401)
    try:
        assert gs.in_flight(fake.base) is None
    finally:
        fake.close()


def test_the_probe_sends_the_gateway_key_when_one_is_set(gw, monkeypatch):
    gs.in_flight(gw.base)
    assert "Authorization" not in gw.calls[-1][1]
    monkeypatch.setenv(gs.KEY_ENV, "sk-test")
    gs.in_flight(gw.base)
    assert gw.calls[-1][1]["Authorization"] == "Bearer sk-test"


# ---- waiting for quiet -----------------------------------------------------------

def test_the_restart_waits_until_the_gateway_has_been_quiet_for_the_window(gw):
    gw.busy = 1
    clock = Clock([1, 1, 0, 1, 0, 0, 0, 0, 0, 0], gw)
    restarts = []
    got = gs.wait_then_restart(gw.base, lambda: restarts.append(clock.now()),
                               idle_s=3, max_wait_s=600, poll_s=1,
                               clock=clock.now, sleep=clock.sleep)
    assert restarts and got["how"] == "idle"
    # Busy until t+4, quiet from t+5: the restart is the first poll 3 s after that.
    assert restarts == [1000.0 + 5 + 3]
    assert got["in_flight"] == 0


def test_a_gateway_that_is_never_quiet_restarts_at_the_max_wait(gw):
    gw.busy = 1
    clock = Clock()
    restarts = []
    got = gs.wait_then_restart(gw.base, lambda: restarts.append(clock.now()),
                               idle_s=3, max_wait_s=20, poll_s=1,
                               clock=clock.now, sleep=clock.sleep)
    assert got["how"] == "forced" and got["in_flight"] == 1
    assert restarts == [1020.0]


def test_an_unobservable_gateway_is_never_restarted_early():
    fake = FakeGateway(status=401)
    clock = Clock()
    restarts = []
    try:
        got = gs.wait_then_restart(fake.base, lambda: restarts.append(clock.now()),
                                   idle_s=3, max_wait_s=20, poll_s=1,
                                   clock=clock.now, sleep=clock.sleep)
    finally:
        fake.close()
    assert got["how"] == "forced" and got["in_flight"] is None
    assert restarts == [1020.0]


# ---- the switch: what changed, when, how ------------------------------------------

def test_a_switch_regenerates_the_served_config_and_records_old_and_new(gw, config):
    gateway.write_served(config)
    adopt_for("code", f"llamacpp:{STEM}")
    clock = Clock()
    restarts = []
    got = gs.switch(base=gw.base, restart=lambda: restarts.append(1),
                    requested_at=999.0, idle_s=3, max_wait_s=60, poll_s=1,
                    clock=clock.now, sleep=clock.sleep)
    assert restarts == [1]
    served = yaml.safe_load(gateway.served_path(config).read_text(encoding="utf-8"))
    names = {e["model_name"]: e["litellm_params"] for e in served["model_list"]}
    assert names["sohot-code"]["model"] == f"openai/{STEM}"
    assert [r["lane"] for r in got] == ["code"]
    conn = ms.connect()
    try:
        rows = gs.switches(conn)
    finally:
        conn.close()
    assert len(rows) == 1
    row = rows[0]
    assert row["lane"] == "code" and row["new_spec"] == f"llamacpp:{STEM}"
    assert row["old_spec"] == "openai/mlx-community/Qwen3-4B-Instruct-2507-4bit"
    assert row["how"] == "idle" and row["requested_at"] == 999.0
    assert row["switched_at"] == 1003.0 and row["in_flight"] == 0


def test_the_next_switch_names_the_last_one_as_its_old_spec(gw, config):
    gateway.write_served(config)
    clock = Clock()
    adopt_for("code", f"llamacpp:{STEM}")
    gs.switch(base=gw.base, restart=lambda: None, idle_s=1, max_wait_s=5,
              poll_s=1, clock=clock.now, sleep=clock.sleep)
    adopt_for("code", "local-large")
    gs.switch(base=gw.base, restart=lambda: None, idle_s=1, max_wait_s=5,
              poll_s=1, clock=clock.now, sleep=clock.sleep)
    conn = ms.connect()
    try:
        rows = gs.switches(conn)
    finally:
        conn.close()
    assert [(r["old_spec"], r["new_spec"]) for r in rows] == [
        ("openai/mlx-community/Qwen3-4B-Instruct-2507-4bit", f"llamacpp:{STEM}"),
        (f"llamacpp:{STEM}", "local-large")]


def test_nothing_changed_means_no_wait_no_restart_no_record(gw, config):
    gateway.write_served(config)
    restarts = []
    got = gs.switch(base=gw.base, restart=lambda: restarts.append(1),
                    idle_s=1, max_wait_s=5, poll_s=1,
                    clock=Clock().now, sleep=Clock().sleep)
    assert got == [] and restarts == [] and gw.calls == []


# ---- the detached waiter -----------------------------------------------------------

def test_the_waiter_takes_the_machine_lock_itself(monkeypatch):
    """An adoption runs inside a run that holds the lock; the child must not inherit it,
    or it restarts mid-run instead of after."""
    monkeypatch.setenv(exclusive.HELD_ENV, "1")
    argv, env = gs.waiter(requested_at=12.5)
    assert exclusive.HELD_ENV not in env
    assert argv[-4:] == ["-m", "harness.gateway_switch", "--requested-at", "12.5"]


def test_an_adoption_spawns_the_waiter_detached_with_its_own_log(monkeypatch):
    spawned = []

    def popen(argv, **kw):
        spawned.append((argv, kw))

    monkeypatch.setattr(gs.sys, "platform", "darwin")
    monkeypatch.setenv(exclusive.HELD_ENV, "1")
    gs.spawn(requested_at=7.0, popen=popen)
    argv, kw = spawned[0]
    assert argv[-4:] == ["-m", "harness.gateway_switch", "--requested-at", "7.0"]
    assert kw["start_new_session"] and exclusive.HELD_ENV not in kw["env"]
    assert kw["cwd"] == str(gateway.REPO)
    assert kw["stdout"].name.endswith("gateway-switch.log")
