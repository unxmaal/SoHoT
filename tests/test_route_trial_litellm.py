"""#1338 inside a real LiteLLM proxy: both routing arms load from the served config, send each tier to its
upstream, and the adaptive arm's cells move with the verdicts the harness sends back.

Needs litellm, which the suite does not install: `make test-litellm`.
"""
import json
import os
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler
from pathlib import Path

import pytest

pytest.importorskip("litellm", reason="needs litellm: make test-litellm")
httpx = pytest.importorskip("httpx")

from harness import completion, gateway, gateway_key, routes  # noqa: E402
from harness.loopback import ThreadingHTTPServer  # noqa: E402

pytestmark = pytest.mark.litellm
REPO = Path(__file__).resolve().parents[1]
KEY = "sk-test-route"
MODEL = "Qwen2.5-7B-Instruct-Q4_K_M"
HARD = ("Think step by step. Prove that the algorithm is correct, then derive its complexity, analyze each "
        "case, and reason about edge cases before you answer. Explain your reasoning step by step.")


def _server(who):
    class Upstream(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if body.get("stream"):
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                chunk = {"id": "x", "object": "chat.completion.chunk", "created": 1, "model": body["model"],
                         "choices": [{"index": 0, "finish_reason": "stop",
                                      "delta": {"role": "assistant", "content": who}}]}
                self.wfile.write(f"data: {json.dumps(chunk)}\n\ndata: [DONE]\n\n".encode())
                return
            data = json.dumps({"id": "x", "object": "chat.completion", "created": 1, "model": body["model"],
                               "choices": [{"index": 0, "finish_reason": "stop",
                                            "message": {"role": "assistant", "content": who}}],
                               "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
    up = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
    threading.Thread(target=up.serve_forever, daemon=True).start()
    return up


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture
def proxy(tmp_path, monkeypatch):
    local, cloud = _server("from-local"), _server("from-cloud")
    for mod, name in (("route_feedback", "proxy_handler_instance"), ("key_auth", "user_api_key_auth"),
                      ("served_model", "proxy_handler_instance")):
        (tmp_path / f"{mod}.py").write_text(
            f"import sys\nsys.path.insert(0, {str(REPO)!r})\n"
            f"from gateway.{mod} import {name}  # noqa: F401\n", encoding="utf-8")
    lbase = f"http://127.0.0.1:{local.server_address[1]}/v1"
    cfg = tmp_path / "config.yaml"
    cfg.write_text(f"""model_list:
  - model_name: {MODEL}
    engine: llama-server
    litellm_params: {{model: openai/{MODEL}, api_base: "{lbase}", api_key: not-needed}}
  - model_name: sohot-code
    engine: llama-server
    litellm_params: {{model: openai/{MODEL}, api_base: "{lbase}", api_key: not-needed}}
  - model_name: sohot-extract
    engine: llama-server
    litellm_params: {{model: openai/{MODEL}, api_base: "{lbase}", api_key: not-needed}}
  - model_name: cloud-opus
    engine: llama-server
    litellm_params: {{model: openai/opus, api_base: "http://127.0.0.1:{cloud.server_address[1]}/v1",
                      api_key: not-needed, input_cost_per_token: 4.0e-06}}
litellm_settings:
  callbacks: ["route_feedback.proxy_handler_instance", "served_model.proxy_handler_instance"]
  num_retries: 0
  use_chat_completions_url_for_anthropic_messages: true
general_settings:
  master_key: os.environ/LITELLM_MASTER_KEY
  custom_auth: key_auth.user_api_key_auth
""", encoding="utf-8")
    served = gateway.write_served(cfg, defaults={}, nodes=[])
    port = _free_port()
    log = open(tmp_path / "proxy.log", "w", encoding="utf-8")
    exe = Path(sys.executable).parent / "litellm"
    proc = subprocess.Popen(
        [str(exe), "--config", str(served), "--host", "127.0.0.1", "--port", str(port)],
        env={**os.environ, "LITELLM_MASTER_KEY": KEY, "GATEWAY_CONFIG": str(cfg),
             "LITELLM_LOCAL_MODEL_COST_MAP": "True"},
        stdout=log, stderr=subprocess.STDOUT)
    base = f"http://127.0.0.1:{port}"
    deadline = time.time() + 90
    while time.time() < deadline:
        try:
            if httpx.get(f"{base}/v1/models", headers={"Authorization": f"Bearer {KEY}"},
                         timeout=2).status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.5)
            continue
        time.sleep(0.5)
    else:
        proc.terminate()
        pytest.fail((tmp_path / "proxy.log").read_text(encoding="utf-8")[-4000:])
    monkeypatch.setenv(gateway_key.ENV_VAR, KEY)
    monkeypatch.setattr(gateway_key, "_cache", {})
    monkeypatch.setenv("GATEWAY_CONFIG", str(cfg))
    routes.headers()
    yield base
    proc.terminate()
    proc.wait(10)
    local.shutdown()
    cloud.shutdown()


def _chat(base, model, text, stream=False):
    body = {"model": model, "messages": [{"role": "user", "content": text}], "stream": stream}
    r = httpx.post(f"{base}/v1/chat/completions", json=body, timeout=60, headers={"Authorization": f"Bearer {KEY}"})
    return r.status_code, r.text, r.headers


def _messages(base, model, text, stream=False):
    body = {"model": model, "max_tokens": 50, "stream": stream, "messages": [{"role": "user", "content": text}]}
    r = httpx.post(f"{base}/v1/messages", json=body, timeout=60,
                   headers={"Authorization": f"Bearer {KEY}", "anthropic-version": "2023-06-01"})
    return r.status_code, r.text, r.headers


def test_both_arms_load_and_send_each_tier_to_its_upstream_on_both_routes(proxy):
    names = {m["id"] for m in httpx.get(f"{proxy}/v1/models", headers={"Authorization": f"Bearer {KEY}"}).json()["data"]}
    assert {"sohot-code-auto", "sohot-code-adaptive"} <= names
    for arm in routes.ARMS:
        model = routes.alias("code", arm)
        for stream in (False, True):
            code, text, h = _chat(proxy, model, "hi", stream)
            assert code == 200 and "from-local" in text, text
            assert h[routes.ROUTED_HEADER] == "sohot-code"
            assert h["x-sohot-model"] == MODEL, "the reply names the model that answered, not the router"
            code, text, h = _chat(proxy, model, HARD, stream)
            assert code == 200 and "from-cloud" in text, text
            assert h[routes.ROUTED_HEADER] == "cloud-opus"
            code, text, _ = _messages(proxy, model, "hi", stream)
            assert code == 200 and "from-local" in text, text
            code, text, _ = _messages(proxy, model, HARD, stream)
            assert code == 200 and "from-cloud" in text, text


def _cell(base, request_type, model):
    got = httpx.get(f"{base}/adaptive_router/state", headers={"Authorization": f"Bearer {KEY}"}, timeout=10).json()
    router = next(r for r in got["routers"] if r["router_name"] == "sohot-code-adaptive")
    return next(c for c in router["cells"] if c["request_type"] == request_type and c["model"] == model)


def _ask(base, model):
    got = completion.complete_full("hi", model=model, gateway=base, max_tokens=20)
    assert got.call_id and got.routed, "the harness reads the call id and the routed tier off the reply"
    return got


def test_verdicts_sent_back_move_the_adaptive_arm_and_never_the_heuristic_one(proxy):
    local, cloud = _cell(proxy, "general", "sohot-code"), _cell(proxy, "general", "cloud-opus")
    assert local["samples"] == cloud["samples"] == 0
    sent = {"sohot-code": 0, "cloud-opus": 0}
    for _ in range(60):
        got = _ask(proxy, "sohot-code-adaptive")
        routes.report(got.call_id, routes.FAIL if got.routed == "sohot-code" else routes.PASS)
        sent[got.routed] += 1
    assert sent["sohot-code"], "the first call of a request type goes to its classified tier"
    routes.report("an-unrouted-call", routes.PASS)
    _ask(proxy, "sohot-code-auto")
    after_local, after_cloud = _cell(proxy, "general", "sohot-code"), _cell(proxy, "general", "cloud-opus")
    assert after_local["beta"] == pytest.approx(local["beta"] + sent["sohot-code"])
    assert after_local["alpha"] == pytest.approx(local["alpha"])
    assert after_cloud["alpha"] == pytest.approx(cloud["alpha"] + sent["cloud-opus"])
    picks = [_ask(proxy, "sohot-code-adaptive").routed for _ in range(20)]
    assert picks.count("cloud-opus") >= 18, picks
    assert {_ask(proxy, "sohot-code-auto").routed for _ in range(20)} == {"sohot-code"}


def _case(root, name, prompt, want):
    (root / "extract").mkdir(parents=True, exist_ok=True)
    (root / "extract" / f"{name}.yaml").write_text(
        f"id: {name}\nmodality: extract\nprompt: |\n  {prompt}\nassert:\n  must_contain: [\"{want}\"]\n",
        encoding="utf-8")


def test_the_trial_command_runs_the_arms_through_evals_and_reports_them(proxy, tmp_path):
    cases = tmp_path / "cases"
    _case(cases, "easy", "Say the word.", "from-local")
    _case(cases, "hard", HARD, "from-cloud")
    run = subprocess.run([sys.executable, "-m", "evals.run", "--modality", "extract", "--gateway", proxy,
                          "--cases", str(cases), "--local-cases", str(tmp_path / "none"), "--candidates",
                          ",".join(routes.arms_of("extract"))],
                         cwd=REPO, env=dict(os.environ), capture_output=True, text=True, timeout=300)
    assert run.returncode == 0, run.stdout[-2000:] + run.stderr[-3000:]
    got = subprocess.run([sys.executable, "-m", "harness.cli", "route-trial", "report", "--lane", "extract", "--json"],
                         cwd=REPO, env=dict(os.environ), capture_output=True, text=True, timeout=120)
    assert got.returncode == 0, got.stdout[-2000:] + got.stderr[-2000:]
    report = json.loads(got.stdout.strip().splitlines()[-1])
    arms = {a["candidate"]: a for a in report["arms"]}
    assert (arms["sohot-extract"]["passed"], arms["sohot-extract"]["cloud_calls"]) == (1, 0)
    assert (arms["sohot-extract-auto"]["passed"], arms["sohot-extract-auto"]["cloud_calls"]) == (2, 1)
    assert arms["sohot-extract-auto"]["cloud_tokens"] > 0 and arms["sohot-extract"]["cloud_tokens"] == 0
    assert arms["sohot-extract-adaptive"]["passed"] == 2
    assert {v["base"] for v in report["verdicts"]} == {"sohot-extract", "sohot-extract-auto"}
