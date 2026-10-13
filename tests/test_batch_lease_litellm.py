"""#769 inside a real LiteLLM proxy: the batch header reaches the hooks, a second batch is refused, the lease follows the request.

Needs litellm, which the suite does not install: `make test-litellm`.
"""
import json
import os
import socket
import sqlite3
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler
from pathlib import Path

import pytest

pytest.importorskip("litellm", reason="needs litellm: make test-litellm")
httpx = pytest.importorskip("httpx")

from harness import batch  # noqa: E402
from harness.loopback import ThreadingHTTPServer  # noqa: E402

pytestmark = pytest.mark.litellm
REPO = Path(__file__).resolve().parents[1]
KEY = "sk-test-batch"
MODEL = "batch-model"
TTL = 3.0
#: How long a wait for an observed state may take before the test calls it hung.
HUNG_S = 60.0

CALLBACK = '''
import json, sys, time
sys.path.insert(0, {repo!r})
from harness import batch
batch.TTL_S = {ttl}
from gateway import served_model as sm
EVENTS = {events!r}

def ev(kind, data=None, **more):
    data = data or {{}}
    more.update(kind=kind, t=time.time(), call=data.get("litellm_call_id"), batch=sm.batch_of(data))
    with open(EVENTS, "a") as f:
        f.write(json.dumps(more) + "\\n")

_claim, _renew = sm._claim, sm._renew_inflight
def claim(deployment, batch_id):
    got = _claim(deployment, batch_id)
    ev("claim", held_by=got.get("batch", ""), claimed=batch_id)
    return got
async def renew():
    ev("renewer-start")
    try:
        await _renew()
    finally:
        ev("renewer-stop")
sm._claim, sm._renew_inflight = claim, renew

class Recording(sm.ServedModel):
    async def async_pre_call_hook(self, user_api_key_dict, cache, data, call_type):
        ev("pre", data, call_type=call_type)
        return await super().async_pre_call_hook(user_api_key_dict, cache, data, call_type)
    async def async_post_call_success_hook(self, data, user_api_key_dict, response):
        ev("post_success", data)
        return await super().async_post_call_success_hook(data, user_api_key_dict, response)
    async def async_post_call_failure_hook(self, request_data, original_exception, user_api_key_dict,
                                           traceback_str=None):
        ev("post_failure", request_data)
        return await super().async_post_call_failure_hook(request_data, original_exception,
                                                          user_api_key_dict, traceback_str)
    async def async_log_success_event(self, kwargs, response_obj, start_time, end_time):
        ev("log_success", kwargs)
        return await super().async_log_success_event(kwargs, response_obj, start_time, end_time)
    async def async_log_failure_event(self, kwargs, response_obj, start_time, end_time):
        ev("log_failure", kwargs)
        return await super().async_log_failure_event(kwargs, response_obj, start_time, end_time)

proxy_handler_instance = Recording()
'''


def _upstream(hold):
    """Holds only the first request it serves until `hold` is set."""
    served = []

    class Slow(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            served.append(body["model"])
            if len(served) == 1:
                hold.wait(HUNG_S)
            if body.get("stream"):
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                chunk = {"id": "x", "object": "chat.completion.chunk", "created": 1, "model": body["model"],
                         "choices": [{"index": 0, "finish_reason": "stop",
                                      "delta": {"role": "assistant", "content": "ok"}}]}
                self.wfile.write(f"data: {json.dumps(chunk)}\n\ndata: [DONE]\n\n".encode())
                return
            data = json.dumps({"id": "x", "object": "chat.completion", "created": 1, "model": body["model"],
                               "choices": [{"index": 0, "finish_reason": "stop",
                                            "message": {"role": "assistant", "content": "ok"}}],
                               "usage": {"prompt_tokens": 1, "completion_tokens": 1,
                                         "total_tokens": 2}}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
    up = ThreadingHTTPServer(("127.0.0.1", 0), Slow)
    threading.Thread(target=up.serve_forever, daemon=True).start()
    return up


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture
def proxy(tmp_path):
    hold = threading.Event()
    hold.set()
    up = _upstream(hold)
    events = tmp_path / "events.jsonl"
    events.write_text("", encoding="utf-8")
    (tmp_path / "batch_probe.py").write_text(
        CALLBACK.format(repo=str(REPO), ttl=TTL, events=str(events)), encoding="utf-8")
    (tmp_path / "key_auth.py").write_text(
        f"import sys\nsys.path.insert(0, {str(REPO)!r})\n"
        "from gateway.key_auth import user_api_key_auth  # noqa: F401\n", encoding="utf-8")
    cfg = tmp_path / "config.yaml"
    cfg.write_text(f"""model_list:
  - model_name: {MODEL}
    litellm_params:
      model: openai/{MODEL}
      api_base: "http://127.0.0.1:{up.server_address[1]}/v1"
      api_key: not-needed
litellm_settings:
  callbacks: ["batch_probe.proxy_handler_instance"]
  num_retries: 0
general_settings:
  master_key: os.environ/LITELLM_MASTER_KEY
  custom_auth: key_auth.user_api_key_auth
""", encoding="utf-8")
    port = _free_port()
    log = open(tmp_path / "proxy.log", "w", encoding="utf-8")
    proc = subprocess.Popen(
        [str(Path(sys.executable).parent / "litellm"), "--config", str(cfg),
         "--host", "127.0.0.1", "--port", str(port)], cwd=tmp_path,
        env={**os.environ, "LITELLM_MASTER_KEY": KEY, "GATEWAY_CONFIG": str(cfg),
             "LOCALHARNESS_HOME": str(tmp_path / "home"), "PYTHONPATH": str(tmp_path)},
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
    try:
        yield base, lambda: [json.loads(line) for line in events.read_text(encoding="utf-8").splitlines()], \
            hold, tmp_path / "home" / "discovery.db"
    finally:
        hold.set()
        proc.terminate()
        proc.wait(10)
        up.shutdown()


def _ask(base, batch_id, stream):
    body = {"model": MODEL, "messages": [{"role": "user", "content": "hi"}], "stream": stream}
    headers = {"Authorization": f"Bearer {KEY}", batch.HEADER: batch_id}
    if stream:
        with httpx.stream("POST", f"{base}/v1/chat/completions", json=body, headers=headers, timeout=60) as r:
            return r.status_code, "".join(r.iter_lines())
    r = httpx.post(f"{base}/v1/chat/completions", json=body, headers=headers, timeout=60)
    return r.status_code, r.text


def _until(what, pred):
    deadline = time.monotonic() + HUNG_S
    while not (got := pred()):
        assert time.monotonic() < deadline, f"never saw {what}"
        time.sleep(0.05)
    return got


def _leases(db):
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        rows = conn.execute("SELECT value FROM meta WHERE key LIKE 'lease:batch:%'").fetchall()
    finally:
        conn.close()
    return [json.loads(value) for (value,) in rows]


def _claims(seen, batch_id):
    return [e for e in seen if e["kind"] == "claim" and e["claimed"] == batch_id]


def _settled(seen, batch_id):
    """Its renewer has stopped and the claim made when its request finished has landed."""
    ended = [e["t"] for e in seen if e["kind"] == "log_success"]
    return any(e["kind"] == "renewer-stop" for e in seen) and bool(ended) and any(
        e["t"] > ended[0] for e in _claims(seen, batch_id))


@pytest.mark.parametrize("stream", [False, True], ids=["plain", "stream"])
def test_a_second_batch_is_refused_while_the_first_holds_the_lease_through_a_long_reply(proxy, stream):
    base, events, hold, db = proxy
    first = {}
    hold.clear()
    t = threading.Thread(target=lambda: first.update(got=_ask(base, "batch-a", stream)))
    t.start()
    # Order, not a sleep: batch-b goes only once batch-a is seen holding the lease. #844.
    taken = _until("batch-a take the lease", lambda: [e for e in _claims(events(), "batch-a") if not e["held_by"]])
    code, text = _ask(base, "batch-b", stream)
    assert code == 503 and batch.BUSY in text and "batch-a" in text, text
    # The reply stays in flight until the renewer has kept the lease past the TTL it was taken with.
    _until("batch-a renewed past its first TTL",
           lambda: [e for e in _claims(events(), "batch-a") if e["t"] > taken[0]["t"] + TTL])
    hold.set()
    t.join()
    assert first["got"][0] == 200, first["got"]
    _until("batch-a's renewer stop and its finishing claim", lambda: _settled(events(), "batch-a"))
    _until("batch-a's lease lapse", lambda: all(
        lease["expires"] <= time.time() for lease in _leases(db)))
    assert _ask(base, "batch-b", stream)[0] == 200
    _until("batch-b's renewer stop", lambda: len([e for e in events() if e["kind"] == "renewer-stop"]) == 2)

    seen = events()
    pre = [e for e in seen if e["kind"] == "pre"]
    assert [e["batch"] for e in pre] == ["batch-a", "batch-b", "batch-b"]
    a_call = pre[0]["call"]
    assert a_call and all(e["call_type"] == "acompletion" for e in pre)
    # The reply outlived TTL, so only the in-flight renewer kept batch-a's lease.
    renewals = [e for e in seen if e["kind"] == "claim" and e["claimed"] == "batch-a"]
    assert len(renewals) >= 3 and not any(e["held_by"] for e in renewals)
    # The log event names the call but carries no headers: the lease is found by litellm_call_id.
    done = [e for e in seen if e["kind"] == "log_success" and e["call"] == a_call]
    assert done and done[0]["batch"] == ""
    assert any(e["kind"] == "post_success" and e["call"] == a_call for e in seen) is not stream
    refused = pre[1]["call"]
    assert any(e["kind"] == "post_failure" and e["call"] == refused and e["batch"] == "batch-b" for e in seen)
    starts = [e for e in seen if e["kind"] == "renewer-start"]
    stops = [e for e in seen if e["kind"] == "renewer-stop"]
    assert len(starts) == len(stops) == 2
