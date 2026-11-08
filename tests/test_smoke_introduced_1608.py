"""Smoke before the switch warns on a property the new release introduces; after the switch it fails. #1608."""
import os
import shutil
import socket
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from harness import deploy, deploy_switch
from tests import shells

REPO = Path(__file__).resolve().parents[1]
BASH = shells.resolve("bash")
needs_curl = pytest.mark.skipif(sys.platform == "win32" or BASH is None or not shutil.which("curl"),
                                reason="bash scripts that run curl")


@pytest.fixture
def ipv4_only_mcp():
    """A stand-in for the old release's MCP server: HTTP on 127.0.0.1 only, nothing on ::1."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    sock.listen(16)

    def serve():
        while True:
            try:
                conn, _ = sock.accept()
            except OSError:
                return
            with conn:
                conn.recv(4096)
                conn.sendall(b"HTTP/1.0 400 Bad Request\r\nContent-Length: 0\r\n\r\n")
    threading.Thread(target=serve, daemon=True).start()
    yield sock.getsockname()[1]
    sock.close()


def _smoke_mcp_lines(port: int, phase: str | None):
    """The MCP lines of scripts/smoke.sh, run as smoke runs them."""
    text = (REPO / "scripts" / "smoke.sh").read_text(encoding="utf-8")
    lines = [ln.strip() for ln in text.splitlines() if "scripts/mcp-probe.sh" in ln and not ln.strip().startswith("#")]
    assert len(lines) == 2
    script = "FAIL=0\n" + "\n".join(lines) + "\nexit $FAIL\n"
    env = {k: v for k, v in os.environ.items() if k != deploy.SMOKE_PHASE_ENV}
    env["MCP_PORT"] = str(port)
    if phase:
        env[deploy.SMOKE_PHASE_ENV] = phase
    return subprocess.run([BASH, "-c", script], cwd=REPO, env=env, capture_output=True, text=True, timeout=60)


@needs_curl
@pytest.mark.parametrize("phase", ["before", None], ids=["before", "old-caller"])
def test_before_the_switch_an_ipv4_only_server_passes_with_a_warning_naming_ipv6(ipv4_only_mcp, phase):
    """None: a deploy.py and deploy_switch.py from before #1608 run this smoke and set no phase."""
    got = _smoke_mcp_lines(ipv4_only_mcp, phase)
    assert got.returncode == 0, got.stdout
    assert f"PASS  mcp at 127.0.0.1:{ipv4_only_mcp}" in got.stdout
    assert f"WARN  mcp at [::1]:{ipv4_only_mcp}" in got.stdout and "FAIL" not in got.stdout


@needs_curl
def test_after_the_switch_the_same_server_fails_naming_ipv6(ipv4_only_mcp):
    got = _smoke_mcp_lines(ipv4_only_mcp, "after")
    assert got.returncode == 1
    assert f"FAIL  mcp at [::1]:{ipv4_only_mcp}" in got.stdout


@needs_curl
@pytest.mark.parametrize("phase", ["before", None])
def test_before_the_switch_a_property_the_old_release_had_still_fails(phase):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    got = _smoke_mcp_lines(port, phase)
    assert got.returncode == 1
    assert f"FAIL  mcp at 127.0.0.1:{port}" in got.stdout


def test_every_switch_step_runs_in_the_after_phase(tmp_path, monkeypatch):
    monkeypatch.setenv(deploy.SMOKE_PHASE_ENV, "before")
    out = tmp_path / "phase"
    with open(tmp_path / "log", "w", encoding="utf-8") as log:
        rc, _ = deploy_switch.run([sys.executable, "-c", f"import os; open({str(out)!r}, 'w').write(os.environ.get('SMOKE_PHASE', ''))"],
                                  str(tmp_path), 60, log)
    assert rc == 0 and out.read_text(encoding="utf-8") == "after"
