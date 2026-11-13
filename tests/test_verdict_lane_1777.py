"""#1777: the repo gate reads a verdict's lane from the field its writer set, never from its sentence."""
import pytest

from harness import adopt, measure_replay, repo_gate
from harness import memory_store as ms
from tests.test_adopt_retest_1001 import lane_cases  # noqa: F401
from tests.test_measure_gain_1315 import proposal


@pytest.fixture
def conn():
    c = ms.connect()
    yield c
    c.close()


def _won(conn, name: str, lane: str, said: str) -> int:
    """An adopt-tier win in `lane` as adopt.record writes it, its sentence then reworded to `said`."""
    proposal(conn, name, "code", ())
    vid = adopt.record(conn, adopt.Verdict(lane, "inc", name, True, "won"), spec=name)
    conn.execute("UPDATE verdicts SET detail = ? WHERE id = ?", (said, vid))
    conn.commit()
    return vid


def test_a_repo_win_whose_sentence_is_reworded_still_opens_the_gate(conn):
    _won(conn, "w/Repo-9B", "repo", "beats the incumbent on the lane's metric")
    assert repo_gate.verdict(conn, "w/Repo-9B") == "measured"
    assert [r["name"] for r in repo_gate.owed(conn)] == ["w/Repo-9B"]
    assert [r["name"] for r in measure_replay.owed_at(conn, float("inf"))] == ["w/Repo-9B"]


def test_a_code_win_whose_sentence_begins_repo_is_no_repo_result(conn):
    _won(conn, "w/Code-9B", "code", "repo: re-decided (#1049) and said so")
    assert repo_gate.verdict(conn, "w/Code-9B") is None
    assert repo_gate.owed(conn) == []
    assert measure_replay.owed_at(conn, float("inf")) == []


def test_the_sentence_keeps_its_lane_prefix_for_an_older_release(conn):
    proposal(conn, "w/Old-9B", "code", ())
    vid = adopt.record(conn, adopt.Verdict("repo", "inc", "w/Old-9B", True, "won"), spec="w/Old-9B")
    row = conn.execute("SELECT lane, detail FROM verdicts WHERE id = ?", (vid,)).fetchone()
    assert (row["lane"], row["detail"]) == ("repo", "repo: won")


@pytest.mark.gauntlet("a-shared-store-query-with-no-scope-or-a-scope-with-its-own-idea-of-null",
                      site="harness/memory_store/migrations/v103.py:data:verdicts")
@pytest.mark.gauntlet("a-shared-store-query-with-no-scope-or-a-scope-with-its-own-idea-of-null",
                      site="harness/memory_store/migrations/v103.py:data:runs")
def test_the_migration_files_an_older_adopt_verdict_under_its_detail_lane_and_no_other(conn):
    from harness.memory_store.migrations import v103
    for name in ("w/A-9B", "w/B-9B", "w/C-9B", "w/D-9B"):
        proposal(conn, name, "code", ())
    run = conn.execute("INSERT INTO runs (path, lane, tier, specs, recorded_at, generated_at) "
                       "VALUES ('r-d', 'repo', 'measure', '{}', 1, 1)").lastrowid
    a = ms.decide(conn, "w/A-9B", "measured", tier=ms.ADOPT, reason="candidate", detail="repo: won")
    b = ms.decide(conn, "w/B-9B", "declined", tier=ms.ADOPT, reason="owner", judge="owner",
                  detail="declined by the owner: owner: no")
    c = ms.decide(conn, "w/C-9B", "measured", tier=ms.MEASURE, reason="candidate", detail="repo: already the default")
    d = ms.decide(conn, "w/D-9B", "declined", tier=ms.ADOPT, reason="limit", until="cases:repo>9", run_id=run,
                  detail="re-decided (#1001): no retest is left")
    v103.data(conn)
    v103.data(conn)
    got = {r["id"]: r["lane"] for r in conn.execute("SELECT id, lane FROM verdicts WHERE id IN (?, ?, ?, ?)",
                                                    (a, b, c, d))}
    assert got == {a: "repo", b: "", c: "", d: "repo"}


def test_a_spent_repo_limit_re_decided_with_no_lane_prefix_stays_in_the_repo_lane(conn, lane_cases):
    from harness import coherence, reasons
    from harness.memory_store import transitions
    from tests.test_adopt_retest_1001 import T, _retested_once
    _retested_once(conn, "w/Spent-9B", "code")
    pid = conn.execute("SELECT id FROM proposals WHERE name = 'w/Spent-9B'").fetchone()[0]
    transitions._write(conn, pid, "w/Spent-9B", {"outcome": "declined", "tier": ms.ADOPT, "reason": reasons.LIMIT,
                                                 "until": "", "detail": "repo: underpowered", "decided_at": T,
                                                 "lane": "repo", "power": '{"cases": 5, "cases_needed": null}'})
    conn.commit()
    found = [c for c in coherence.changes(conn) if c["name"] == "w/Spent-9B"]
    assert found and found[0]["detail"].startswith("re-decided (#1001)")
    vid = coherence.apply(conn, found)[0]
    assert conn.execute("SELECT lane FROM verdicts WHERE id = ?", (vid,)).fetchone()[0] == "repo"
    assert repo_gate.verdict(conn, "w/Spent-9B") == "declined"


def test_a_coherence_re_decision_keeps_the_lane_of_the_verdict_it_replaces(conn):
    from harness import coherence
    proposal(conn, "w/Held-9B", "code", ())
    vid = ms.decide(conn, "w/Held-9B", "declined", tier=ms.ADOPT, reason="limit", until="cases:repo>40",
                    detail="code: fewer cases than the effect needs", lane="repo")
    r = dict(conn.execute(coherence.HELD.replace("ORDER BY v.id", "AND v.id = ? ORDER BY v.id"), (vid,)).fetchone())
    assert r["verdict_lane"] == "repo"
    got = coherence.apply(conn, [{"name": "w/Held-9B", "now": ["declined", ms.ADOPT, "limit", "cases:repo>50"],
                                  "run_path": "", "run_id": None, "candidate_id": None, "lane": r["verdict_lane"],
                                  "detail": "code: re-decided (#1049): reworded"}])
    assert conn.execute("SELECT lane FROM verdicts WHERE id = ?", (got[0],)).fetchone()[0] == "repo"
