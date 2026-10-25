"""The craft lane's stdio MCP client against a scripted server (#1209)."""
from __future__ import annotations

import sys
import textwrap

import pytest

from evals import craft_mcp

SERVER = textwrap.dedent('''
    import json, sys, time
    for line in sys.stdin:
        msg = json.loads(line)
        if "id" not in msg:
            continue
        m, p = msg["method"], msg.get("params") or {}
        if m == "initialize":
            out = {"protocolVersion": p["protocolVersion"], "capabilities": {"tools": {}}}
        elif m == "tools/list":
            page = p.get("cursor")
            out = {"tools": [{"name": "b"}]} if page else {"tools": [{"name": "a"}], "nextCursor": "2"}
        elif m == "tools/call" and p["name"] == "slow":
            time.sleep(5)
            out = {}
        elif m == "tools/call" and p["name"] == "die":
            sys.exit(3)
        elif m == "tools/call" and p["name"] == "bad":
            print(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32602, "message": "no such tool"}}), flush=True)
            continue
        else:
            print("not json", flush=True)
            print(json.dumps({"jsonrpc": "2.0", "method": "notifications/progress"}), flush=True)
            out = {"content": [{"type": "text", "text": json.dumps(p["arguments"])}]}
        print(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": out}), flush=True)
''')


@pytest.fixture
def client(tmp_path):
    script = tmp_path / "server.py"
    script.write_text(SERVER, encoding="utf-8")
    c = craft_mcp.Client([sys.executable, str(script)], cwd=tmp_path, stderr=tmp_path / "err.log")
    c.initialize(timeout=10)
    yield c
    c.close(grace=1)


def test_tools_are_listed_across_pages(client):
    assert [t["name"] for t in client.tools(timeout=10)] == ["a", "b"]


def test_a_call_skips_notifications_and_noise_and_answers_its_own_id(client):
    got = client.call("echo", {"x": 1}, timeout=10)
    assert craft_mcp.json_of(got) == {"x": 1}


def test_a_slow_call_times_out(client):
    with pytest.raises(craft_mcp.McpTimeout, match="0.3s"):
        client.call("slow", {}, timeout=0.3)


def test_an_error_reply_is_raised_with_its_message(client):
    with pytest.raises(craft_mcp.McpError, match="no such tool"):
        client.call("bad", {}, timeout=10)


def test_a_server_that_exits_mid_call_is_named(client):
    with pytest.raises(craft_mcp.McpError, match="exited"):
        client.call("die", {}, timeout=10)


def test_a_missing_binary_is_an_mcp_error(tmp_path):
    with pytest.raises(craft_mcp.McpError, match="could not start"):
        craft_mcp.Client([str(tmp_path / "no-such-cli"), "mcp"], cwd=tmp_path)


def test_text_and_structured_results_read_back():
    assert craft_mcp.text_of({"content": [{"type": "text", "text": "a"}, {"type": "image"}]}) == "a"
    assert craft_mcp.json_of({"structuredContent": {"k": 2}, "content": []}) == {"k": 2}
    assert craft_mcp.json_of({"content": [{"type": "text", "text": "not json"}]}) is None
