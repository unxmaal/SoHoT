"""A node's down mark runs a fixed cooldown from the failure; the gateway's own skips never extend it. #1808."""
import asyncio
import importlib.util
import socket
import threading
import time
import types
from pathlib import Path

import pytest

from harness import gateway, node_reach, nodes

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("served_model_1808", REPO / "gateway" / "served_model.py")
served = importlib.util.module_from_spec(spec)
spec.loader.exec_module(served)

MODEL = "Qwen2.5-7B-Instruct-Q4_K_M"
BASE = f"""model_list:
  - model_name: {MODEL}
    engine: llama-server
    litellm_params:
      model: openai/{MODEL}
      api_base: http://127.0.0.1:8082/v1
      api_key: not-needed
"""
LOCAL = "http://127.0.0.1:8082/v1"
COOLDOWN = 30.0


class Response:
    def __init__(self, base):
        self._hidden_params = {"api_base": base}


@pytest.fixture
def listening():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen(64)

    def accept():
        try:
            while True:
                s.accept()[0].close()
        except OSError:
            return
    threading.Thread(target=accept, daemon=True).start()
    yield s.getsockname()[1]
    s.close()


@pytest.fixture
def gw(tmp_path, monkeypatch, listening):
    monkeypatch.setenv("LOCALHARNESS_HOME", str(tmp_path / "home"))
    cfg = tmp_path / "config.yaml"
    cfg.write_text(BASE, encoding="utf-8")
    base = f"http://127.0.0.1:{listening}/v1"
    gateway.write_served(cfg, defaults={}, nodes=nodes.parse({"nodes": [{
        "name": "styx", "api_base": base, "engine": "llama-server", "models": [MODEL],
        "key": "keychain:svc/acct", "cooldown": COOLDOWN}]}))
    monkeypatch.setenv("GATEWAY_CONFIG", str(cfg))
    clock = [1000.0]
    monkeypatch.setattr(served, "time", types.SimpleNamespace(monotonic=lambda: clock[0], time=time.time))
    for cache in (served._REACH, served._REACHING, served._ROUTED):
        cache.clear()
    return types.SimpleNamespace(clock=clock, node=base, log=tmp_path / "home" / "nodes" / "reach.jsonl")


def _send(model=MODEL):
    """What the pre-call hook sends a request on to."""
    data = {"model": model}
    return asyncio.run(served.proxy_handler_instance.async_pre_call_hook(None, None, data, "acompletion"))


def _reply(data, answered_by):
    return asyncio.run(served.proxy_handler_instance.async_post_call_response_headers_hook(
        data=data, user_api_key_dict=None, response=Response(answered_by)))


def _fail_on_the_node(g):
    data = _send()
    assert data["model"] == MODEL, "the node was not tried before it failed"
    assert _reply(data, LOCAL)["x-sohot-fallback"] == "styx"


def _request(g):
    """One request at the current time: the model it went to, with the reply the right deployment gives."""
    data = _send()
    _reply(data, g.node if data["model"] == MODEL else LOCAL)
    return data["model"]


def test_skips_inside_a_down_window_do_not_extend_it(gw):
    _fail_on_the_node(gw)
    gw.clock[0] += 20
    assert _request(gw) == MODEL + nodes.LOCAL_SUFFIX
    gw.clock[0] += 20
    assert _request(gw) == MODEL, "a skip 20 s after the failure re-armed the cooldown from its own time"


@pytest.mark.parametrize("gap", [1.0, 5.0, 29.0])
def test_a_recovered_node_is_routed_again_within_its_cooldown_and_one_request(gw, gap):
    _fail_on_the_node(gw)
    t0, sent = gw.clock[0], []
    while gw.clock[0] < t0 + 4 * COOLDOWN:
        gw.clock[0] += gap
        sent.append((gw.clock[0] - t0, _request(gw)))
    first = next((at for at, model in sent if model == MODEL), None)
    assert first is not None, f"steady traffic every {gap:g} s kept the node out of routing"
    assert COOLDOWN <= first <= COOLDOWN + gap
    assert all(model == MODEL for at, model in sent if at >= first)


def test_a_request_asked_of_the_local_copy_never_marks_the_node_down(gw):
    _reply({"model": MODEL + nodes.LOCAL_SUFFIX}, LOCAL)
    assert _send()["model"] == MODEL
    assert node_reach.read(gw.log) == []


def test_the_gateway_logs_each_routing_transition_once(gw):
    _fail_on_the_node(gw)
    gw.clock[0] += 5
    _request(gw)
    _request(gw)
    gw.clock[0] += COOLDOWN
    _request(gw)
    _request(gw)
    got = [(r["node"], r["state"]) for r in node_reach.read(gw.log)]
    assert got == [("styx", node_reach.DOWN), ("styx", node_reach.UP)]
    assert node_reach.read(gw.log)[0]["why"] == f"{MODEL} fell back"


def test_a_node_that_takes_no_connection_is_logged_down(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALHARNESS_HOME", str(tmp_path / "home"))
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    cfg = tmp_path / "config.yaml"
    cfg.write_text(BASE, encoding="utf-8")
    gateway.write_served(cfg, defaults={}, nodes=nodes.parse({"nodes": [{
        "name": "styx", "api_base": f"http://127.0.0.1:{port}/v1", "engine": "llama-server",
        "models": [MODEL], "key": "keychain:svc/acct"}]}))
    monkeypatch.setenv("GATEWAY_CONFIG", str(cfg))
    for cache in (served._REACH, served._REACHING, served._ROUTED):
        cache.clear()
    assert _send()["model"] == MODEL + nodes.LOCAL_SUFFIX
    got = node_reach.read(tmp_path / "home" / "nodes" / "reach.jsonl")
    assert [(r["state"], r["why"]) for r in got] == [(node_reach.DOWN, "it took no connection")]


def test_outages_are_clipped_to_the_window_and_an_open_one_runs_to_now(tmp_path):
    log = tmp_path / "reach.jsonl"
    for at, state in ((100, "down"), (130, "up"), (500, "down"), (510, "down"), (560, "up"), (900, "down")):
        node_reach.record("styx", state, "why", at=at, where=log)
    node_reach.record("other", "up", at=50, where=log)
    log.write_text(log.read_text(encoding="utf-8") + "not json\n", encoding="utf-8")
    got = node_reach.summary(since=520, now=1000, where=log)
    assert [n["node"] for n in got] == ["styx"]
    styx = got[0]
    assert [(o["start"], o["end"]) for o in styx["outages"]] == [(500, 560), (900, None)]
    assert styx["down_s"] == pytest.approx((560 - 520) + (1000 - 900))
    assert styx["down_now"] is True
    assert "out of routing 2 time(s), 2m 20s in all" in node_reach.line(styx)
    assert node_reach.line(styx).endswith("still out, not seen up since")


def test_morning_names_a_node_that_was_out_of_routing(tmp_path, monkeypatch):
    from harness import memory_store as ms, morning
    from harness.commands import morning as morning_cmd
    monkeypatch.setenv("LOCALHARNESS_HOME", str(tmp_path / "home"))
    now = time.time()
    node_reach.record("styx", node_reach.DOWN, "sohot-claims fell back", at=now - 100)
    node_reach.record("styx", node_reach.UP, "it took a connection", at=now - 59)
    conn = ms.connect()
    r = morning.gather(conn, now, now - 3600, gh=lambda a: "[]", lanes=lambda c: [], stalls=lambda c: [],
                       reach=node_reach.summary)
    got = [ln for ln in morning_cmd.render(r) if "styx" in ln]
    assert len(got) == 1 and got[0].startswith("nodes     styx out of routing 1 time(s), 41s in all; last ")
    assert got[0].endswith("(sohot-claims fell back), back after 41s")
