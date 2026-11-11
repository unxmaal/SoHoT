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
from harness import node_reach  # noqa: E402
from harness import nodes as nodes_mod  # noqa: E402
from harness.loopback import ThreadingHTTPServer  # noqa: E402

pytestmark = pytest.mark.litellm
REPO = Path(__file__).resolve().parents[1]
KEY = "sk-test-node"
NODE_KEY = "node-secret"
MODEL = "Qwen2.5-7B-Instruct-Q4_K_M"
TIMEOUT = 3
#: A message the fake node answers with HTTP 500, whatever name asked for it. #1810.
FAIL = "fail-this-one"


def _server(who, seen, first_delay=0.0, failing=None, fail_on=None):
    class Upstream(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            seen.append(self.headers.get("Authorization", ""))
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if (failing is not None and failing.is_set()) or body["messages"][-1]["content"] == fail_on:
                self.send_response(500)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if len(seen) == 1 and first_delay:
                time.sleep(first_delay)
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


class Drops:
    """Takes every connection and closes it on the first bytes of a request, answering nothing."""

    def __init__(self):
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(64)
        self.port = self.sock.getsockname()[1]
        self.requests = 0
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        try:
            while True:
                conn = self.sock.accept()[0]
                threading.Thread(target=self._drop, args=(conn,), daemon=True).start()
        except OSError:
            return

    def _drop(self, conn):
        with conn:
            if conn.recv(65536):
                self.requests += 1

    def close(self):
        self.sock.close()


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


def _proxy(tmp_path, node_base, extra=(), cooldown=30):
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
        "connect_timeout": 1, "timeout": TIMEOUT, "cooldown": cooldown}]})
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


def _ask(base, model=MODEL, stream=False, content="hi"):
    started = time.monotonic()
    body = {"model": model, "messages": [{"role": "user", "content": content}]}
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
        code, h, text, _ = _ask(base, stream=stream)
        assert code == 200 and "from-studio" in text, text
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
        assert took > TIMEOUT - 0.5
        assert h["x-sohot-fallback"] == "pc"
        dialled = len(hung.held)
        code, h, text, _ = _ask(base, stream=True)
        assert "from-studio" in text
        code, h, text, _ = _ask(base, "eval-7b")
        assert "from-studio" in text
        assert len(hung.held) == dialled, "the hung node was dialled again inside its cooldown"
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
    assert took >= 2.0 and len(node_seen) == 1
    code, h, text, _ = _ask(base)
    assert "from-node" in text and h["x-sohot-node"] == "pc" and len(node_seen) == 2
    node.shutdown()


def test_a_down_node_model_with_no_local_copy_is_refused_at_once(tmp_path, stop):
    """#823: it waited out the connect timeout and retries, then answered a bare 500."""
    base, proc, _, studio_seen, _ = _proxy(tmp_path, f"http://127.0.0.1:{_free_port()}/v1",
                                          extra=("node-only-14b",))
    stop(proc)
    code, _, text, _ = _ask(base, "node-only-14b")
    # The pre-call hook's own refusal; #823's retries ended in a bare 500.
    assert code == 503, text
    assert "node pc is down" in text and "no copy of node-only-14b" in text
    assert not studio_seen


def test_a_node_that_failed_and_recovered_is_routed_again_under_steady_traffic(tmp_path, stop):
    """#1808: requests the gateway sends to this machine while the node is held out must not extend its cooldown."""
    failing, node_seen, cooldown = threading.Event(), [], 3
    failing.set()
    node = _server("from-node", node_seen, failing=failing)
    base, proc, *_ = _proxy(tmp_path, f"http://127.0.0.1:{node.server_address[1]}/v1", cooldown=cooldown)
    stop(proc)
    code, h, text, _ = _ask(base)
    assert code == 200 and "from-studio" in text and h["x-sohot-fallback"] == "pc", text
    failed, failing_seen = time.monotonic(), len(node_seen)
    failing.clear()
    served_by = []
    for _ in range(int(cooldown * 4 / 0.5)):
        time.sleep(0.5)
        code, h, text, _ = _ask(base)
        served_by.append((time.monotonic() - failed, "from-node" in text))
        if "from-node" in text:
            break
    assert served_by[-1][1], f"steady traffic kept the recovered node out: {served_by}"
    assert served_by[-1][0] < cooldown * 2, served_by
    assert all(not by_node for _, by_node in served_by[:-1]) and len(node_seen) == failing_seen + 1
    node.shutdown()



def test_a_server_error_for_one_name_leaves_the_others_on_the_node(tmp_path, stop):
    """#1810: the node answered 500 for one name; its other names keep going to it, the failed one does not."""
    node_seen = []
    node = _server("from-node", node_seen, fail_on=FAIL)
    base, proc, _, studio_seen, _ = _proxy(tmp_path, f"http://127.0.0.1:{node.server_address[1]}/v1")
    stop(proc)
    code, h, text, _ = _ask(base, content=FAIL)
    assert code == 200 and "from-studio" in text and h["x-sohot-fallback"] == "pc", text
    tried = len(node_seen)
    code, h, text, _ = _ask(base, "eval-7b")
    assert code == 200 and "from-node" in text and h["x-sohot-node"] == "pc", "a 500 for one name downed the node"
    code, h, text, _ = _ask(base)
    assert "from-studio" in text and h["x-sohot-fallback"] == "pc"
    assert len(node_seen) == tried + 1, "the name that failed was sent to the node again inside its cooldown"
    rows = node_reach.read()
    assert [(r["node"], r.get("model"), r["state"]) for r in rows] == [("pc", MODEL, "down")], rows
    assert rows[0]["why"] == f"{MODEL} answered InternalServerError 500"
    node.shutdown()


def test_a_node_that_drops_the_request_takes_every_name_out(tmp_path, stop):
    """#1810: no answer at all is the node's fault, not the name's."""
    drops = Drops()
    try:
        base, proc, *_ = _proxy(tmp_path, f"http://127.0.0.1:{drops.port}/v1")
        stop(proc)
        code, h, text, _ = _ask(base)
        assert code == 200 and "from-studio" in text and h["x-sohot-fallback"] == "pc", text
        dialled = drops.requests
        code, h, text, _ = _ask(base, "eval-7b")
        assert "from-studio" in text and h["x-sohot-fallback"] == "pc"
        assert drops.requests == dialled, "a node that dropped a request was sent another name at once"
        rows = node_reach.read()
        assert [(r["node"], r.get("model"), r["state"]) for r in rows] == [("pc", None, "down")], rows
        assert rows[0]["why"] == f"{MODEL} fell back: InternalServerError 500, no answer from the node", rows
    finally:
        drops.close()
