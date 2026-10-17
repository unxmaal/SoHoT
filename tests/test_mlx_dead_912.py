"""A live mlx_lm.server whose generation thread died is restarted by the watchdog and named by soh morning (#912)."""
import http.server
import inspect
import json
import subprocess
import threading
import time

import pytest

from harness import memory_store as ms
from harness import loopback, mlx_server, morning, serving
from harness import watchdog as wd
from harness.commands import morning as morning_cmd

NIGHT = time.mktime((2026, 10, 17, 1, 30, 0, 0, 0, -1))


class Stub(http.server.BaseHTTPRequestHandler):
    """Answers as mlx-lm 0.32.0 does once its generation thread died, or as a healthy one."""
    dead = True

    def _send(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/health":
            self._send(503, {"status": "unavailable"}) if self.dead else self._send(200, {"status": "ok"})
        else:
            self._send(404, {})

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        if self.dead:
            self._send(404, {"error": "generation thread died"})
        else:
            self._send(200, {"choices": [{"message": {"content": "x"}}]})

    def log_message(self, *a):
        pass


@pytest.fixture
def stub():
    def start(dead=True):
        handler = type("S", (Stub,), {"dead": dead})
        srv = loopback.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        servers.append(srv)
        return f"http://127.0.0.1:{srv.server_address[1]}"
    servers = []
    yield start
    for s in servers:
        s.shutdown()
        s.server_close()


class Loaded(wd.Probes):
    """Real probes except the process table and launchd, which say only that the mlx unit is loaded."""

    def __init__(self, tmp_path):
        self.tmp = tmp_path

    def processes(self):
        return []

    def launchd_loaded(self, service):
        return service == "mlx"

    def launchd_pid(self, service):
        return None

    def heartbeat(self):
        return None

    def job_pids(self):
        return {}

    def progress(self, evals):
        return []

    def lock(self):
        return {}

    def resident(self):
        return []

    def pressure(self):
        return None

    def gateway_up(self):
        return None

    def fallbacks(self, conn):
        return []

    def state(self):
        d = self.tmp / "wd"
        d.mkdir(exist_ok=True)
        return d


def _launchctl():
    calls = []

    def run(argv, **kw):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, "", "")
    return calls, run


def test_generating_reads_mlx_lm_s_own_health(stub):
    assert mlx_server.generating(stub(dead=True), 5.0) is False
    assert mlx_server.generating(stub(dead=False), 5.0) is True
    assert mlx_server.generating("http://127.0.0.1:9", 5.0) is None


def test_a_stub_server_that_says_its_generation_thread_died_is_restarted_by_the_watchdog(tmp_path, monkeypatch, stub):
    monkeypatch.setattr(serving, "MLX_URL", stub(dead=True))
    calls, run = _launchctl()
    conn = ms.connect()
    got = wd.wake(conn, Loaded(tmp_path), wd.Hands(run=run, platform="darwin"), act=True, now=NIGHT, say=lambda m: None)
    assert [(a["criterion"], a["action"], a["outcome"]) for a in got["acted"]] == [("mlx_dead", wd.RESTART,
                                                                                    "restarted mlx")]
    assert calls == [["launchctl", "kickstart", "-k", f"gui/{wd.os.getuid()}/{wd.LABEL}.mlx"]]
    row = conn.execute("SELECT criterion, subject, action, dry_run, outcome FROM watchdog_actions").fetchall()
    assert [tuple(r) for r in row] == [("mlx_dead", "mlx", wd.RESTART, 0, "restarted mlx")]


def test_a_healthy_or_unloaded_mlx_unit_is_left_alone(tmp_path, monkeypatch, stub):
    monkeypatch.setattr(serving, "MLX_URL", stub(dead=False))
    calls, run = _launchctl()
    conn = ms.connect()
    assert wd.wake(conn, Loaded(tmp_path), wd.Hands(run=run), act=True, now=NIGHT, say=lambda m: None)["acted"] == []
    monkeypatch.setattr(serving, "MLX_URL", stub(dead=True))
    monkeypatch.setattr(Loaded, "launchd_loaded", lambda self, s: False)
    got = wd.wake(conn, Loaded(tmp_path), wd.Hands(run=run), act=True, now=NIGHT, say=lambda m: None)
    assert got["acted"] == [] and "mlx_dead" in got["skipped"] and calls == []


def test_a_server_that_does_not_answer_is_not_restarted(tmp_path, monkeypatch):
    """A refused connection is a unit mid-start; restarting it then would loop."""
    monkeypatch.setattr(serving, "MLX_URL", "http://127.0.0.1:9")
    calls, run = _launchctl()
    got = wd.wake(ms.connect(), Loaded(tmp_path), wd.Hands(run=run), act=True, now=NIGHT, say=lambda m: None)
    assert got["acted"] == [] and "mlx_dead" in got["skipped"] and calls == []


def test_a_restart_that_did_not_fix_it_escalates_to_a_person(tmp_path, monkeypatch, stub):
    monkeypatch.setattr(serving, "MLX_URL", stub(dead=True))
    calls, run = _launchctl()
    conn = ms.connect()
    hands = wd.Hands(run=run, platform="darwin")
    actions = [wd.wake(conn, Loaded(tmp_path), hands, act=True, now=NIGHT + 300 * i, say=lambda m: None)["acted"][0]
               for i in range(wd.ESCALATE_AFTER + 1)]
    assert [a["action"] for a in actions] == [wd.RESTART] * wd.ESCALATE_AFTER + [wd.NOTIFY]
    assert actions[-1]["escalated"]


def test_restarting_mlx_off_macos_is_refused():
    calls, run = _launchctl()
    f = wd.Finding("mlx_dead", wd.Subject("server", "mlx", "t", detail={"service": "mlx"}), {})
    assert wd.Hands(run=run, platform="linux").do(wd.RESTART, f).startswith("refused") and calls == []


def test_the_prompt_cache_is_capped_unless_the_caller_set_a_cap():
    got = mlx_server.cache_caps(["--model", "m"])
    assert got == ["--model", "m", "--prompt-cache-size", str(mlx_server.PROMPT_CACHE_SIZE),
                   "--prompt-cache-bytes", mlx_server.PROMPT_CACHE_BYTES]
    mine = mlx_server.cache_caps(["--prompt-cache-size=2", "--prompt-cache-bytes", "1GB"])
    assert mine == ["--prompt-cache-size=2", "--prompt-cache-bytes", "1GB"]


def test_the_installed_mlx_lm_takes_the_cap_flags_and_says_503_when_generation_died():
    server = pytest.importorskip("mlx_lm.server")
    main = inspect.getsource(server.main)
    assert '"--prompt-cache-size"' in main and '"--prompt-cache-bytes"' in main
    utils = pytest.importorskip("mlx_lm.utils")
    assert utils._parse_size(mlx_server.PROMPT_CACHE_BYTES) == 8 * 10**9
    health = inspect.getsource(server.APIHandler.handle_health_check)
    assert "503" in health and "is_healthy" in health
    assert "_generation_failed" in inspect.getsource(server.ResponseGenerator.generation_available)


# --- soh morning ---------------------------------------------------------------

def _gather(health):
    conn = ms.connect()
    return morning.gather(conn, NIGHT + 6 * 3600, NIGHT - 6 * 3600, beat={}, gh=lambda argv: "[]",
                          git=lambda argv: "", where=None, lanes=lambda c: [], health=health)


def test_morning_names_a_dead_lane_as_its_own_line_and_does_not_ask_it(monkeypatch, stub):
    base = stub(dead=True)
    from harness import delegate
    monkeypatch.setattr(delegate, "route", lambda lane: ("mlx-community/Qwen2.5-7B-Instruct-4bit",
                                                         serving.Route(base, "m", {})))
    monkeypatch.setattr(delegate, "upstream", lambda where: (base, "m"))
    monkeypatch.setattr(serving, "engine_at", lambda b, config=None: serving.DEFAULT)
    r = _gather(morning.lane_health)
    assert r["lane"]["generating"] is False
    assert r["needs"][0].startswith("the extract lane cannot generate: mlx-community/Qwen2.5-7B-Instruct-4bit at "
                                    f"{base} says its generation thread died")
    head = morning.headline(r, "facts", ask=lambda p: pytest.fail("a dead lane must not be asked"))
    assert head["by"] == "deterministic" and head["text"].splitlines()[0] == r["needs"][0]
    assert "lane      extract: CANNOT GENERATE" in morning_cmd.render(r)


def test_morning_with_a_live_lane_adds_no_line(monkeypatch, stub):
    base = stub(dead=False)
    from harness import delegate
    monkeypatch.setattr(delegate, "route", lambda lane: ("s", serving.Route(base, "m", {})))
    monkeypatch.setattr(delegate, "upstream", lambda where: (base, "m"))
    monkeypatch.setattr(serving, "engine_at", lambda b, config=None: serving.DEFAULT)
    r = _gather(morning.lane_health)
    assert r["lane"]["generating"] is True and not any("cannot generate" in n for n in r["needs"])


def test_morning_survives_a_lane_it_cannot_route(monkeypatch):
    from harness import delegate

    def boom(lane):
        raise delegate.Refused("no extract model")
    monkeypatch.setattr(delegate, "route", boom)
    r = _gather(morning.lane_health)
    assert r["lane"]["generating"] is None and "no extract model" in r["lane"]["why"]
