"""An MCP restart leaves no harness.mcp_server behind, and one left behind is reported (#1155)."""
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

from harness import mcp_peers, paths
from harness import watchdog as wd

from tests import shells
from tests.test_watchdog import NIGHT, Fake

pytest.importorskip("mcp")

PY = "/opt/homebrew/Cellar/python@3.12/3.12.15/Frameworks/Python.framework/Versions/3.12/Resources/Python.app/Contents/MacOS/Python"
ARGS = "-m harness.mcp_server --host 0.0.0.0 --port 8899 --transport streamable-http"
posix = pytest.mark.skipif(sys.platform == "win32", reason="signals and ps are POSIX")


def P(pid, ppid, command, elapsed=600.0):
    return wd.Proc(pid, ppid, pid, float(elapsed), command)


# --- which processes are stale -------------------------------------------------

def test_the_uv_wrapper_and_its_server_are_the_live_one_and_an_old_server_on_the_port_is_stale():
    procs = [P(100, 1, f"uv run --group mcp python {ARGS}"), P(101, 100, f"{PY} {ARGS}"),
             P(50, 1, f"{PY} {ARGS}", elapsed=86400), P(60, 1, f"{PY} -m harness.mcp_server --port 9000"),
             P(70, 1, f"{PY} -m harness.mcp_server --transport stdio"), P(80, 101, f"{PY} -m harness.cli svg x")]
    assert [p.pid for p in mcp_peers.stale(procs, 100)] == [50]
    assert [p.pid for p in mcp_peers.stale(procs, 101, 8899)] == [50]


def test_a_command_is_a_server_only_when_python_runs_the_module_on_a_real_port():
    assert mcp_peers.port_of(f"{PY} -m harness.mcp_server") == 8899
    assert mcp_peers.port_of(f"{PY} -m harness.mcp_server --port=9001") == 9001
    assert mcp_peers.port_of(f"{PY} -m harness.mcp_server --port 0") is None
    assert mcp_peers.port_of(f"{PY} -m harness.mcp_server_extra --port 1") is None
    assert not mcp_peers.is_server(f"uv run --group mcp python {ARGS}")
    assert mcp_peers.is_server(f"/x/.venv/bin/python3.12 {ARGS}")


def test_the_stop_command_force_quits_a_draining_uvicorn():
    assert mcp_peers.stop_command([1693, 53054]) == "kill -INT 1693 53054"


# --- the watchdog keeps it visible ---------------------------------------------

class Unit(Fake):
    def __init__(self, tmp_path, procs, live):
        super().__init__(tmp_path, procs=procs)
        self.live = live

    def launchd_pid(self, service):
        return self.live if service == "mcp" else None


def _found(tmp_path, procs, live):
    world = wd.observe(Unit(tmp_path, procs, live), None, NIGHT)
    found, skipped = wd.judge(world)
    return [f.subject.key for f in found if f.criterion == "stale_mcp"], skipped, found


def test_the_watchdog_reports_an_old_server_beside_the_mcp_unit_with_the_command_to_stop_it(tmp_path):
    keys, _, found = _found(tmp_path, [P(200, 1, f"{PY} {ARGS}"), P(50, 1, f"{PY} {ARGS}", elapsed=86400)], 200)
    assert keys == ["mcp pid 50"]
    f = next(f for f in found if f.criterion == "stale_mcp")
    assert f.evidence["stop"] == "kill -INT 50" and f.subject.orphan
    assert wd.BY_ID["stale_mcp"].action == wd.NOTIFY


def test_a_server_draining_inside_the_grace_after_a_restart_is_not_reported(tmp_path):
    young = wd.ORPHAN_GRACE_S - 1
    assert _found(tmp_path, [P(200, 1, f"{PY} {ARGS}", elapsed=young), P(50, 1, f"{PY} {ARGS}")], 200)[0] == []


def test_with_no_mcp_unit_the_criterion_is_skipped_and_says_why(tmp_path):
    keys, skipped, _ = _found(tmp_path, [P(50, 1, f"{PY} {ARGS}")], None)
    assert keys == [] and "no mcp unit" in skipped["stale_mcp"]


# --- a real server ------------------------------------------------------------------

def _port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _start(tmp_path, port, *extra, name="a"):
    log = (tmp_path / f"{name}.log").open("w", encoding="utf-8")
    env = {**os.environ, "LOCALHARNESS_HOME": str(tmp_path / "home"), "PYTHONUNBUFFERED": "1"}
    proc = subprocess.Popen([sys.executable, "-m", "harness.mcp_server", "--host", "127.0.0.1", "--port", str(port),
                             *extra], cwd=paths.REPO, env=env, stdout=log, stderr=subprocess.STDOUT)
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return proc
        if proc.poll() is not None:
            break
        time.sleep(0.1)
    proc.kill()
    pytest.fail(f"server never listened: {(tmp_path / f'{name}.log').read_text(encoding="utf-8")[-2000:]}")


def _hold(port):
    """A client whose request never completes: uvicorn's graceful shutdown waits on it, as on the live orphans."""
    raw = socket.create_connection(("127.0.0.1", port))
    raw.sendall(f"POST /mcp HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nContent-Type: application/json\r\n"
                f"Accept: application/json, text/event-stream\r\nContent-Length: 100\r\n\r\n{{".encode())
    time.sleep(0.5)
    return raw


def _gone(proc, within):
    try:
        proc.wait(timeout=within)
        return True
    except subprocess.TimeoutExpired:
        return False


@posix
def test_a_stopped_server_exits_within_its_grace_though_a_client_holds_a_request_open(tmp_path):
    port = _port()
    proc = _start(tmp_path, port, "--shutdown-grace", "2")
    client = _hold(port)
    try:
        proc.send_signal(signal.SIGTERM)
        assert _gone(proc, 15), "the server outlived its grace on a client holding a request open"
    finally:
        proc.kill()
        client.close()


@posix
def test_a_new_server_names_the_old_one_still_draining_a_client_on_its_port(tmp_path):
    port = _port()
    old = _start(tmp_path, port, "--shutdown-grace", "600")
    client = _hold(port)
    new = None
    try:
        old.send_signal(signal.SIGTERM)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            with socket.socket() as s:
                if s.connect_ex(("127.0.0.1", port)) != 0:
                    break
            time.sleep(0.1)
        assert old.poll() is None, "the old server should still be draining"
        new = _start(tmp_path, port, name="b")
        log = (tmp_path / "b.log").read_text(encoding="utf-8")
        assert f"STALE server pid {old.pid}" in log and f"kill -INT {old.pid}" in log
        assert old.poll() is None, "the new server only reports; it stops nothing"
    finally:
        for p in (old, new):
            if p is not None:
                p.kill()
        client.close()


# --- how the server is spawned -----------------------------------------------

@posix
def test_serve_mcp_execs_the_server_so_launchd_signals_reach_it(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_py, out = bin_dir / "python3", tmp_path / "ran"
    fake_py.write_text(f'#!/bin/bash\necho "$$ $*" > "{out}"\n', encoding="utf-8")
    # uv run spawns its command as a child, the way the real uv does.
    (bin_dir / "uv").write_text(f'#!/bin/bash\nfor a in "$@"; do [ "$a" = -c ] && {{ echo "{fake_py}"; exit 0; }}; done\n'
                                f'"{fake_py}" "${{@:5}}"\n', encoding="utf-8")
    for f in (fake_py, bin_dir / "uv"):
        f.chmod(0o755)
    hf = tmp_path / "hf"
    hf.mkdir()
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "HF_ROOT": str(hf), "HF_HOME": str(hf),
           "LOCALHARNESS_HOME": str(tmp_path / "home"), "MCP_PORT": "18899"}
    proc = subprocess.Popen([shells.BASH, str(Path(paths.REPO) / "scripts" / "serve-mcp.sh")], env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    got, _ = proc.communicate(timeout=60)
    pid, _, argv = out.read_text(encoding="utf-8").strip().partition(" ")
    assert argv.startswith("-m harness.mcp_server") and "--port 18899" in argv, got
    assert int(pid) == proc.pid, "the server is not the process launchd started"
