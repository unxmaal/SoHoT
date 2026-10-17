"""A commit_after refusal reopens once its upstream commits after the until, asked of the registry per row. #961."""
import argparse

import pytest

from harness import feeds
from harness import inspect as ins
from harness import memory_store as ms
from harness.commands import loop as loop_cmd
from tests import fakes

#: Recorded cards: an idle repo inspect calls dead, and one that committed 2026-09-24T21:37:19.000Z.
IDLE = "BAAI/bge-reranker-base"
COMMITTED = "Contrastive-LM/CLM-v0.1-8B"


def _see(conn, name, registry=ms.HUGGINGFACE):
    ms.record(conn, ms.Seen(name=name, source="t", resolved=name, kind="weights",
                            registry=registry, lane="code"))


def _dead(conn, name):
    """Decline `name` the way the inspect tier does, from its recorded card."""
    fit = ins.inspect_model(name, data=fakes.card(name))
    assert fit.verdict == "dead"
    _see(conn, name)
    ms.decide(conn, name, "declined", tier=ms.INSPECT, reason=ins.reason_of(fit),
              until=ins.until_of(fit), upstream_idle_days=fit.upstream_idle_days,
              detail=f"dead: {fit.why}")


def _fetched_before_commit(conn, name, until="commit_after:2026-09-01T00:00:00Z"):
    """A screen refusal waiting on a commit after our copy was fetched (the #953 shape)."""
    _see(conn, name)
    ms.decide(conn, name, "broken", tier=ms.SCREEN, reason="candidate", until=until,
              detail="llama-server: malformed file")


def _state(conn, name):
    return conn.execute("SELECT state FROM proposals WHERE name = ?", (name,)).fetchone()[0]


@pytest.fixture
def store(tmp_path):
    conn = ms.connect(tmp_path / "s.db")
    yield conn
    conn.close()


def _ask(fetch, client=None):
    return lambda repo, registry: ins.upstream_commit(repo, registry, fetch=fetch, client=client)


def test_a_repo_that_committed_after_its_until_reopens_and_one_that_did_not_stays(store):
    _dead(store, IDLE)
    _fetched_before_commit(store, COMMITTED)
    got = ms.requeue_upstream_committed(store, _ask(fakes.registry()))
    assert (got["waiting"], got["asked"], got["answered"]) == (2, 2, 2)
    assert [r["name"] for r in got["committed"]] == [COMMITTED]
    assert got["committed"][0]["last_commit"] == "2026-09-24T21:37:19.000Z"
    assert _state(store, COMMITTED) == "queued"
    assert _state(store, IDLE) == "declined", "an upstream that has not moved was reopened"
    again = ms.requeue_upstream_committed(store, _ask(fakes.registry()))
    assert (again["waiting"], again["committed"]) == (1, [])


def test_the_dry_read_reopens_nothing(store):
    _fetched_before_commit(store, COMMITTED)
    got = ms.upstream_committed(store, _ask(fakes.registry()))
    assert [r["name"] for r in got["committed"]] == [COMMITTED]
    assert _state(store, COMMITTED) == "broken"


def test_network_trouble_leaves_the_row_standing(store):
    _fetched_before_commit(store, COMMITTED)

    def down(url):
        raise feeds.FeedError(f"{url}: HTTP 503")

    got = ms.requeue_upstream_committed(store, _ask(down))
    assert (got["asked"], got["answered"], got["committed"]) == (1, 0, [])
    assert _state(store, COMMITTED) == "broken"


def test_a_rate_limited_registry_stops_asking_and_reopens_nothing(store):
    _dead(store, IDLE)
    _fetched_before_commit(store, COMMITTED)
    asked = []

    def limited(url):
        asked.append(url)
        raise feeds.RateLimitedFeed(f"{url}: HTTP 429")

    ins.PACE.start()
    try:
        got = ms.requeue_upstream_committed(store, _ask(limited))
    finally:
        ins.PACE.end()
    assert len(asked) == 1, "a 429 must stop the pass, not spend a request per row"
    assert (got["waiting"], got["asked"], got["committed"]) == (2, 0, [])
    assert "not asked (registry rate-limited)" in loop_cmd.upstream_line(got)
    assert {_state(store, IDLE), _state(store, COMMITTED)} == {"declined", "broken"}


def test_a_github_repo_is_asked_for_its_last_push(store):
    _see(store, "org/tool", registry=ms.GITHUB)
    ms.decide(store, "org/tool", "declined", tier=ms.INSPECT, reason="upstream",
              until="commit_after:2021-01-05T12:35:40Z", detail="dead: last commit 5.7 years ago")

    class Client:
        def __init__(self, pushed):
            self.pushed = pushed

        def repo(self, name):
            assert name == "org/tool"
            return {"pushed_at": self.pushed}

    still = ms.requeue_upstream_committed(store, _ask(None, Client("2021-01-05T12:35:40Z")))
    assert still["committed"] == [] and _state(store, "org/tool") == "declined"
    moved = ms.requeue_upstream_committed(store, _ask(None, Client("2026-10-01T09:00:00Z")))
    assert [r["name"] for r in moved["committed"]] == ["org/tool"]
    assert _state(store, "org/tool") == "queued"


def test_commit_after_compares_instants_not_text():
    met = lambda until, seen: ms.until_met(f"commit_after:{until}", {"last_commit": seen})
    assert not met("2024-06-24T14:10:03.000Z", "2024-06-24T14:10:03.000Z")
    assert not met("2026-10-06T00:28:07Z", "2026-10-06T00:28:07.000Z"), "one instant, two spellings"
    assert not met("2021-01-05T20:00:00-08:00", "2021-01-06T01:00:00Z"), "an earlier push, later as text"
    assert met("2021-01-05T20:00:00-08:00", "2021-01-06T05:00:00Z")
    assert met("2026-09-01T00:00:00Z", "2026-09-24T21:37:19.000Z")
    assert not met("2023-10-22T03:10:14Z", "last Tuesday")


def test_the_loop_pass_asks_the_registry_and_says_what_it_reopened(capsys):
    conn = ms.connect()
    try:
        _dead(conn, IDLE)
        _fetched_before_commit(conn, COMMITTED)
    finally:
        conn.close()
    got = loop_cmd._reopen_upstream_committed(fetch=fakes.registry())
    out = capsys.readouterr().out
    assert "asked 2 of 2 commit_after refusal(s)" in out
    assert "1 committed since and requeued" in out and COMMITTED in out
    assert [r["name"] for r in got["committed"]] == [COMMITTED]


def test_the_loop_asks_the_upstream_before_its_inspect_step(monkeypatch):
    seen = []

    class Stop(Exception):
        pass

    def fake_discover(sub):
        if getattr(sub, "inspect", False):
            seen.append("inspect")
            raise Stop
        return 0

    monkeypatch.setattr(loop_cmd, "_reopen_upstream_committed", lambda: seen.append("upstream") or {})
    monkeypatch.setattr(loop_cmd.discover_cmd, "cmd_discover", fake_discover)
    with pytest.raises(Stop):
        loop_cmd._run_loop_held(argparse.Namespace(run=True, lane=""))
    assert seen == ["upstream", "inspect"]


def test_discover_revisit_reports_the_upstream_and_requeues_only_when_asked(monkeypatch, capsys):
    from harness import cli
    conn = ms.connect()
    try:
        _fetched_before_commit(conn, COMMITTED)
    finally:
        conn.close()
    monkeypatch.setattr(ins, "hf_get", fakes.registry())
    assert cli.main(["discover", "--revisit"]) == 0
    assert "1 committed since" in capsys.readouterr().out
    conn = ms.connect()
    try:
        assert _state(conn, COMMITTED) == "broken"
    finally:
        conn.close()
    assert cli.main(["discover", "--revisit", "--requeue"]) == 0
    assert "committed since and requeued" in capsys.readouterr().out
    conn = ms.connect()
    try:
        assert _state(conn, COMMITTED) == "queued"
    finally:
        conn.close()
