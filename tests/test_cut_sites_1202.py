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
    conn = ms.connect(tmp_path / "s.db")
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
