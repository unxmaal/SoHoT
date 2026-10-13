"""#684 inside a real LiteLLM proxy: a node serves its model; unreachable, refused or hung, this machine does.

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

from harness import gateway  # noqa: E402
from harness import nodes as nodes_mod  # noqa: E402
from harness.loopback import ThreadingHTTPServer  # noqa: E402

pytestmark = pytest.mark.litellm
REPO = Path(__file__).resolve().parents[1]
KEY = "sk-test-node"
NODE_KEY = "node-secret"
MODEL = "Qwen2.5-7B-Instruct-Q4_K_M"
TIMEOUT = 3


def _server(who, seen, first_delay=0.0):
    class Upstream(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            seen.append(self.headers.get("Authorization", ""))
            if len(seen) == 1 and first_delay:
                time.sleep(first_delay)
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if body.get("stream"):
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                chunk = {"id": "x", "object": "chat.completion.chunk", "created": 1,
                         "model": body["model"], "choices": [{
                             "index": 0, "finish_reason": "stop",
                             "delta": {"role": "assistant", "content": who}}]}
                self.wfile.write(f"data: {json.dumps(chunk)}\n\ndata: [DONE]\n\n".encode())
                return
            data = json.dumps({"id": "x", "object": "chat.completion", "created": 1,
                               "model": body["model"],
                               "choices": [{"index": 0, "finish_reason": "stop",
                                            "message": {"role": "assistant", "content": who}}],
                               "usage": {"prompt_tokens": 1, "completion_tokens": 1,
                                         "total_tokens": 2}}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
    up = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
    threading.Thread(target=up.serve_forever, daemon=True).start()
    return up


class Hung:
    """Accepts every connection and never answers."""

    def __init__(self):
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(64)
        self.port = self.sock.getsockname()[1]
        self.held = []
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        try:
            while True:
                self.held.append(self.sock.accept()[0])
        except OSError:
            return

    def close(self):
        for c in self.held:
            c.close()
        self.sock.close()


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _proxy(tmp_path, node_base, extra=()):
    studio_seen, node_seen = [], []
    studio = _server("from-studio", studio_seen)
    for mod, name in (("usage_log", "proxy_handler_instance"), ("key_auth", "user_api_key_auth"),
                      ("served_model", "proxy_handler_instance"),
                      ("schema_guard", "proxy_handler_instance")):
        (tmp_path / f"{mod}.py").write_text(
            f"import sys\nsys.path.insert(0, {str(REPO)!r})\n"
            f"from gateway.{mod} import {name}  # noqa: F401\n", encoding="utf-8")
    cfg = tmp_path / "config.yaml"
    cfg.write_text(f"""model_list:
  - model_name: {MODEL}
    engine: llama-server
    litellm_params: &q7
      model: openai/{MODEL}
      api_base: "http://127.0.0.1:{studio.server_address[1]}/v1"
      api_key: not-needed
  - model_name: eval-7b
    deprecated_for: {MODEL}
    litellm_params: *q7
litellm_settings:
  callbacks: ["schema_guard.proxy_handler_instance", "usage_log.proxy_handler_instance",
              "served_model.proxy_handler_instance"]
  num_retries: 0
general_settings:
  master_key: os.environ/LITELLM_MASTER_KEY
  custom_auth: key_auth.user_api_key_auth
""", encoding="utf-8")
    nodes = nodes_mod.parse({"nodes": [{
        "name": "pc", "api_base": node_base, "engine": "llama-server", "models": [MODEL, *extra],
        "key": "env:TEST_NODE_KEY", "machine": "PC1/Windows/x86_64/abc123",
        "connect_timeout": 1, "timeout": TIMEOUT, "cooldown": 30}]})
    served = gateway.write_served(cfg, defaults={}, nodes=nodes)
    port = _free_port()
    log = open(tmp_path / "proxy.log", "w", encoding="utf-8")
    exe = Path(sys.executable).parent / "litellm"
    proc = subprocess.Popen(
        [str(exe), "--config", str(served), "--host", "127.0.0.1", "--port", str(port)],
        env={**os.environ, "LITELLM_MASTER_KEY": KEY, "GATEWAY_CONFIG": str(cfg),
             "TEST_NODE_KEY": NODE_KEY},
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
        pytest.fail((tmp_path / "proxy.log").read_text(encoding="utf-8"))
    return base, proc, studio, studio_seen, node_seen


def _ask(base, model=MODEL, stream=False):
    started = time.monotonic()
    body = {"model": model, "messages": [{"role": "user", "content": "hi"}]}
    if stream:
        body["stream"] = True
        with httpx.stream("POST", f"{base}/v1/chat/completions", timeout=60, json=body,
                          headers={"Authorization": f"Bearer {KEY}"}) as r:
            text = "".join(r.iter_lines())
            return r.status_code, r.headers, text, time.monotonic() - started
    r = httpx.post(f"{base}/v1/chat/completions", timeout=60, json=body,
                   headers={"Authorization": f"Bearer {KEY}"})
    return r.status_code, r.headers, r.text, time.monotonic() - started


@pytest.fixture
def stop():
    procs = []
    yield procs.append
    for p in procs:
        p.terminate()
        p.wait(10)


def test_the_node_serves_its_model_with_its_key_and_says_so(tmp_path, stop):
    node_seen = []
    node = _server("from-node", node_seen)
    base, proc, *_ = _proxy(tmp_path, f"http://127.0.0.1:{node.server_address[1]}/v1")
    stop(proc)
    for model in (MODEL, "eval-7b"):
        code, h, text, _ = _ask(base, model)
        assert code == 200 and "from-node" in text, text
        assert h["x-sohot-node"] == "pc"
        assert h["x-sohot-machine"] == "PC1/Windows/x86_64/abc123"
        assert h["x-sohot-model"] == MODEL
        assert h["x-sohot-served-as"] == f"{model}@pc"
    code, h, text, _ = _ask(base, stream=True)
    assert "from-node" in text and h["x-sohot-node"] == "pc"
    assert node_seen and set(node_seen) == {f"Bearer {NODE_KEY}"}
    node.shutdown()


def test_an_unreachable_node_falls_back_to_this_machine_within_the_connect_timeout(tmp_path, stop):
    base, proc, _, studio_seen, _ = _proxy(tmp_path, f"http://127.0.0.1:{_free_port()}/v1")
    stop(proc)
    for stream in (False, True):
        code, h, text, took = _ask(base, stream=stream)
        assert code == 200 and "from-studio" in text, text
        assert took < 1 + 2
        assert h["x-sohot-fallback"] == "pc" and "x-sohot-node" not in h
        assert h["x-sohot-model"] == MODEL
    code, h, text, _ = _ask(base, "eval-7b")
    assert "from-studio" in text and h["x-sohot-served-as"] == "eval-7b"
    assert studio_seen


def test_a_hung_node_falls_back_after_the_request_timeout_then_is_skipped(tmp_path, stop):
    hung = Hung()
    try:
        base, proc, *_ = _proxy(tmp_path, f"http://127.0.0.1:{hung.port}/v1")
        stop(proc)
        code, h, text, took = _ask(base)
        assert code == 200 and "from-studio" in text, text
        assert TIMEOUT - 0.5 < took < TIMEOUT + 3
        assert h["x-sohot-fallback"] == "pc"
        code, h, text, took = _ask(base, stream=True)
        assert "from-studio" in text and took < 1.5
        code, h, text, took = _ask(base, "eval-7b")
        assert "from-studio" in text and took < 1.5
    finally:
        hung.close()


def test_a_node_reloading_after_idle_answers_late_and_still_serves(tmp_path, stop):
    """--sleep-idle-seconds: the first request after idle waits on a reload; that is not a failure."""
    node_seen = []
    node = _server("from-node", node_seen, first_delay=2.0)
    base, proc, *_ = _proxy(tmp_path, f"http://127.0.0.1:{node.server_address[1]}/v1")
    stop(proc)
    code, h, text, took = _ask(base)
    assert code == 200 and "from-node" in text, text
    assert h["x-sohot-node"] == "pc" and "x-sohot-fallback" not in h
    assert 2.0 <= took < TIMEOUT
    code, h, text, took = _ask(base)
    assert "from-node" in text and took < 1.0
    node.shutdown()


def test_a_down_node_model_with_no_local_copy_is_refused_at_once(tmp_path, stop):
    """#823: it waited out the connect timeout and retries, then answered a bare 500."""
    base, proc, _, studio_seen, _ = _proxy(tmp_path, f"http://127.0.0.1:{_free_port()}/v1",
                                          extra=("node-only-14b",))
    stop(proc)
    code, _, text, took = _ask(base, "node-only-14b")
    assert code == 503, text
    assert "node pc is down" in text and "no copy of node-only-14b" in text
    assert took < 1 + 2
    assert not studio_seen
