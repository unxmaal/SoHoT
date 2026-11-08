"""The limit_cuts rows retest_spent and the router's requests write when their limit binds (#1087, nightly #1202)."""
import pytest

from harness import cuts, router
from harness import memory_store as ms
from harness.memory_store import transitions

#: Taken at import: conftest's _no_real_router replaces both for every test.
GET, POST = router._get, router._post


def _rows(conn):
    return [tuple(r) for r in conn.execute("SELECT knob, what FROM limit_cuts ORDER BY id")]


@pytest.fixture
def store(tmp_path):
    conn = ms.connect()
    yield conn
    conn.close()


def _proposal(conn, name="org/m", retests=0):
    ms.record(conn, ms.Seen(name=name, source="t", lane="code", resolved=name))
    pid = conn.execute("SELECT id FROM proposals WHERE name = ?", (name,)).fetchone()[0]
    conn.execute("UPDATE proposals SET retest_count = ? WHERE id = ?", (retests, pid))
    return pid


def test_a_proposal_out_of_retests_records_the_cut_on_the_callers_store(store):
    pid = _proposal(store, retests=transitions.RETESTS)
    assert transitions.retest_spent(store, pid, ms.SCREEN)
    assert _rows(store) == [("retests", f"proposal {pid} has no retest left")]


def test_an_adopt_decline_past_its_retests_records_the_adopt_cut_on_the_callers_store(store):
    pid = _proposal(store)
    assert not transitions.retest_spent(store, pid, ms.ADOPT, pending=transitions.RETESTS_AT_ADOPT)
    assert _rows(store) == []
    assert transitions.retest_spent(store, pid, ms.ADOPT, pending=transitions.RETESTS_AT_ADOPT + 1)
    assert _rows(store) == [("retests_at_adopt", f"proposal {pid} has no adopt retest left")]


@pytest.mark.parametrize("call, what", [(lambda: GET("/models", "http://router.invalid"), "router GET /models"),
                                        (lambda: POST("/models/unload", {}, "http://router.invalid"),
                                         "router POST /models/unload")])
def test_a_router_request_that_times_out_records_its_cut(monkeypatch, call, what):
    def slow(*a, **k):
        raise TimeoutError("timed out")
    monkeypatch.setattr(router.urllib.request, "urlopen", slow)
    conn = ms.connect()
    try:
        with pytest.raises(TimeoutError):
            call()
        cuts.flush(conn)
        assert _rows(conn) == [("harness/router.py:TIMEOUT", what)]
    finally:
        conn.close()


class _Sent:
    """urlopen that keeps each request and answers with `reply`."""

    def __init__(self, reply=b'{"ok": 1}'):
        self.reply, self.reqs, self.timeouts = reply, [], []

    def __call__(self, req, timeout=None):
        import io
        self.reqs.append(req)
        self.timeouts.append(timeout)
        return io.BytesIO(self.reply)


@pytest.mark.parametrize("key", ["k1", ""])
def test_a_router_request_sends_its_key_only_when_given_one(monkeypatch, key):
    """A LAN router wants its API key on every request; a loopback one gets no header. #1562."""
    import json
    sent = _Sent()
    monkeypatch.setattr(router.urllib.request, "urlopen", sent)
    assert GET("/models", "http://r:1", key=key) == {"ok": 1}
    assert POST("/models/load", {"model": "m"}, "http://r:1", key=key) == {"ok": 1}
    get, post = sent.reqs
    assert (get.full_url, get.get_method(), get.data) == ("http://r:1/models", "GET", None)
    assert (post.full_url, post.get_method()) == ("http://r:1/models/load", "POST")
    assert json.loads(post.data) == {"model": "m"} and post.get_header("Content-type") == "application/json"
    for req in sent.reqs:
        assert req.get_header("Authorization") == (f"Bearer {key}" if key else None)
    assert sent.timeouts == [router.TIMEOUT, router.TIMEOUT]
    assert router._auth(key) == ({"Authorization": f"Bearer {key}"} if key else {})


def test_a_router_request_with_no_base_asks_this_machines_router_and_reads_an_empty_body_as_nothing(monkeypatch):
    sent = _Sent(reply=b"")
    monkeypatch.setattr(router.urllib.request, "urlopen", sent)
    monkeypatch.setattr(router, "url", lambda: "http://here:2")
    assert GET("/models") == {} and POST("/models/unload", {}) == {}
    assert [r.full_url for r in sent.reqs] == ["http://here:2/models", "http://here:2/models/unload"]
    assert all(r.get_header("Authorization") is None for r in sent.reqs)
