"""An outcome column moves only by compare-and-swap on the outcome it leaves. #1739."""
import re

import pytest
from gauntlet import detectors

from harness import delegations, repo, reverify
from harness import memory_store as ms
from harness import runtime_trials as rtt
from tests.gauntlet import registry
from tests.test_reverify import (NOW, _queue_and_finish, cases, check, conn, on, powered,  # noqa: F401
                                 upgraded)
from tests.test_runtime_trials_1474 import NOW as TRIAL_NOW
from tests.test_runtime_trials_1474 import ROOMY, _channels, _uv, sandbox  # noqa: F401


@pytest.fixture
def wide():
    """unguarded_transition as the registry configures it for the ratchet."""
    config = registry.REGISTRY.detector_config["unguarded_transition"]
    assert "outcome" in config["columns"]
    return lambda trees: detectors.unguarded_transition(trees, registry.production, **config)


def test_an_unguarded_outcome_write_fires_and_a_guarded_one_does_not(wide):
    trees = detectors.parse({
        "harness/a.py": 'def bare(c):\n    c.execute("UPDATE t SET outcome = ? WHERE id = ?")\n',
        "harness/b.py": 'def cas(c):\n    c.execute("UPDATE u SET outcome = ? WHERE id = ? AND outcome = ?")\n'})
    assert [h.site for h in wide(trees)] == ["harness/a.py:bare"]


def test_no_production_code_sets_an_outcome_without_a_where_on_it(wide):
    trees = detectors.parse(detectors.sources(registry.REPO, production=registry.production, lister=repo.publishable))
    hits = [f"{h.site}:{h.line} {h.why}" for h in wide(trees) if not re.search(r"\.(state|status)\b", h.why)]
    assert hits == []


def test_a_rerun_settled_by_another_writer_is_not_settled_again(upgraded, monkeypatch):
    conn = upgraded
    _queue_and_finish(conn, cases("q3-4b", 10))
    real = reverify.judge

    def raced(c, rv, job):
        c.execute("UPDATE reverifications SET outcome = ?, settled_at = ? WHERE id = ?",
                  (reverify.CANCELLED, NOW, rv["id"]))
        return real(c, rv, job)
    monkeypatch.setattr(reverify, "judge", raced)
    got = check(conn, now=NOW + 120)
    row = conn.execute("SELECT outcome FROM reverifications ORDER BY id DESC").fetchone()
    assert got["settled"] == [] and row["outcome"] == reverify.CANCELLED


@pytest.fixture
def store():
    c = ms.connect()
    yield c
    c.close()


def _trial(conn, outcome=rtt.PROPOSED):
    conn.execute("INSERT INTO runtime_trials (runtime, version, pinned, channel, seen_at, outcome) "
                 "VALUES ('mlx-lm', '9.9.9', '0.32.0', 'pypi', 1.0, ?)", (outcome,))
    conn.commit()
    return conn.execute("SELECT * FROM runtime_trials WHERE version = '9.9.9'").fetchone()


def test_a_proposed_trial_records_its_verdict(store):
    _trial(store)
    assert rtt.record(store, rtt.RUNTIMES["mlx-lm"], "9.9.9", rtt.Verdict(rtt.BLOCKED, "no wheel")) is True
    assert store.execute("SELECT outcome FROM runtime_trials").fetchone()[0] == rtt.BLOCKED


def test_a_decided_trial_is_never_decided_again(store):
    _trial(store, rtt.HELD)
    assert rtt.record(store, rtt.RUNTIMES["mlx-lm"], "9.9.9", rtt.Verdict(rtt.BLOCKED, "no wheel")) is False
    row = store.execute("SELECT outcome, detail FROM runtime_trials").fetchone()
    assert (row["outcome"], row["detail"]) == (rtt.HELD, "")


def test_a_trial_another_loop_decided_first_is_not_reported_as_this_loop_s(tmp_path, sandbox, monkeypatch):
    conn = ms.connect()
    get_json, gh, _ = _channels({"mlx-lm": "0.33.0"})
    rtt.watch(conn, {"mlx-lm": "0.32.0"}, get_json=get_json, gh=gh, now=TRIAL_NOW)
    real = rtt.decide

    def raced(*a, **kw):
        conn.execute("UPDATE runtime_trials SET outcome = ? WHERE runtime = 'mlx-lm'", (rtt.KEPT,))
        return real(*a, **kw)
    monkeypatch.setattr(rtt, "decide", raced)
    tried = rtt.trial(conn, run=_uv(), home=tmp_path / "home", platform="darwin", machine="arm64",
                      incumbent_of=lambda lane: "", free=ROOMY)
    assert tried == [] and conn.execute("SELECT outcome FROM runtime_trials").fetchone()[0] == rtt.KEPT


class _Racing:
    """A connection on which another writer closes the delegation just before outcome() writes it."""

    def __init__(self, conn, call_id):
        self.conn, self.call_id, self.raced = conn, call_id, False

    def execute(self, sql, args=()):
        if sql.startswith("UPDATE delegations") and not self.raced:
            self.raced = True
            self.conn.execute("UPDATE delegations SET outcome = 'unknown', why = 'expired' WHERE call_id = ?",
                              (self.call_id,))
        return self.conn.execute(sql, args)

    def __getattr__(self, name):
        return getattr(self.conn, name)


def test_an_outcome_told_after_another_writer_closed_it_keeps_what_it_overwrote(store):
    call_id = delegations.record(store, delegations.new_id(), "code")
    got = delegations.outcome(_Racing(store, call_id), call_id, "used", "fine")
    row = store.execute("SELECT outcome, why FROM delegations WHERE call_id = ?", (call_id,)).fetchone()
    assert got["previous"] == "unknown"
    assert (row["outcome"], row["why"]) == ("used", "fine (was unknown: expired)")


def test_a_retold_outcome_another_writer_changed_keeps_what_it_overwrote(store):
    call_id = delegations.record(store, delegations.new_id(), "code")
    delegations.outcome(store, call_id, "discarded")
    got = delegations.outcome(_Racing(store, call_id), call_id, "used", "fine")
    assert got["previous"] == "unknown" and got["why"] == "fine (was unknown: expired)"
