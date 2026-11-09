"""The lane probe reaches a lane a node serves first through the gateway, and names the node or the @local fallback that answered. #1653."""
import http.server
import json
import threading
import urllib.error

import pytest

from harness import completion, context, delegate, interactive, loopback, nodes, serving
from harness import lane_probe as lp
from tests.test_interactive_1561 import DECIDE, URL
from tests.test_interactive_node_1562 import NODE_BASE, pinned, serve, styx  # noqa: F401 - pinned is a fixture

KEY_VAR = "SOHOT_NODE_STYX_KEY"
ANSWER = {"choices": [{"message": {"content": json.dumps({"answer": "A"})}, "finish_reason": "stop"}],
          "usage": {"prompt_tokens": 30, "completion_tokens": 6}}


class Sender:
    """Records what a wake sends and answers it as the gateway would, with the headers naming who served it."""

    def __init__(self, headers):
        self.headers, self.sent = headers, []

    def in_flight(self, lane):
        return False

    def start(self, lane, url, headers, body, hold):
        self.sent.append({"url": url, "headers": headers, "body": body})
        return lane

    def collect(self, handle, wait):
        return {"status": 200, "body": json.dumps(ANSWER), "headers": dict(self.headers), "seconds": 0.4}


@pytest.fixture
def node(pinned, tmp_path, monkeypatch):  # noqa: F811
    monkeypatch.setenv(KEY_VAR, "node-secret")
    serve(tmp_path, monkeypatch, styx(lanes=["decide"], key=f"env:{KEY_VAR}"))
    asked = []

    def get(url, key=""):
        asked.append((url, key))
        if getattr(get, "refuse", False):
            raise urllib.error.URLError(ConnectionRefusedError(61, "Connection refused"))
        return {"data": [{"id": DECIDE, "status": {"value": "loaded"}}]}
    monkeypatch.setattr(context, "_get_json", get)
    return get, asked


def _wake(sender):
    return lp.wake(None, 0.0, lanes=("decide",), sender=sender, resolve=interactive.node_route, headers={})[0]


def test_a_node_lane_resolves_to_the_node_and_reports_it_reached_it(node):
    _, asked = node
    sender = Sender({"x-sohot-node": "styx"})
    row = _wake(sender)
    assert row["outcome"] == lp.UP, row
    assert row["upstream"] == serving.bare(NODE_BASE) and row["engine"] == serving.LLAMACPP
    assert "node styx" in row["reason"] and "sohot-decide@local" in row["reason"]
    # The probe takes the path interactive traffic takes: the gateway alias, which goes to the node first.
    assert [s["url"] for s in sender.sent] == [f"{completion.gateway_url()}/v1/chat/completions"]
    assert sender.sent[0]["body"]["model"] == "sohot-decide"
    # Residency is asked of the node itself, with the key the gateway sends it.
    assert asked == [(f"{serving.bare(NODE_BASE)}/models", "node-secret")]
    assert "node styx" in lp.line(row)


def test_a_fallback_answering_for_the_node_is_named_on_the_row_and_the_line(node):
    sender = Sender({"x-sohot-fallback": "styx"})
    row = _wake(sender)
    assert row["outcome"] == lp.UP
    assert row["upstream"] == URL
    assert "sohot-decide@local" in row["reason"] and "node styx did not" in row["reason"]
    assert "@local" in lp.line(row)


def test_a_node_that_refuses_its_residency_query_is_still_probed_through_the_gateway(node):
    get, _ = node
    get.refuse = True
    sender = Sender({"x-sohot-fallback": "styx"})
    row = _wake(sender)
    assert len(sender.sent) == 1 and row["outcome"] == lp.UP and row["upstream"] == URL
    assert "refused" in row["reason"]


def test_delegate_upstream_finds_a_lane_alias_only_the_served_config_names(node):
    where = interactive.node_route("decide")[1]
    assert delegate.upstream(where) == (serving.bare(NODE_BASE), DECIDE)
    twin = serving.Route(completion.gateway_url(), "sohot-decide" + nodes.LOCAL_SUFFIX, {})
    assert delegate.upstream(twin) == (URL, DECIDE)


def test_the_sender_keeps_the_gateways_headers_naming_who_answered():
    class Gateway(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
            data = json.dumps(ANSWER).encode()
            self.send_response(200)
            self.send_header("x-sohot-fallback", "styx")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *a):
            pass
    server = loopback.ThreadingHTTPServer(("127.0.0.1", 0), Gateway)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        got = lp._send({"url": f"http://127.0.0.1:{server.server_port}/v1/chat/completions", "body": {}, "hold": 5.0})
    finally:
        server.shutdown()
    assert got["status"] == 200 and got["headers"] == {"x-sohot-fallback": "styx"}
