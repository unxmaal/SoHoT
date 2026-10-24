"""#1181: an eval queued behind a router restart waits for the router instead of recording every case refused."""
import json
import os
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler
from pathlib import Path

import httpx
import pytest

from evals import run
from evals.core import Case
from evals.runners.base import RunnerError
from evals.runners.text import CompletionRunner
from harness import completion, exclusive, gguf, router
from harness.loopback import ThreadingHTTPServer

#: The real one: conftest swaps the module attribute for a stub in every test.
REFRESH = gguf.refresh_router
GET = router._get
STEM = "Qwopus-27B-Q4_K_M"
REPO = Path(__file__).resolve().parents[1]


class Router(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, port):
        super().__init__(("127.0.0.1", port), Handler)
        self.posts = 0


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, body):
        data = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/health":
            return self._send({"status": "ok"})
        self._send({"data": [{"id": STEM, "status": {"value": "unloaded"}}]})

    def do_POST(self):
        self.rfile.read(int(self.headers["Content-Length"]))
        self.server.posts += 1
        self._send({"choices": [{"message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6}})


@pytest.fixture
def port(monkeypatch):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        free = s.getsockname()[1]
    monkeypatch.setenv("LLAMACPP_PORT", str(free))
    monkeypatch.setattr(router, "_get", GET)
    servers = []
    yield free, servers
    for srv in servers:
        srv.shutdown()
        srv.server_close()


def _bind_later(free, servers, after_s):
    def bind():
        time.sleep(after_s)
        srv = Router(free)
        servers.append(srv)
        srv.serve_forever()
    threading.Thread(target=bind, daemon=True).start()


class Warming:
    """Job 0141's runner: the real warm-up against the router, and a case that passes once it answered."""
    candidate = "fake"

    def __init__(self, base):
        self.inner = CompletionRunner(base, STEM)

    def warm(self):
        self.inner.warm()

    def run(self, case):
        from evals.core import Result
        return Result(case.id, self.candidate, True, 0.1, 0, "")

    def failed(self, case, exc):
        from evals.core import Result
        return Result(case.id, self.candidate, False, 0.0, 0, exc.detail)

    def artifact(self, case, suffix):
        return f"{case.id}{suffix}"


def test_a_job_that_starts_while_the_router_restarts_waits_for_it(port, monkeypatch, tmp_path):
    free, servers = port
    monkeypatch.setattr(run, "warm", run.warm.real)
    monkeypatch.setattr(run, "GATEWAY_DOWN_POLL_S", 0.05)
    _bind_later(free, servers, 0.5)
    rows = []
    case = Case(id="sohot-363-spec", modality="code", prompt="p")
    run._run_candidate(run.parse_args([]), "fake", Warming(router.url()), [case], rows, tmp_path)
    (row,) = rows
    assert row.passed, row.detail
    assert servers and servers[0].posts == 1


class Refusing:
    def __init__(self, exc_for):
        self.exc_for, self.calls = exc_for, 0

    def warm(self):
        self.calls += 1
        try:
            raise self.exc_for()
        except completion.CompletionError as exc:
            raise RunnerError(f"warm-up: {exc}", failure_class=exc.failure_class) from exc


def _connect_refused():
    try:
        raise httpx.ConnectError("[Errno 61] Connection refused")
    except httpx.ConnectError as exc:
        try:
            raise completion.CompletionError("gateway unreachable at http://127.0.0.1:8082",
                                             "refused_by_gateway") from exc
        except completion.CompletionError as wrapped:
            return wrapped


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


def test_a_router_that_never_comes_back_fails_the_warm_up_at_the_bound(monkeypatch, capsys):
    monkeypatch.setattr(run, "GATEWAY_DOWN_WAIT_S", 5.0)
    clock, runner = Clock(), Refusing(_connect_refused)
    with pytest.raises(RunnerError, match="gateway unreachable"):
        run.warm(runner, clock=clock, sleep=clock.sleep)
    assert 5.0 <= clock.t <= 5.0 + run.GATEWAY_DOWN_POLL_S
    assert runner.calls == int(5.0 / run.GATEWAY_DOWN_POLL_S) + 1
    assert "waiting up to 5 s" in capsys.readouterr().err


def test_a_gateway_that_answers_with_a_refusal_is_not_waited_for():
    clock = Clock()
    runner = Refusing(lambda: completion.CompletionError("gateway returned HTTP 400: model not found",
                                                         "refused_by_gateway"))
    with pytest.raises(RunnerError, match="HTTP 400"):
        run.warm(runner, clock=clock, sleep=clock.sleep)
    assert runner.calls == 1 and clock.t == 0.0


def test_unreachable_is_a_refused_connection_anywhere_in_the_chain():
    assert completion.unreachable(_connect_refused())
    assert not completion.unreachable(RunnerError("x"))
    timed = completion.CompletionError("timed out", "timeout")
    timed.__cause__ = httpx.ReadTimeout("slow")
    assert not completion.unreachable(timed)
    loop = completion.CompletionError("a")
    loop.__context__ = loop
    assert not completion.unreachable(loop)


def test_a_router_restart_holds_the_machine_lock_until_the_router_answers():
    """The 2026-10-23 sweep: with-gpu-lock let go when kickstart returned, and job 0141 took the lock."""
    seen = []
    REFRESH(expect=(STEM,),
            run=lambda cmd, check=False: seen.append(("restart", exclusive._taken(exclusive.lock_path()))),
            wait=lambda expect: seen.append(("wait", exclusive._taken(exclusive.lock_path()))) or "")
    assert seen == [("restart", True), ("wait", True)]
    assert not exclusive._taken(exclusive.lock_path())


def test_the_restart_s_own_with_gpu_lock_does_not_wait_on_its_parent():
    got = []

    def nested(cmd, check=False):
        got.append(subprocess.run([sys.executable, str(REPO / "scripts" / "with-gpu-lock"),
                                   sys.executable, "-c", "pass"], timeout=60, env=os.environ.copy()).returncode)
    REFRESH(run=nested, wait=lambda expect: "")
    assert got == [0]
