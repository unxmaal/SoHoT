"""The MCP server listens on IPv4 and IPv6 both, so a client whose localhost is ::1 connects. #1555."""
import shutil
import socket
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from tests import shells

mcp_server = pytest.importorskip("harness.mcp_server")

REPO = Path(__file__).resolve().parents[1]
PROBE = REPO / "scripts" / "mcp-probe.sh"


def _has_ipv6_loopback() -> bool:
    if not socket.has_ipv6:
        return False
    try:
        with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as s:
            s.bind(("::1", 0))
        return True
    except OSError:
        return False


IPV6 = pytest.mark.skipif(not _has_ipv6_loopback(), reason="this host has no IPv6 loopback")


def _connects(addr: str, port: int) -> bool:
    try:
        with socket.create_connection((addr, port), timeout=5):
            return True
    except OSError:
        return False


@pytest.fixture
def listening():
    opened = []

    def listen(host):
        socks = mcp_server.listen_sockets(host, 0)
        for s in socks:
            s.listen()
        opened.extend(socks)
        return socks[0].getsockname()[1], socks
    yield listen
    for s in opened:
        s.close()


@IPV6
@pytest.mark.parametrize("host", ["0.0.0.0", "127.0.0.1"])
def test_the_server_accepts_a_connection_on_both_loopback_stacks(listening, host):
    port, socks = listening(host)
    assert _connects("127.0.0.1", port)
    assert _connects("::1", port), f"bound {[s.getsockname() for s in socks]}"


@IPV6
def test_each_stack_has_its_own_socket_so_an_ipv4_client_stays_ipv4(listening):
    _, socks = listening("0.0.0.0")
    assert [s.family for s in socks] == [socket.AF_INET, socket.AF_INET6]
    assert socks[1].getsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY) == 1


@pytest.mark.gauntlet("a-closed-table-fronting-an-open-set", site="harness/mcp_server.py:OTHER_STACK")
def test_a_named_address_listens_on_that_address_alone(monkeypatch):
    calls = []
    monkeypatch.setattr(mcp_server, "_bound", lambda host, port: calls.append((host, port)) or socket.socket())
    for s in mcp_server.listen_sockets("192.0.2.10", 8899):
        s.close()
    assert calls == [("192.0.2.10", 8899)]


def test_a_stack_that_cannot_bind_is_skipped_with_a_line_saying_so(monkeypatch, capsys):
    real = mcp_server._bound

    def no_ipv6(host, port):
        if ":" in host:
            raise OSError("no IPv6 here")
        return real(host, port)
    monkeypatch.setattr(mcp_server, "_bound", no_ipv6)
    socks = mcp_server.listen_sockets("0.0.0.0", 0)
    try:
        assert len(socks) == 1 and socks[0].family == socket.AF_INET
    finally:
        for s in socks:
            s.close()
    assert "not ::" in capsys.readouterr().err


def test_serve_hands_uvicorn_both_sockets(monkeypatch):
    import uvicorn
    got = {}
    monkeypatch.setattr(uvicorn.Server, "run", lambda self, sockets=None: got.setdefault("socks", sockets))
    monkeypatch.setattr(mcp_server, "listen_sockets", lambda host, port: ["v4", "v6"])
    monkeypatch.setattr(mcp_server, "stale_report", lambda port, pid: [])
    mcp_server.serve("0.0.0.0", 8899)
    assert got["socks"] == ["v4", "v6"]


def test_a_bracketed_ipv6_loopback_host_passes_the_dns_rebinding_allowlist(monkeypatch):
    from mcp.server.transport_security import TransportSecurityMiddleware
    monkeypatch.setattr(mcp_server, "_local_hostname", lambda: "box")
    guard = TransportSecurityMiddleware(mcp_server.transport_security("0.0.0.0", 8899))
    assert guard._validate_host("[::1]:8899")
    assert guard._validate_origin("http://[::1]:8899")
    assert not guard._validate_host("[::2]:8899")


def _http_answering(socks):
    def serve(sock):
        sock.listen()
        sock.settimeout(10)
        while True:
            try:
                conn, _ = sock.accept()
            except OSError:
                return
            with conn:
                conn.recv(4096)
                conn.sendall(b"HTTP/1.0 400 Bad Request\r\nContent-Length: 0\r\n\r\n")
    for s in socks:
        threading.Thread(target=serve, args=(s,), daemon=True).start()


def _probe(port):
    return subprocess.run([shells.resolve("bash"), str(PROBE), str(port)], capture_output=True, text=True, timeout=60)


@IPV6
@pytest.mark.skipif(sys.platform == "win32" or not shutil.which("curl"), reason="a bash script that runs curl")
def test_the_smoke_probe_passes_a_server_on_both_stacks(listening):
    port, socks = listening("0.0.0.0")
    _http_answering(socks)
    got = _probe(port)
    assert got.returncode == 0, got.stdout


@IPV6
@pytest.mark.skipif(sys.platform == "win32" or not shutil.which("curl"), reason="a bash script that runs curl")
def test_the_smoke_probe_fails_naming_the_stack_that_refuses():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    try:
        _http_answering([sock])
        got = _probe(port)
    finally:
        sock.close()
    assert got.returncode == 1
    assert f"FAIL  mcp at [::1]:{port}" in got.stdout and f"PASS  mcp at 127.0.0.1:{port}" in got.stdout


def test_smoke_runs_the_mcp_probe():
    assert "scripts/mcp-probe.sh" in (REPO / "scripts" / "smoke.sh").read_text(encoding="utf-8")
