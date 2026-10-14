"""A measurement the #803 length cap refused before #813 comes back as measurable. #858."""
import pytest

from harness import memory_store as ms

REFUSED = ("code: not run: 135 case(s) x repeat 1 x 2 call(s) projected at 3h 26m, "
           "over the 2h 00m budget; inconclusive, nothing is concluded about the challenger")


def _screened(conn, name):
    ms.record(conn, ms.Seen(name=name, source="test", url="", why="", relevance=0,
                            kind="candidate", registry=ms.HUGGINGFACE, lane="code",
                            resolved=name))
    ms.decide(conn, name, "queued", tier="inspect", detail="fits")
    ms.decide(conn, name, "screened", tier="screen", detail="3 case(s) passed a screen")


def _adopt_decline(conn, name, detail, failure_class, until="", run_id=None):
    vid = ms.decide(conn, name, "declined", tier="adopt", reason="limit", detail=detail,
                    until=until)
    conn.execute("UPDATE verdicts SET failure_class = ?, run_id = ? WHERE id = ?",
                 (failure_class, run_id, vid))


def _migrated(tmp_path, seed):
    path = tmp_path / "old.db"
    conn = ms.connect(path)
    seed(conn)
    conn.execute("UPDATE meta SET value = '70' WHERE key = 'schema'")
    conn.commit()
    conn.close()
    conn = ms.connect(path)
    try:
        state = dict(conn.execute("SELECT name, state FROM proposals").fetchall())
        survivors = [r["name"] for r in ms.survivors(conn, limit=100)]
    finally:
        conn.close()
    return state, survivors


def test_a_pre_815_length_refusal_is_requeued_for_measurement(tmp_path):
    def seed(conn):
        _screened(conn, "org/refused")
        _adopt_decline(conn, "org/refused", REFUSED, "inconclusive")
    state, survivors = _migrated(tmp_path, seed)
    assert state["org/refused"] == "screened"
    assert "org/refused" in survivors


def test_other_limit_declines_stay_declined(tmp_path):
    def seed(conn):
        _screened(conn, "org/underpowered")
        _adopt_decline(conn, "org/underpowered",
                       "code: underpowered: power 0.15 < 0.8 to detect +0.20 per cell",
                       "underpowered")
        _screened(conn, "org/budget")
        ms.decide(conn, "org/budget", "declined", tier="screen", reason="limit",
                  detail="stopped at a limit this harness chose (max_tokens.code>32768)",
                  until="limit:max_tokens.code>32768")
        _screened(conn, "org/load")
        ms.decide(conn, "org/load", "declined", tier="screen", reason="limit",
                  detail="cold load timed out", until="limit:load_timeout_s>600")
        _screened(conn, "org/fresh")
        _adopt_decline(conn, "org/fresh", REFUSED, "inconclusive",
                       until="limit:measure_budget_s>7200")
    state, survivors = _migrated(tmp_path, seed)
    for name in ("org/underpowered", "org/budget", "org/load", "org/fresh"):
        assert state[name] == "declined", name
        assert name not in survivors


def test_a_refusal_after_a_later_retest_is_left_alone(tmp_path):
    """Only the state verdict is retracted: a refusal superseded since then is history."""
    def seed(conn):
        _screened(conn, "org/moved-on")
        _adopt_decline(conn, "org/moved-on", REFUSED, "inconclusive")
        ms.decide(conn, "org/moved-on", "queued", tier="inspect", detail="retest 1/3",
                  reopen="retest", reopen_why="retest 1/3", reason="reopened")
    state, _ = _migrated(tmp_path, seed)
    assert state["org/moved-on"] == "queued"


@pytest.mark.gauntlet("state-is-whichever-row-came-last",
                      site="harness/memory_store/migrations/retractions.py:_requeue_length_refusals")
def test_only_a_refusal_straight_after_the_screen_is_requeued(tmp_path):
    """The row before the refusal, by id, must be the screen: a measured candidate stays declined."""
    def seed(conn):
        _screened(conn, "org/measured")
        pid = conn.execute("SELECT id FROM proposals WHERE name = 'org/measured'").fetchone()[0]
        conn.execute("INSERT INTO verdicts (proposal_id, outcome, tier, detail, decided_at, reason) "
                     "VALUES (?, 'declined', 'adopt', 'code: does not beat the incumbent', 0, 'candidate')",
                     (pid,))
        _adopt_decline(conn, "org/measured", REFUSED, "inconclusive")
    state, survivors = _migrated(tmp_path, seed)
    assert state["org/measured"] == "declined"
    assert "org/measured" not in survivors
