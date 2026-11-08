"""A node-served reply and its receipt name the node's llama.cpp build, not this machine's. #1607."""
import argparse
import asyncio
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
import respx

from evals import core
from evals import run as R
from evals.core import Case, Receipt, comparable
from evals.runners.base import BaseRunner
from harness import completion, context, gateway, nodes, serving

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("served_model_1607", ROOT / "gateway" / "served_model.py")
served = importlib.util.module_from_spec(spec)
spec.loader.exec_module(served)

MODEL = "Qwen2.5-7B-Instruct-Q4_K_M"
NODE_BASE = "http://styx.invalid:8083"
STYX = "Mac14,12/macOS/arm64/731b6725bbad"
HERE_ENV = {"hw_model": "Mac17,15", "os": "macOS-27.0.1-arm64-arm-64bit", "arch": "arm64",
            "host": "b82b652fe135", "memory_gb": 96, "accelerator": {},
            "versions": {"llama.cpp": "11960"}}
BASE = f"""model_list:
  - model_name: {MODEL}
    engine: llama-server
    litellm_params:
      model: openai/{MODEL}
      api_base: http://127.0.0.1:8082/v1
      api_key: not-needed
"""
PROPS = {"build_info": "b12110-cd959bae9", "default_generation_settings": {"n_ctx": 32768}, "total_slots": 2}


def styx():
    return nodes.parse({"nodes": [{"name": "styx", "api_base": f"{NODE_BASE}/v1", "engine": "llama-server",
                                   "models": [MODEL], "machine": STYX}]})


@pytest.fixture
def routed(tmp_path, monkeypatch):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(BASE, encoding="utf-8")
    gateway.write_served(cfg, defaults={}, nodes=styx())
    monkeypatch.setenv("GATEWAY_CONFIG", str(cfg))
    served._SHAPES.clear()
    yield cfg
    served._SHAPES.clear()


@pytest.mark.parametrize("info, want", [("b12110-cd959bae9", "12110"), ("b11960", "11960"),
                                        ("11960-8642541b2", "11960"), ("", ""), (None, ""), ("unknown", "")])
def test_the_build_number_is_read_from_build_info(info, want):
    assert context.build_of(info) == want


def test_the_gateway_names_the_nodes_build_from_its_props(routed, monkeypatch):
    answers = {f"{NODE_BASE}/props": PROPS, f"{NODE_BASE}/models": {"data": []}}
    monkeypatch.setattr(context, "_get_json", lambda url, key="": answers[url])
    assert served.served_shape(MODEL) == {"ctx": 32768, "slots": 2, "engine-build": "12110"}
    got = asyncio.run(served.proxy_handler_instance.async_post_call_response_headers_hook(
        data={"model": MODEL}, user_api_key_dict=None,
        response=SimpleNamespace(_hidden_params={"api_base": f"{NODE_BASE}/v1"})))
    assert got["x-sohot-node"] == "styx" and got["x-sohot-engine-build"] == "12110"


def test_a_loopback_upstream_sends_no_build(routed, monkeypatch):
    """This machine's build is in its own receipt environment; the gateway does not ask its own router."""
    monkeypatch.setattr(context, "_get_json", lambda *a, **k: pytest.fail("asked a loopback /props"))
    assert context.served_build(MODEL + nodes.LOCAL_SUFFIX) is None


class Asks(BaseRunner):
    def __init__(self, gw):
        self.candidate = self.spec = "sohot-code"
        self.gateway = gw

    def generate(self, case):
        return completion.complete_full("x", "sohot-code", gateway=self.gateway).text, 0


def _reply(build):
    headers = {"x-sohot-model": MODEL, "x-sohot-machine": STYX, "x-sohot-node": "styx"}
    if build:
        headers["x-sohot-engine-build"] = build
    return httpx.Response(200, headers=headers, json={
        "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}], "usage": {}})


@pytest.fixture
def quiet(monkeypatch, machine_is):
    for name, value in (("accelerator_id", "unified:client"), ("where_id", "host"),
                        ("swap_used_mb", 7), ("instruments", {}), ("engines", {})):
        monkeypatch.setattr(R, name, lambda *a, _v=value, **k: _v)
    monkeypatch.setattr(R, "warn_if_pressed", lambda *a, **k: SimpleNamespace(as_dict=lambda: {"level": 1}))
    monkeypatch.setattr(completion, "SERVED", {}, raising=False)
    monkeypatch.setattr(serving, "llamacpp_build", lambda binary="": "11960")
    machine_is(HERE_ENV)


def _run(tmp_path, monkeypatch, gw):
    monkeypatch.setattr(R, "build_runner", lambda candidate, g, *a, **k: Asks(g))
    for name in ("load_cases", "load_suite"):
        monkeypatch.setattr(core, name, lambda *a, **k: [Case("c1", "code", "x", assertions={"checks": ["True"]})])
    args = argparse.Namespace(
        screen=False, repeat=1, adherence="", cases=str(ROOT / "evals" / "cases"),
        modality="code", candidates="sohot-code", from_winners=False, gateway=gw,
        out=str(tmp_path / "out"), split="all", max_tokens=100)
    R._execute(args)
    return json.loads((tmp_path / "out" / "results.json").read_text(encoding="utf-8"))


@respx.mock
def test_a_node_served_receipt_names_the_nodes_build_not_this_machines(tmp_path, monkeypatch, quiet):
    gw = "http://127.0.0.1:4000"
    respx.post(f"{gw}/v1/chat/completions").mock(return_value=_reply("12110"))
    data = _run(tmp_path, monkeypatch, gw)
    assert completion.served(gw)[(gw, "sohot-code")]["build"] == "12110"
    assert data["receipt"]["machine"] == STYX
    assert data["receipt"]["served"]["sohot-code"]["llama.cpp"] == "12110"
    assert data["environment"]["versions"] == {"llama.cpp": "12110"}
    assert data["environment"]["client"]["versions"]["llama.cpp"] == "11960"


@respx.mock
def test_a_node_reply_without_a_build_claims_none(tmp_path, monkeypatch, quiet):
    gw = "http://127.0.0.1:4000"
    respx.post(f"{gw}/v1/chat/completions").mock(return_value=_reply(""))
    data = _run(tmp_path, monkeypatch, gw)
    assert "llama.cpp" not in data["receipt"]["served"]["sohot-code"]
    assert "versions" not in data["environment"]


def test_two_node_builds_are_two_exams_and_a_receipt_without_one_still_pairs():
    base = dict(modality="code", case_ids=("a",), repeat=1, sampling={}, gateway="g", machine=STYX)
    a = Receipt(**base, served={"k": {"model": MODEL, "llama.cpp": "12110"}})
    b = Receipt(**base, served={"k": {"model": MODEL, "llama.cpp": "12200"}})
    old = Receipt(**base, served={"k": {"model": MODEL}})
    ok, why = comparable(a, b)
    assert not ok and "llama.cpp 12110 vs 12200" in why
    assert comparable(a, old)[0]


def test_smoke_warns_when_the_node_build_differs_and_passes_when_it_matches():
    n = styx()
    differ = nodes.builds(n, "11960", get=lambda node: "12110")
    assert differ == [(False, "node styx runs llama.cpp build 12110, this machine 11960: "
                              "its replies and receipts name 12110")]
    assert nodes.builds(n, "12110", get=lambda node: "12110") == [
        (True, "node styx runs llama.cpp build 12110, this machine 12110")]
    silent = nodes.builds(n, "11960", get=lambda node: (_ for _ in ()).throw(OSError("down")))
    assert not silent[0][0] and "names no llama.cpp build" in silent[0][1]


@pytest.mark.parametrize("node_build, rc, mark", [("12110", 0, "WARN"), ("11960", 0, "PASS")])
def test_smoke_prints_the_build_line_and_a_mismatch_never_fails_it(monkeypatch, capsys, node_build, rc, mark):
    monkeypatch.setattr(nodes, "load", lambda file=None: styx())
    monkeypatch.setattr(nodes, "parked", lambda file=None: [])
    monkeypatch.setattr(nodes, "smoke", lambda *a, **k: [(True, "node styx up: m served by styx")])
    monkeypatch.setattr(nodes, "_get_build", lambda node: node_build)
    monkeypatch.setattr(serving, "llamacpp_build", lambda binary="": "11960")
    from harness import gateway_key
    monkeypatch.setattr(gateway_key, "key", lambda: "k")
    assert nodes.main(["smoke", "--gateway", "http://127.0.0.1:4000"]) == rc
    out = capsys.readouterr().out
    assert f"{mark}  node styx runs llama.cpp build {node_build}, this machine 11960" in out
