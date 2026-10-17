"""A parent that stops ranking a weight drops its claim; the weight goes back to inspect, never terminal. #954."""
import pytest

from harness import fetching, live_audit, reasons
from harness import memory_store as ms
from harness.commands import loop as loop_cmd

PARENT, OTHER, WEIGHT = "Blaizzy/mlx-audio", "org/other-tool", "sesame/csm-1b"


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr("harness.paths.home", lambda: tmp_path)
    conn = ms.connect(tmp_path / "discovery.db")
    yield conn
    conn.close()


def _repo(conn, name):
    ms.record(conn, ms.Seen(name=name, source="inspect", resolved=name, kind="repo",
                            registry=ms.GITHUB))


def _queue(conn, parent, weight):
    """What discover's inspect writes for a weight a GitHub repo ranks."""
    ms.record(conn, ms.Seen(name=weight, source="inspect", resolved=weight, kind="weights",
                            registry=ms.HUGGINGFACE, category=ms.MODEL, why=f"named by {parent}"))
    ms.link(conn, parent, weight, "needs")
    ms.decide(conn, weight, "queued", tier=ms.INSPECT, size_bytes=1, reason=reasons.CANDIDATE,
              detail=f"lane=- named by {parent}")


def _edges(conn, weight):
    return sorted(ms.parents(conn, weight))


def _held(conn, name):
    return conn.execute("SELECT p.state, v.id, v.tier, v.reason, v.detail, v.reopen_kind FROM proposals p "
                        "JOIN verdicts v ON v.id = p.state_verdict_id WHERE p.name = ?", (name,)).fetchone()


def test_a_parent_that_drops_a_weight_hands_it_back_to_inspect(store):
    _repo(store, PARENT)
    _queue(store, PARENT, WEIGHT)
    assert ms.retire_unlisted(store, PARENT, keep=[]) == [WEIGHT]
    held = _held(store, WEIGHT)
    assert held["state"] == "queued" and WEIGHT not in ms.settled(store)
    assert (held["tier"], held["reason"]) == (ms.INSPECT, reasons.HARNESS)
    assert _edges(store, WEIGHT) == []
    assert WEIGHT in ms.pending(store, registry=ms.HUGGINGFACE, screened=False)
    row = next(r for r in fetching.queued(store, needs_lane=False) if r["name"] == WEIGHT)
    assert not row["inspected"]


def test_a_weight_a_second_parent_still_ranks_keeps_its_state(store):
    _repo(store, PARENT)
    _repo(store, OTHER)
    _queue(store, PARENT, WEIGHT)
    ms.link(store, OTHER, WEIGHT, "needs")
    before = _held(store, WEIGHT)["id"]
    assert ms.retire_unlisted(store, PARENT, keep=[]) == []
    assert _held(store, WEIGHT)["id"] == before
    assert _edges(store, WEIGHT) == [OTHER]
    assert ms.retire_unlisted(store, OTHER, keep=[]) == [WEIGHT]
    assert _held(store, WEIGHT)["state"] == "queued"


def test_a_weight_still_ranked_is_left_alone(store):
    _repo(store, PARENT)
    _queue(store, PARENT, WEIGHT)
    before = _held(store, WEIGHT)["id"]
    assert ms.retire_unlisted(store, PARENT, keep=[WEIGHT]) == []
    assert _held(store, WEIGHT)["id"] == before and _edges(store, WEIGHT) == [PARENT]


def _retired_the_old_way(conn, weight):
    ms.decide(conn, weight, "ignored", tier=ms.INSPECT, reason=reasons.CANDIDATE, detail=ms.UNRANKED)


def test_the_loop_reopens_weights_a_ranking_retired_and_the_audit_reads_zero(store):
    _repo(store, PARENT)
    _queue(store, PARENT, WEIGHT)
    _retired_the_old_way(store, WEIGHT)
    _queue(store, PARENT, "funasr/campplus")
    ms.decide(store, "funasr/campplus", "ignored", tier=ms.INSPECT, reason=reasons.CANDIDATE,
              detail="an auxiliary model, not a candidate")
    assert len(live_audit._no_ranking_verdict(store)) == 1
    assert loop_cmd._reopen_unranked() == [WEIGHT]
    assert loop_cmd._reopen_unranked() == []
    store.rollback()
    held = _held(store, WEIGHT)
    assert (held["state"], held["tier"], held["reopen_kind"]) == ("queued", ms.INSPECT, "retraction")
    assert _held(store, "funasr/campplus")["state"] == "ignored"
    assert live_audit._no_ranking_verdict(store) == []
    row = next(r for r in fetching.queued(store, needs_lane=False) if r["name"] == WEIGHT)
    assert not row["inspected"]


def test_the_audit_names_the_check():
    assert "no_ranking_verdict" in live_audit.CHECKS
