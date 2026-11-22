"""Extra /status host names come from the home's status-hosts file, per request. #2124."""
import pytest

from tests.test_status_page_2075 import _app

srv = pytest.importorskip("harness.mcp_server", reason="needs the `mcp` group: uv run --group mcp pytest")

PHONE = "100.64.0.9"
NAME = "Box.Example.ts.net."


@pytest.fixture
def served(monkeypatch, tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("LOCALHARNESS_HOME", str(home))
    monkeypatch.setattr(srv, "STATUS_PORT", 8899)
    return _app(monkeypatch, tmp_path), home


def _codes(client, host, paths=("/status", "/status.json")):
    return [client.get(p, headers={"host": host}).status_code for p in paths]


def test_without_the_file_a_private_address_is_refused(served):
    client, _ = served
    assert _codes(client, f"{PHONE}:8899") == [421, 421]


def test_names_in_the_file_are_allowed_with_and_without_the_port(served):
    client, home = served
    (home / "status-hosts").write_text(f"{PHONE}\n{NAME}\n", encoding="utf-8")
    for host in (f"{PHONE}:8899", PHONE, "box.example.ts.net:8899"):
        assert _codes(client, host) == [200, 200], host
    assert _codes(client, "other.example:8899") == [421, 421]


def test_the_file_is_read_per_request(served):
    client, home = served
    assert _codes(client, f"{PHONE}:8899", ("/status",)) == [421]
    (home / "status-hosts").write_text(PHONE + "\n", encoding="utf-8")
    assert _codes(client, f"{PHONE}:8899", ("/status",)) == [200]


def test_the_action_endpoint_passes_the_host_check(served):
    client, home = served
    (home / "status-hosts").write_text(PHONE + "\n", encoding="utf-8")
    assert client.post("/status/action", data={}, headers={"host": f"{PHONE}:8899"}).status_code != 421
    assert client.post("/status/action", data={}, headers={"host": "other.example:8899"}).status_code == 421


def test_the_mcp_allow_list_is_not_widened(served):
    _, home = served
    (home / "status-hosts").write_text(PHONE + "\n", encoding="utf-8")
    allowed = srv.transport_security("0.0.0.0", 8899).allowed_hosts
    assert PHONE not in allowed and f"{PHONE}:8899" not in allowed
    assert PHONE in srv.status_hosts()


def test_comments_and_blank_lines_add_nothing(served):
    client, home = served
    (home / "status-hosts").write_text("# the phone\n\n   \n", encoding="utf-8")
    assert srv.status_hosts() == srv.STATUS_HOSTS
    assert _codes(client, f"{PHONE}:8899") == [421, 421]


def test_an_unreadable_file_is_a_421_not_a_500(served):
    client, home = served
    (home / "status-hosts").mkdir()
    assert srv.status_hosts() == srv.STATUS_HOSTS
    assert _codes(client, f"{PHONE}:8899") == [421, 421]


def test_without_a_served_port_only_the_bare_name_is_added(monkeypatch, tmp_path):
    monkeypatch.setattr(srv, "STATUS_HOSTS", {"localhost"})
    monkeypatch.setattr(srv, "STATUS_PORT", None)
    (tmp_path / "status-hosts").write_text(PHONE + "\n", encoding="utf-8")
    assert srv.status_hosts(tmp_path) == {"localhost", PHONE}
