"""A node deploy takes the node out of the gateway's routing and waits for its in-flight requests before it restarts it. #1815."""
from __future__ import annotations

import asyncio
import importlib.util
import json
import shlex
import threading
import time
from pathlib import Path

import pytest

from harness import cuts, deploy, deploy_switch, gateway, gateway_switch, node_deploy, node_reach, nodes, reasons
from harness import memory_store as ms
from test_node_deploy_1692 import NEW, Fake, _follow, _node, _yaml, deployed  # noqa: F401 - deployed is a fixture

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("served_model_1815", REPO / "gateway" / "served_model.py")
served = importlib.util.module_from_spec(spec)
spec.loader.exec_module(served)

MODEL = "Qwen2.5-7B-Instruct-Q4_K_M"
ONLY_THERE = "imajev-4b-Q8_0"
BASE = f"""model_list:
  - model_name: {MODEL}
    engine: llama-server
    litellm_params:
      model: openai/{MODEL}
      api_base: http://127.0.0.1:8082/v1
      api_key: not-needed
"""


class Styx:
    """The node's own server: a restart cuts every request still in flight with a 500."""

    def __init__(self) -> None:
        self.processing, self.answers, self.restarts = 0, [], []
        self._lock, self._cut = threading.Lock(), threading.Event()

    def start(self, seconds: float) -> threading.Thread:
        started = threading.Event()

        def work() -> None:
            with self._lock:
                self.processing += 1
            started.set()
            self._cut.wait(timeout=seconds)
            with self._lock:
                self.answers.append(500 if self._cut.is_set() else 200)
                self.processing -= 1

        t = threading.Thread(target=work, daemon=True)
        t.start()
        started.wait()
        return t

    def restart(self) -> None:
        with self._lock:
            self.restarts.append(self.processing)
            if self.processing:
                self._cut.set()
        end = time.monotonic() + 5
        while self.processing and time.monotonic() < end:
            time.sleep(0.01)
        self._cut.clear()


class Deploying(Fake):
    """ssh to a node whose `state` reports its server's in-flight count and whose install restarts that server."""

    def __init__(self, styx: Styx, on_poll=None):
        super().__init__()
        self.styx, self.on_poll = styx, on_poll

    def __call__(self, argv, script, timeout):
        args = shlex.split(argv[-1])[3:]
        if args[0] == "state":
            if self.on_poll:
                self.on_poll()
            return 0, json.dumps({"interactive": self.styx.processing})
        if args[0] == "install":
            self.styx.restart()
        return super().__call__(argv, script, timeout)


@pytest.fixture
def gw(tmp_path, monkeypatch):
    """This machine's gateway serving styx's two models node first, only one of them with a copy here."""
    cfg = tmp_path / "config.yaml"
    cfg.write_text(BASE, encoding="utf-8")
    gateway.write_served(cfg, defaults={}, nodes=nodes.parse({"nodes": [{
        "name": "styx", "api_base": "http://127.0.0.1:9/v1", "engine": "llama-server", "models": [MODEL, ONLY_THERE],
        "key": "keychain:svc/acct"}]}))
    monkeypatch.setenv("GATEWAY_CONFIG", str(cfg))
    for cache in (served._REACH, served._REACHING, served._ROUTED, served._NAME_DOWN, served._FAULT):
        cache.clear()
    served._REACH["styx"] = (time.monotonic(), True)


def _send(model=MODEL, smoke=False):
    """The model the gateway's pre-call hook sends a request on to."""
    data = {"model": model, **({"metadata": {"tags": ["purpose:smoke"]}} if smoke else {})}
    return asyncio.run(served.proxy_handler_instance.async_pre_call_hook(None, None, data, "acompletion"))["model"]


def test_a_request_in_flight_when_the_node_deploy_starts_completes_and_new_ones_go_to_this_machine(shown_live, 
        deployed, gw, tmp_path, monkeypatch):  # noqa: F811
    monkeypatch.setattr(node_deploy, "DRAIN_POLL_S", 0.02)
    styx, sent = Styx(), []
    ssh = Deploying(styx, on_poll=lambda: sent.append((_send(), _send(smoke=True))))
    assert _send() == MODEL, "before the deploy the node serves"
    running = styx.start(0.3)
    r = _follow(deployed, _yaml(tmp_path, _node("styx", deploy={"ssh": "styx"})), ssh)["nodes"]["styx"]
    running.join(5)
    assert r["outcome"] == node_deploy.DEPLOYED, r
    assert styx.answers == [200], "the request in flight finished before the restart"
    assert styx.restarts == [0], "nothing was in flight when the install restarted the node"
    assert r["drain"]["outcome"] == node_deploy.DRAINED and r["drain"]["in_flight"] == 0
    assert sent and all(got == (MODEL + nodes.LOCAL_SUFFIX, MODEL) for got in sent), \
        "while draining, new work goes to this machine's copy and only the deploy's smoke reaches the node"
    assert not gateway_switch.draining(node="styx") and _send() == MODEL, "routable again once the deploy ended"
    rows = node_reach.read()
    assert [(x["state"], x["why"].split(" ")[0]) for x in rows] == [
        ("down", "draining"), ("down", "drain"), ("up", "the")], rows
    assert "drained" in rows[1]["why"] and "ended deployed" in rows[2]["why"]
    assert node_reach.summary(0, time.time())[0]["outages"][0]["why"] == f"draining for the deploy of {NEW[:12]}"


def test_a_node_with_no_copy_here_refuses_while_draining_as_the_harness_not_the_model(gw):
    gateway_switch.start_drain(time.time() + 60, node="styx")
    with pytest.raises(Exception) as got:
        _send(ONLY_THERE)
    detail = str(getattr(got.value, "detail", got.value))
    assert getattr(got.value, "status_code", None) == 503 and "node styx" in detail
    assert reasons.classify(detail) == reasons.REFUSED_BY_GATEWAY
    assert _send() == MODEL + nodes.LOCAL_SUFFIX
    gateway_switch.start_drain(time.time() - 1, node="styx")
    assert _send() == MODEL, "a drain whose deploy died expires on its own"


def _drain(busy):
    clock, slept = [0.0], []

    def sleep(s):
        slept.append(s)
        clock[0] += s
    node = nodes.parse({"nodes": [_node("styx")]})[0]
    got = node_deploy.drain(node, "the deploy of x", busy=busy, sleep=sleep, clock=lambda: clock[0])
    return got, slept


@pytest.mark.parametrize("busy, said", [(lambda n: 1, "1 in flight"), (lambda n: None, "unknown in flight")])
def test_the_drain_wait_ends_at_its_deadline_and_says_so(busy, said):
    got, slept = _drain(busy)
    assert got["outcome"] == node_deploy.DRAIN_DEADLINE
    assert got["waited_s"] == node_deploy.DRAIN_S and len(slept) == node_deploy.DRAIN_S / node_deploy.DRAIN_POLL_S
    assert set(slept) == {node_deploy.DRAIN_POLL_S}
    assert gateway_switch.draining(node="styx"), "the node stays out of routing through its restart"
    end = node_reach.read()[-1]
    assert end["state"] == node_reach.DOWN and end["why"].startswith(f"drain {node_deploy.DRAIN_DEADLINE} after")
    assert said in end["why"]
    c = ms.connect()
    try:
        cuts.flush(c)
        assert [r[0] for r in c.execute("SELECT knob FROM limit_cuts").fetchall()] == ["deploy_node_drain"]
    finally:
        c.close()


def test_a_drain_that_empties_ends_drained_without_waiting_for_the_deadline():
    left = [2, 1, 0]
    got, slept = _drain(lambda n: left.pop(0))
    assert got == {"outcome": node_deploy.DRAINED, "in_flight": 0, "waited_s": 2 * node_deploy.DRAIN_POLL_S}
    assert len(slept) == 2


def test_a_deploy_held_at_the_deadline_still_installs_and_records_it(shown_live, deployed, tmp_path):  # noqa: F811
    ssh, clock = Fake(), [0.0]
    ssh.busy = [1] * 10_000

    def sleep(s):
        clock[0] += s
    r = node_deploy.follow(deployed["conn"], runner=ssh, check=lambda n: "", alert=lambda m: None,
                           load=lambda: nodes.load(_yaml(tmp_path, _node("styx", deploy={"ssh": "styx"}))),
                           sleep=sleep, clock=lambda: clock[0])["nodes"]["styx"]
    assert r["outcome"] == node_deploy.DEPLOYED and r["drain"]["outcome"] == node_deploy.DRAIN_DEADLINE
    assert r["drain"]["in_flight"] == 1 and ssh.polled
    assert deploy_switch.load(deploy.record_path(deployed["id"]))["nodes"]["styx"]["drain"] == r["drain"]
    assert not gateway_switch.draining(node="styx")


def test_a_failed_deploy_keeps_the_node_out_of_routing_through_its_rollback_then_puts_it_back(shown_live, deployed, tmp_path):  # noqa: F811
    seen = []
    ssh = Fake(install={NEW: (1, "boom")})
    real = ssh.__call__

    def runner(argv, script, timeout):
        if "install" in argv[-1]:
            seen.append(gateway_switch.draining(node="styx"))
        return real(argv, script, timeout)
    r = _follow(deployed, _yaml(tmp_path, _node("styx", deploy={"ssh": "styx"})), runner)["nodes"]["styx"]
    assert r["outcome"] == node_deploy.ROLLED_BACK and seen == [True, True]
    assert not gateway_switch.draining(node="styx")
    assert node_reach.read()[-1]["why"].endswith("ended rolled_back")
