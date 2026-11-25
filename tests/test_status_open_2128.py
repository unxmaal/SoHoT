"""The status page answers any host name and any peer on its own connection may press. #2128."""
import types

import pytest

from harness import owner_actions as oa
from tests.test_owner_actions_2116 import NOW, R

LAN = "198.51.100.50"
TAILNET = "100.64.0.9"


def _press(tmp_path, peer, headers=None):
    ran = []
    run = lambda cmd, **kw: ran.append(cmd) or types.SimpleNamespace(returncode=0, stdout="ok\n", stderr="")  # noqa: E731
    who, _ = oa.caller(peer, {})
    form = {"token": oa.token(peer, who, NOW) if who else "x", "action": "queue_resume"}
    kw = {"now": NOW, "home": tmp_path, "run": run}
    code, page = oa.press(peer, headers or {}, form, R, **kw)
    return code, page, ran, kw, form


@pytest.mark.parametrize("peer", [LAN, TAILNET, "127.0.0.1", "::1"])
def test_any_peer_with_no_device_list_and_no_whois_can_press(tmp_path, peer):
    assert not (tmp_path / "owner-devices").exists()
    code, page, ran, kw, form = _press(tmp_path, peer)
    assert code == 200 and ran == []
    form["confirm"] = page.split("name='confirm' value='")[1].split("'")[0]
    assert oa.press(peer, {}, form, R, **kw)[0] == 200 and ran == [[__import__("sys").executable, "-m", "harness.cli", "jobs", "resume"]]


@pytest.mark.parametrize("header", ["X-Forwarded-For", "forwarded", "X-Real-IP", "Via"])
def test_a_forwarded_request_is_refused(tmp_path, header):
    code, _, ran, _, _ = _press(tmp_path, LAN, headers={header: "x"})
    assert code == 403 and ran == []


def test_no_peer_is_refused():
    assert oa.caller(None, {}) == (None, "no peer address")


def test_the_caller_is_named_by_its_peer_address():
    assert oa.caller(LAN, {}) == ({"name": LAN, "id": LAN}, "")


def test_the_panel_is_shown_to_any_other_peer(tmp_path):
    assert "queue_resume" in oa.panel_for(LAN, {}, R, home=tmp_path, now=NOW)


def test_the_unused_lookups_are_gone():
    for name in ("allowed", "whois", "tailscale_bin", "DEVICES", "WHOIS_TIMEOUT_S", "APP_BIN", "is_local", "_binds"):
        assert not hasattr(oa, name), name


@pytest.fixture
def client(monkeypatch, tmp_path):
    from tests.test_status_page_2075 import _app
    return _app(monkeypatch, tmp_path)


def test_status_answers_any_host_name(client):
    for host in ("anything.example:8899", "198.51.100.50:8899", "100.64.0.9", "localhost:8899"):
        for path in ("/status", "/status.json"):
            assert client.get(path, headers={"host": host}).status_code == 200, (host, path)


def test_the_action_endpoint_has_no_host_check(client):
    assert client.post("/status/action", data={}, headers={"host": "anything.example:8899"}).status_code != 421


def test_mcp_still_refuses_an_unlisted_host(client):
    body = {"jsonrpc": "2.0", "id": 1, "method": "ping"}
    heads = {"accept": "application/json, text/event-stream", "content-type": "application/json"}
    with client:
        assert client.post("/mcp", json=body, headers={**heads, "host": "anything.example:8899"}).status_code == 421
        assert client.post("/mcp", json=body, headers={**heads, "host": "localhost:8899"}).status_code != 421
