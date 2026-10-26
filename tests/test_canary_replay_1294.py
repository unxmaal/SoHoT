"""`soh canary` replay plants: a stored known pair through adopt.decide and confirm, no GPU, no store write. #1294."""
import json

import pytest

from harness import canary, cli, holdout
from harness import memory_store as ms

SPLIT = holdout.Split("repo", dev=tuple(f"d{i}" for i in range(12)), holdout=tuple(f"h{i}" for i in range(24)),
                      too_small=False)
GOOD, BAD = "claude-code:good", "llamacpp:bad"


def _run(conn, path, lane, key, passes, digest="dig1", cases=None):
    """One stored measure run of `key`: `passes(case)` says which cases it resolved."""
    conn.execute("INSERT INTO runs (path, lane, tier, cases_digest, recorded_at) VALUES (?, ?, 'measure', ?, 0)",
                 (path, lane, digest))
    rid = conn.execute("SELECT id FROM runs WHERE path = ?", (path,)).fetchone()[0]
    for i, case in enumerate(cases or (*SPLIT.dev, *SPLIT.holdout)):
        ok = passes(case)
        conn.execute("INSERT INTO results (run_id, seq, candidate, case_id, passed, metrics) VALUES (?,?,?,?,?,?)",
                     (rid, i, key, case, int(ok), json.dumps({"resolved": int(ok), "patch_applied": 1})))
    conn.commit()
    return rid


def _pair(conn, **kw):
    """The good candidate resolves every case, the bad one every fourth."""
    inc = _run(conn, "bad", "repo", BAD, lambda c: int(c[1:]) % 4 == 0, **kw)
    ch = _run(conn, "good", "repo", GOOD, lambda c: True, digest=kw.get("digest", "dig1"))
    return inc, ch


def _replays(inc, ch):
    return (canary.Replay("known-better", "repo", BAD, GOOD, (inc, ch), ("measured", "")),
            canary.Replay("known-worse", "repo", GOOD, BAD, (ch, inc), ("declined", "candidate")))


def test_the_replayed_repo_gate_adopts_the_stored_known_better_run(tmp_path):
    conn = ms.connect(tmp_path / "s.db")
    try:
        better, _ = _replays(*_pair(conn))
        got = canary.replay(conn, better, split=SPLIT)
    finally:
        conn.close()
    assert got["ok"] and not got["invalid"], got
    assert got["observed"]["outcome"] == "measured" and got["observed"]["tier"] == "adopt", got
    assert "confirmed on" in got["observed"]["why"], got


def test_the_replayed_repo_gate_declines_the_stored_known_worse_run(tmp_path):
    conn = ms.connect(tmp_path / "s.db")
    try:
        _, worse = _replays(*_pair(conn))
        got = canary.replay(conn, worse, split=SPLIT)
    finally:
        conn.close()
    assert got["ok"] and got["observed"]["outcome"] == "declined", got
    assert got["observed"]["reason"] == "candidate", got


def test_a_replay_the_gate_answers_wrongly_is_a_miss_not_invalid(tmp_path):
    conn = ms.connect(tmp_path / "s.db")
    try:
        inc, ch = _pair(conn)
        swapped = canary.Replay("x", "repo", GOOD, BAD, (ch, inc), ("measured", ""))
        got = canary.replay(conn, swapped, split=SPLIT)
    finally:
        conn.close()
    assert not got["ok"] and not got["invalid"], got


def test_a_decline_for_another_reason_is_a_miss(tmp_path):
    conn = ms.connect(tmp_path / "s.db")
    try:
        # A holdout win the dev cases do not confirm is declined as limit, not as a worse candidate.
        inc = _run(conn, "bad", "repo", BAD, lambda c: c[0] == "d" or int(c[1:]) % 4 == 0)
        ch = _run(conn, "good", "repo", GOOD, lambda c: True)
        got = canary.replay(conn, canary.Replay("z", "repo", BAD, GOOD, (inc, ch), ("declined", "candidate")),
                            split=SPLIT)
    finally:
        conn.close()
    assert got["observed"]["outcome"] == "declined" and got["observed"]["reason"] == "limit", got
    assert not got["ok"], got


def test_a_replay_plant_whose_stored_pair_no_longer_shares_an_exam_is_invalid_not_a_miss(tmp_path):
    conn = ms.connect(tmp_path / "s.db")
    try:
        inc = _run(conn, "bad", "repo", BAD, lambda c: False, digest="dig1")
        ch = _run(conn, "good", "repo", GOOD, lambda c: True, digest="dig2")
        better, _ = _replays(inc, ch)
        got = canary.replay(conn, better, split=SPLIT)
    finally:
        conn.close()
    assert not got["ok"] and "different exams" in got["invalid"], got


def test_a_replay_plant_whose_rows_are_gone_is_invalid_not_a_miss(tmp_path):
    conn = ms.connect(tmp_path / "s.db")
    try:
        inc, ch = _pair(conn)
        conn.execute("DELETE FROM results WHERE run_id = ?", (ch,))
        conn.commit()
        better, _ = _replays(inc, ch)
        got = canary.replay(conn, better, split=SPLIT)
        gone = canary.replay(conn, canary.Replay("y", "repo", BAD, GOOD, (inc, 999), ("measured", "")), split=SPLIT)
    finally:
        conn.close()
    assert not got["ok"] and GOOD in got["invalid"] and "no rows" in got["invalid"], got
    assert not gone["ok"] and gone["invalid"], gone


def test_a_replay_whose_rows_miss_todays_holdout_is_invalid_not_a_miss(tmp_path):
    conn = ms.connect(tmp_path / "s.db")
    try:
        old = tuple(f"old{i}" for i in range(30))
        inc = _run(conn, "bad", "repo", BAD, lambda c: False, cases=old)
        ch = _run(conn, "good", "repo", GOOD, lambda c: True, cases=old)
        better, _ = _replays(inc, ch)
        got = canary.replay(conn, better, split=SPLIT)
    finally:
        conn.close()
    assert not got["ok"] and "holdout" in got["invalid"], got


def test_a_replay_writes_nothing_to_the_store_it_reads(tmp_path):
    conn = ms.connect(tmp_path / "s.db")
    try:
        better, worse = _replays(*_pair(conn))
        before = conn.execute("SELECT (SELECT count(*) FROM verdicts), (SELECT count(*) FROM adoptions)").fetchone()
        canary.replay(conn, better, split=SPLIT)
        canary.replay(conn, worse, split=SPLIT)
        after = conn.execute("SELECT (SELECT count(*) FROM verdicts), (SELECT count(*) FROM adoptions)").fetchone()
    finally:
        conn.close()
    assert tuple(before) == tuple(after)


def test_the_canary_run_lists_replay_plants_without_planting_them(monkeypatch):
    live = ms.connect()
    try:
        better, worse = _replays(*_pair(live))
    finally:
        live.close()
    monkeypatch.setattr(holdout, "for_lane", lambda lane, root=None: SPLIT)
    seen = []
    r = canary.run([], run=lambda *a, **kw: seen.append(a), replays=(better, worse))
    assert seen == [] and r["ok"], r
    assert [(p["plant"], p["replay"], p["ok"]) for p in r["plants"]] == [("known-better", True, True),
                                                                         ("known-worse", True, True)]
    assert r["leaked"] == 0


def test_a_missed_or_invalid_replay_reaches_the_morning_line(monkeypatch):
    live = ms.connect()
    try:
        inc, ch = _pair(live)
    finally:
        live.close()
    monkeypatch.setattr(holdout, "for_lane", lambda lane, root=None: SPLIT)
    canary.run([], replays=(canary.Replay("flipped", "repo", GOOD, BAD, (ch, inc), ("measured", "")),))
    assert "missed" in canary.morning_line() and "flipped" in canary.morning_line()


def test_every_shipped_replay_names_two_runs_and_an_adopt_outcome():
    assert {r.lane for r in canary.REPLAYS} == {"code", "repo"}
    for r in canary.REPLAYS:
        assert len(r.runs) == 2 and all(isinstance(i, int) for i in r.runs), r
        assert r.expect[0] in ("measured", "declined") and r.incumbent != r.challenger, r
    names = [r.name for r in canary.REPLAYS] + [p.name for p in canary.PLANTS]
    assert len(names) == len(set(names))


def test_check_and_the_dry_run_list_the_replays(monkeypatch, capsys):
    live = ms.connect()
    try:
        better, _ = _replays(*_pair(live))
    finally:
        live.close()
    monkeypatch.setattr(canary, "REPLAYS", (better,))
    monkeypatch.setattr(holdout, "for_lane", lambda lane, root=None: SPLIT)
    assert cli.main(["canary"]) == 0
    assert "known-better" in capsys.readouterr().out
    rc = cli.main(["canary", "check", "--plant", "known-better"])
    out = capsys.readouterr().out
    assert rc == 0 and "ok   known-better" in out, out


@pytest.mark.parametrize("name", ["known-better"])
def test_run_with_a_replay_name_runs_only_that_replay(monkeypatch, capsys, name):
    live = ms.connect()
    try:
        better, worse = _replays(*_pair(live))
    finally:
        live.close()
    monkeypatch.setattr(canary, "REPLAYS", (better, worse))
    monkeypatch.setattr(holdout, "for_lane", lambda lane, root=None: SPLIT)
    real = canary.run
    monkeypatch.setattr(canary, "run", lambda plants, wait_h, replays=(): real(plants, wait_h=wait_h,
                                                                                 replays=replays,
                                                                                 run=lambda *a, **k: None))
    assert cli.main(["canary", "--run", "--plant", name, "--json"]) == 0
    got = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert [p["plant"] for p in got["plants"]] == [name]
