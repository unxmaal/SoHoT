"""#1634: requests share one httpx client, whose SSL context costs 175 ms to build on Windows, yet each opens its own connection."""
import json
import os
import threading
from http.server import BaseHTTPRequestHandler

import httpx
import pytest
import respx

from harness import completion, gateway_switch as gs
from harness.loopback import ThreadingHTTPServer

GW = "http://127.0.0.1:4000"


@pytest.fixture
def built(monkeypatch):
    """How many httpx clients were built since the test began, with no client left from an earlier test."""
    monkeypatch.setattr(completion, "_CLIENT", None)
    count = []
    real = httpx.Client.__init__

    def init(self, *a, **kw):
        count.append(1)
        real(self, *a, **kw)
    monkeypatch.setattr(httpx.Client, "__init__", init)
    return count


@pytest.fixture
def server():
    """A loopback server that keeps a connection open between requests, noting the client port of each."""
    ports = []

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _answer(self, body):
            ports.append(self.client_address[1])
            data = json.dumps(body).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
            self._answer({"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]})

        def do_GET(self):
            self._answer({"data": [], "in_flight_requests": 1})

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}", ports
    srv.shutdown()
    srv.server_close()


def test_many_completions_build_one_client(built):
    with respx.mock:
        route = respx.post(f"{GW}/v1/chat/completions").mock(return_value=httpx.Response(
            200, json={"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}))
        for _ in range(20):
            assert completion.complete("hi", model="sohot-code", gateway=GW) == "ok"
    assert route.call_count == 20 and len(built) == 1


def test_gateway_switch_probes_share_the_client(built, server):
    base, ports = server
    for _ in range(10):
        assert gs.in_flight(base) == 0
        assert gs.not_serving(base, {}) == ""
    assert len(ports) == 20 and len(built) == 1


def test_each_request_still_opens_its_own_connection(built, server):
    base, ports = server
    for _ in range(3):
        assert completion.complete("hi", model="sohot-code", gateway=base) == "ok"
    assert len(set(ports)) == 3


def test_a_forked_child_builds_its_own_client(built, monkeypatch):
    first = completion.http()
    assert completion.http() is first
    monkeypatch.setattr(os, "getpid", lambda: -1)
    assert completion.http() is not first and len(built) == 2
