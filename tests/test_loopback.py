"""Servers bind without a reverse DNS lookup: ~35 s per fake on check-macos (#711)."""
import http.server
import re
import socket
import threading
import urllib.request
from pathlib import Path

import pytest

from harness import loopback

REPO = Path(__file__).resolve().parent.parent
STOCK = re.compile(r"from\s+http\.server\s+import[^\n]*\b(?:Threading)?HTTPServer\b"
                   r"|http\.server\.(?:Threading)?HTTPServer\s*[()]")
ALLOWED = {
    "harness/loopback.py",
    "tests/test_loopback.py",
    "tests/test_gauntlet_scanners.py",
}


class Hello(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"ok")


def _no_reverse_dns(name=""):
    raise AssertionError(f"reverse DNS lookup of {name!r}")


@pytest.mark.parametrize("cls", [loopback.HTTPServer, loopback.ThreadingHTTPServer])
def test_a_loopback_server_binds_and_answers_without_reverse_dns(cls, monkeypatch):
    monkeypatch.setattr(socket, "getfqdn", _no_reverse_dns)
    srv = cls(("127.0.0.1", 0), Hello)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        assert srv.server_port == srv.server_address[1]
        with urllib.request.urlopen(f"http://127.0.0.1:{srv.server_port}/", timeout=5) as r:
            assert r.read() == b"ok"
    finally:
        srv.shutdown()
        srv.server_close()


def test_the_stock_server_does_look_up_reverse_dns(monkeypatch):
    monkeypatch.setattr(socket, "getfqdn", _no_reverse_dns)
    with pytest.raises(AssertionError, match="reverse DNS"):
        http.server.HTTPServer(("127.0.0.1", 0), Hello)


def test_a_test_that_looks_up_reverse_dns_fails():
    with pytest.raises(AssertionError, match="reverse DNS"):
        socket.getfqdn("127.0.0.1")


def test_no_server_is_built_from_http_server_outside_loopback():
    found = []
    for root in ("harness", "tests", "scripts", "evals"):
        for path in sorted((REPO / root).rglob("*.py")):
            rel = path.relative_to(REPO).as_posix()
            if rel in ALLOWED:
                continue
            for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if STOCK.search(line):
                    found.append(f"{rel}:{n}: {line.strip()}")
    assert not found, "use harness.loopback (or socketserver in a child without harness):\n" + \
        "\n".join(found)
