"""#1012: a router restart returns only once the router answers, so the screen after a fetch is not refused."""
import json
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler
from pathlib import Path

import pytest

from evals.runners.text import CompletionRunner
from harness import downloads, fetching, gguf, router
from harness import memory_store as ms
from harness.loopback import ThreadingHTTPServer

#: The real one: conftest swaps the module attribute for a stub in every test.
REFRESH = gguf.refresh_router
#: Likewise router._get, so the stub router on this test's own port is asked over HTTP.
GET = router._get
GIB = 1024 ** 3
STEM = "Nemo-4B-Q4_K_M"


class Router(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, port, loading=0, listed=(STEM,)):
        super().__init__(("127.0.0.1", port), Handler)
        self.loading = loading
        self.listed = list(listed)
        self.health = 0


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        s = self.server
        if self.path == "/health":
            s.health += 1
            if s.health <= s.loading:
                return self._send(503, {"error": {"message": "Loading model"}})
            return self._send(200, {"status": "ok"})
        if self.path == "/models":
            return self._send(200, {"data": [{"id": m, "status": {"value": "unloaded"}}
                                             for m in s.listed]})
        self._send(404, {})

    def do_POST(self):
        self.rfile.read(int(self.headers["Content-Length"]))
        self._send(200, {"choices": [{"message": {"role": "assistant", "content": "ok"},
                                      "finish_reason": "stop"}],
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


def _restart_that_comes_up_late(free, servers, after_s=0.6, loading=2):
    """A restart that returns at once, as kickstart -k does, and binds the port later."""
    argv = []

    def run(cmd, check=False):
        argv.append(cmd)

        def bind():
            time.sleep(after_s)
            srv = Router(free, loading=loading)
            servers.append(srv)
            srv.serve_forever()
        threading.Thread(target=bind, daemon=True).start()
    return run, argv


def test_the_screen_warm_up_after_a_router_restart_is_not_refused(port):
    free, servers = port
    run, argv = _restart_that_comes_up_late(free, servers)
    why = REFRESH(expect=(STEM,), run=run)
    CompletionRunner(router.url(), STEM).warm()
    assert why == "" and argv and servers[0].health > servers[0].loading


def test_a_router_that_never_answers_is_named_when_the_wait_gives_up(port, monkeypatch, capsys):
    monkeypatch.setattr(gguf, "READY_TIMEOUT_S", 0.3)
    monkeypatch.setattr(gguf, "READY_POLL_S", 0.05)
    why = REFRESH(expect=(STEM,), run=lambda cmd, check=False: None)
    assert router.url() in why and "0.3 s" in why and STEM in why
    assert why in capsys.readouterr().err


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


def _get(listed_from=3):
    calls = {"/health": 0, "/models": 0}

    def get(path):
        calls[path] += 1
        if path == "/health":
            return {"status": "ok"}
        return {"data": [{"id": STEM, "status": "unloaded"}] if calls[path] >= listed_from else []}
    return get, calls


def test_a_router_that_answers_before_it_lists_the_new_file_is_waited_for():
    get, calls = _get(listed_from=3)
    clock = Clock()
    assert gguf.wait_router((STEM,), timeout=10, get=get, clock=clock, sleep=clock.sleep) == ""
    assert calls["/models"] == 3


def test_the_wait_gives_up_at_its_timeout_and_names_the_missing_file():
    get, _ = _get(listed_from=10 ** 6)
    clock = Clock()
    why = gguf.wait_router((STEM,), timeout=2, get=get, clock=clock, sleep=clock.sleep)
    assert f"listing {STEM}" in why and "within 2 s" in why
    assert 2 <= clock.t <= 2 + gguf.READY_POLL_S


def test_a_router_still_loading_is_not_ready():
    def get(path):
        raise OSError("HTTP Error 503: Service Unavailable")
    assert not gguf.router_ready((), get)
    assert gguf.router_ready((), lambda p: {"status": "ok"})
    assert not gguf.router_ready((), lambda p: {"status": "loading"})


@pytest.mark.parametrize("platform", ["darwin", "linux", "win32"])
def test_every_platform_waits_after_its_restart(platform, monkeypatch):
    """Read at call time: services.sh restart backgrounds the server as kickstart -k does."""
    monkeypatch.setattr(sys, "platform", platform)
    order = []
    REFRESH(expect=(STEM,), run=lambda cmd, check=False: order.append(("run", cmd)),
            wait=lambda expect: order.append(("wait", expect)) or "")
    assert [o[0] for o in order] == ["run", "wait"]
    assert order[0][1] == gguf.router_restart_argv(platform)
    assert order[1][1] == (STEM,)


@pytest.fixture
def models(tmp_path, monkeypatch):
    monkeypatch.setenv("HF_HOME", str(tmp_path / "hf"))
    monkeypatch.setenv("LLAMACPP_MODELS_DIR", str(tmp_path / "gguf"))
    return tmp_path


def test_a_fetched_file_is_what_the_restart_waits_to_see(models, _no_real_services):
    gguf.download("org/M", "M-Q4_K_M.gguf", hf_download=lambda r, f, d: str(Path(d) / f))
    assert _no_real_services == [("M-Q4_K_M",)]


def test_a_hub_download_adopted_at_the_start_of_a_fetch_is_waited_for_by_its_stem(
        models, _no_real_services):
    import fakes
    snap = downloads.hub_dir("org/A-GGUF") / "snapshots" / "abc"
    snap.mkdir(parents=True)
    (snap / "A-Q4_K_M.gguf").write_bytes(b"x" * 64)
    fakes.hub_ref(snap)
    conn = ms.connect()
    ms.record(conn, ms.Seen(name="org/A-GGUF", source="t", lane="code"))
    downloads.record(conn, "org/A-GGUF", downloads.HUB, snap.parent.parent)
    assert gguf.adopt_pending(conn) == ["org/A-GGUF"]
    assert _no_real_services == [("A-Q4_K_M",)]
    conn.close()


def test_a_whole_gguf_repo_fetched_by_the_loop_restarts_the_router_before_the_screen(
        models, monkeypatch, _no_real_services):
    """The loop's fetch tier linked the file and never restarted, so its screen met a router without it."""
    monkeypatch.setattr(fetching.rank, "unrunnable", lambda row, m=None: "")
    db = ms.connect()
    ms.record(db, ms.Seen(name="org/Nemo-4B", source="t", resolved="org/Nemo-4B",
                          kind="weights", lane="code"))
    ms.set_size(db, "org/Nemo-4B", GIB)
    ms.decide(db, "org/Nemo-4B", "queued", tier="inspect", size_bytes=GIB)

    def snapshot(repo_id, **kw):
        import fakes
        snap = downloads.hub_dir(repo_id) / "snapshots" / "abc"
        snap.mkdir(parents=True)
        (snap / f"{STEM}.gguf").write_bytes(b"GGUF" * 64)
        fakes.hub_ref(snap)
        return snap

    done = fetching.run(db, snapshot=snapshot, free=900 * GIB)
    assert done[0]["ok"], done
    assert gguf.fetched("org/Nemo-4B", db) == STEM
    assert _no_real_services == [(STEM,)]
    db.close()
