"""MCP and audio listen on loopback by default and demand the gateway key when opened to the LAN. #510."""
import json
import socket
import sys
import threading
import time

import httpx
import pytest

from harness import gateway_key, lan_auth

INIT = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                   "clientInfo": {"name": "t", "version": "0"}}}
MCP_HEADERS = {"Accept": "application/json, text/event-stream"}


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def serve():
    """Run an ASGI app under a real uvicorn on loopback; the app decides whether it is guarded."""
    import uvicorn
    servers = []

    def start(app):
        """`app` is an ASGI app, or a function of the port that returns one."""
        port = _free_port()
        if getattr(app, "wants_port", False):
            app = app(port)
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port,
                                               log_level="warning", lifespan="auto"))
        t = threading.Thread(target=server.run, daemon=True)
        t.start()
        servers.append((server, t))
        deadline = time.monotonic() + 20
        while not server.started:
            assert time.monotonic() < deadline, "server did not start"
            time.sleep(0.05)
        return f"http://127.0.0.1:{port}"

    yield start
    for server, t in servers:
        server.should_exit = True
        t.join(timeout=10)


def _mcp_app(host):
    pytest.importorskip("mcp")
    from harness import mcp_server

    def build(port):
        return mcp_server.http_app("streamable-http", host, port)
    build.wants_port = True
    return mcp_server, build


@pytest.mark.parametrize("host,out", [("127.0.0.1", False), ("localhost", False), ("::1", False),
                                      ("127.0.0.2", False), ("0.0.0.0", True), ("::", True),
                                      ("192.0.2.10", True), ("100.64.0.1", True),
                                      ("<host>.local", True)])
def test_exposed_means_another_machine_can_connect(host, out):
    assert lan_auth.exposed(host) is out


def _never_bind(*a, **k):
    raise AssertionError("main() must serve through http_app, never bind a real port here")


def test_mcp_defaults_to_loopback(monkeypatch):
    pytest.importorskip("mcp")
    import uvicorn

    from harness import mcp_server
    seen = {}
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: seen.update(kw, app=app))
    monkeypatch.setattr(mcp_server.SERVER, "run", _never_bind)
    monkeypatch.setattr(sys, "argv", ["soh-mcp"])
    mcp_server.main()
    assert seen["host"] == "127.0.0.1"
    assert not isinstance(seen["app"], lan_auth.KeyRequired)


def test_mcp_on_the_lan_is_wrapped_in_the_key(monkeypatch):
    pytest.importorskip("mcp")
    import uvicorn

    from harness import mcp_server
    seen = {}
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: seen.update(kw, app=app))
    monkeypatch.setattr(mcp_server.SERVER, "run", _never_bind)
    monkeypatch.setattr(sys, "argv", ["soh-mcp", "--host", "0.0.0.0"])
    mcp_server.main()
    assert seen["host"] == "0.0.0.0"
    assert isinstance(seen["app"], lan_auth.KeyRequired)


def test_exposed_mcp_refuses_a_missing_key_with_401_naming_the_fix(serve):
    _, app = _mcp_app("0.0.0.0")
    base = serve(app)
    r = httpx.post(f"{base}/mcp", json=INIT, headers=MCP_HEADERS)
    assert r.status_code == 401
    assert "soh gateway key" in r.json()["error"]
    assert r.headers["www-authenticate"].startswith("Bearer")


def test_exposed_mcp_refuses_a_wrong_key(serve):
    _, app = _mcp_app("0.0.0.0")
    base = serve(app)
    r = httpx.post(f"{base}/mcp", json=INIT,
                   headers={**MCP_HEADERS, "Authorization": "Bearer sk-not-the-key"})
    assert r.status_code == 401


def test_exposed_mcp_refuses_the_key_under_another_scheme(serve):
    _, app = _mcp_app("0.0.0.0")
    base = serve(app)
    r = httpx.post(f"{base}/mcp", json=INIT,
                   headers={**MCP_HEADERS, "Authorization": f"Basic {gateway_key.ensure()}"})
    assert r.status_code == 401


def test_exposed_mcp_answers_the_gateway_key(serve):
    _, app = _mcp_app("0.0.0.0")
    base = serve(app)
    r = httpx.post(f"{base}/mcp", json=INIT,
                   headers={**MCP_HEADERS, **gateway_key.headers(environ={})})
    assert r.status_code == 200, r.text[:200]
    assert "serverInfo" in r.text


def test_loopback_mcp_needs_no_key(serve):
    """Claude Code on this machine is registered keyless at localhost:8899; that keeps working."""
    _, app = _mcp_app("127.0.0.1")
    base = serve(app)
    r = httpx.post(f"{base}/mcp", json=INIT, headers=MCP_HEADERS)
    assert r.status_code == 200, r.text[:200]


def test_exposed_server_with_no_stored_key_makes_one():
    store = gateway_key.default_store()
    assert store.get() == ""
    lan_auth.guard(object(), "0.0.0.0")
    assert store.get().startswith("sk-")


def test_an_empty_key_refuses_to_build():
    with pytest.raises(ValueError):
        lan_auth.KeyRequired(object(), "")


async def _hello(scope, receive, send):
    if scope["type"] == "websocket":
        await receive()
        await send({"type": "websocket.accept"})
        await send({"type": "websocket.close", "code": 1000})
        return
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"ok"})


def test_the_audio_launcher_guards_the_app_it_imports(monkeypatch):
    """serve-tts.sh runs `python -m harness.lan_auth mlx_audio.server:app`."""
    import types

    import uvicorn
    seen = {}
    monkeypatch.setitem(sys.modules, "fake_audio", types.SimpleNamespace(app=_hello))
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: seen.update(kw, app=app))
    lan_auth.main(["fake_audio:app", "--port", "8890"])
    assert seen["host"] == "127.0.0.1" and seen["app"] is _hello
    lan_auth.main(["fake_audio:app", "--host", "0.0.0.0", "--port", "8890"])
    assert isinstance(seen["app"], lan_auth.KeyRequired)


def test_exposed_audio_refuses_without_the_key_and_answers_with_it(serve):
    base = serve(lan_auth.guard(_hello, "0.0.0.0"))
    assert httpx.get(f"{base}/v1/models").status_code == 401
    r = httpx.get(f"{base}/v1/models", headers=gateway_key.headers(environ={}))
    assert (r.status_code, r.text) == (200, "ok")


def test_the_cuda_audio_server_defaults_to_loopback_and_is_keyed_when_opened(monkeypatch):
    pytest.importorskip("fastapi")
    import uvicorn

    from harness import audio_server
    seen = {}
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: seen.update(kw, app=app))
    monkeypatch.delenv("AUDIO_HOST", raising=False)
    audio_server.main()
    assert seen["host"] == "127.0.0.1"
    assert not isinstance(seen["app"], lan_auth.KeyRequired)
    monkeypatch.setenv("AUDIO_HOST", "0.0.0.0")
    audio_server.main()
    assert isinstance(seen["app"], lan_auth.KeyRequired)


def test_a_websocket_without_the_key_is_closed():
    import asyncio
    sent = []

    async def send(msg):
        sent.append(msg)

    async def receive():
        return {"type": "websocket.connect"}

    asyncio.run(lan_auth.KeyRequired(_hello, "sk-k")({"type": "websocket", "headers": []},
                                                      receive, send))
    assert sent == [{"type": "websocket.close", "code": 1008}]


def test_the_refusal_body_never_carries_the_key(serve):
    key = gateway_key.ensure()
    base = serve(lan_auth.guard(_hello, "0.0.0.0"))
    r = httpx.get(f"{base}/", headers={"Authorization": "Bearer wrong"})
    assert key not in r.text and key not in json.dumps(dict(r.headers))
