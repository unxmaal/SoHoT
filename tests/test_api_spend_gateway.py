"""#1214 end to end: a real LiteLLM proxy prices a fake hosted request, records it, and refuses past api_budget.

The hosted upstream is a loopback fake; nothing reaches the Anthropic API. Needs litellm: `make test-litellm`.
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

from harness import api_spend  # noqa: E402
from harness import memory_store as ms  # noqa: E402
from harness.loopback import ThreadingHTTPServer  # noqa: E402

pytestmark = pytest.mark.litellm
REPO = Path(__file__).resolve().parents[1]
KEY = "sk-test-spend"
IN, OUT, READ, WRITE = 4e-06, 2e-05, 2e-07, 5e-06
USAGE = {"input_tokens": 1200, "output_tokens": 300, "cache_read_input_tokens": 400,
         "cache_creation_input_tokens": 100}


class Upstream(BaseHTTPRequestHandler):
    """An Anthropic Messages server and an OpenAI one, both answering at once; it counts what reached it."""
    hits: list = []

    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        Upstream.hits.append((self.path, body.get("model")))
        if self.path.endswith("/messages"):
            reply = {"id": "msg_1", "type": "message", "role": "assistant", "model": body["model"],
                     "content": [{"type": "text", "text": "hi"}], "stop_reason": "end_turn",
                     "stop_sequence": None, "usage": USAGE}
        else:
            reply = {"id": "x", "object": "chat.completion", "created": 1, "model": "up",
                     "choices": [{"index": 0, "finish_reason": "stop",
                                  "message": {"role": "assistant", "content": "hi"}}],
                     "usage": {"prompt_tokens": 9, "completion_tokens": 4, "total_tokens": 13}}
        data = json.dumps(reply).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture
def gateway(tmp_path):
    Upstream.hits = []
    up = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
    threading.Thread(target=up.serve_forever, daemon=True).start()
    base_up = f"http://127.0.0.1:{up.server_address[1]}"
    for mod, name in (("spend_guard", "proxy_handler_instance"), ("key_auth", "user_api_key_auth")):
        (tmp_path / f"{mod}.py").write_text(
            f"import sys\nsys.path.insert(0, {str(REPO)!r})\n"
            f"from gateway.{mod} import {name}  # noqa: F401\n", encoding="utf-8")
    cfg = tmp_path / "config.yaml"
    cfg.write_text(f"""model_list:
  - model_name: cloud-opus
    litellm_params:
      model: anthropic/claude-opus-5-5
      api_base: "{base_up}"
      api_key: fake-not-a-key
      input_cost_per_token: {IN}
      output_cost_per_token: {OUT}
      cache_read_input_token_cost: {READ}
      cache_creation_input_token_cost: {WRITE}
  - model_name: sohot-code
    litellm_params: {{model: openai/up, api_base: "{base_up}/v1", api_key: not-needed}}
litellm_settings:
  callbacks: ["spend_guard.proxy_handler_instance"]
  num_retries: 0
general_settings:
  master_key: os.environ/LITELLM_MASTER_KEY
  custom_auth: key_auth.user_api_key_auth
""", encoding="utf-8")
    port = _free_port()
    log = open(tmp_path / "proxy.log", "w", encoding="utf-8")
    exe = Path(sys.executable).parent / "litellm"
    proc = subprocess.Popen(
        [str(exe), "--config", str(cfg), "--host", "127.0.0.1", "--port", str(port)],
        env={**os.environ, "LITELLM_MASTER_KEY": KEY, "GATEWAY_CONFIG": str(cfg),
             "LITELLM_LOCAL_MODEL_COST_MAP": "True", "ANTHROPIC_API_KEY": "fake-not-a-key"},
        stdout=log, stderr=subprocess.STDOUT)
    base = f"http://127.0.0.1:{port}"
    deadline, last = time.time() + 90, None
    while time.time() < deadline:
        try:
            if httpx.get(f"{base}/v1/models", headers={"Authorization": f"Bearer {KEY}"},
                         timeout=2).status_code == 200:
                break
        except httpx.HTTPError as exc:
            last = exc
        time.sleep(0.5)
    else:
        proc.terminate()
        pytest.fail(f"{last}\n" + (tmp_path / "proxy.log").read_text(encoding="utf-8"))
    yield base, tmp_path
    proc.terminate()
    proc.wait(10)
    up.shutdown()


def _rows(n=0, timeout=20.0):
    """api_spend rows once there are n; LiteLLM fires the success event just after the reply."""
    deadline = time.time() + timeout
    while True:
        conn = ms.connect()
        try:
            rows = [dict(r) for r in conn.execute("SELECT * FROM api_spend ORDER BY id")]
        finally:
            conn.close()
        if len(rows) >= n or time.time() > deadline:
            return rows
        time.sleep(0.1)


def _ask(base, model, tags=""):
    h = {"Authorization": f"Bearer {KEY}", **({"x-litellm-tags": tags} if tags else {})}
    return httpx.post(f"{base}/v1/chat/completions", headers=h, timeout=30,
                      json={"model": model, "max_tokens": 20, "messages": [{"role": "user", "content": "hi"}]})


def test_a_hosted_request_is_priced_recorded_and_refused_past_the_budget(gateway, monkeypatch):
    base, tmp = gateway
    assert _ask(base, "sohot-code").status_code == 200
    r = _ask(base, "cloud-opus", tags="purpose:eval,job:7")
    assert r.status_code == 200, r.text
    (row,) = _rows(1)
    want = (1200 * IN + 300 * OUT + 400 * READ + 100 * WRITE)
    assert row["alias"] == "cloud-opus" and row["caller"] == "job:7,purpose:eval"
    assert (row["prompt_tokens"], row["completion_tokens"]) == (1700, 300)
    assert (row["cache_read_tokens"], row["cache_write_tokens"]) == (400, 100)
    assert row["cost_usd"] == pytest.approx(want, rel=1e-6) and row["cost_source"] == "litellm", row
    conn = ms.connect()
    try:
        got = api_spend.status(conn, budget=0.01)
        assert got["spent"] == pytest.approx(want) and got["remaining"] == pytest.approx(0.01 - want)
        api_spend.set_start(conn, 0.0)
        conn.execute("UPDATE api_spend SET cost_usd = ?", (api_spend.BUDGET_USD,))
        conn.commit()
    finally:
        conn.close()
    sent = len(Upstream.hits)
    refused = _ask(base, "cloud-opus")
    assert refused.status_code == api_spend.REFUSED_STATUS, refused.text
    assert "api_budget" in refused.text and f"${api_spend.BUDGET_USD:.2f}" in refused.text
    assert len(Upstream.hits) == sent
    assert _ask(base, "sohot-code").status_code == 200
    assert len(_rows(2, timeout=3.0)) == 1
