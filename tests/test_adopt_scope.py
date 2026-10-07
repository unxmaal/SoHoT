"""A by-hand adoption is scoped, fitted and costed per machine. #485."""
import json

import pytest

from harness import adopt, candidates, human
from harness import memory_store as ms

M2 = {"fingerprint": "Mac14,12/macOS/arm64", "hw_model": "Mac14,12",
      "os": "macOS-26", "arch": "arm64", "memory_gb": 32.0,
      "accelerator": "unified 32GB", "runtimes": "cpu,mlx", "ceiling_gb": 22.0}
STUDIO = {**M2, "fingerprint": "Mac17,15/macOS/arm64", "hw_model": "Mac17,15",
          "os": "macOS-27", "memory_gb": 96.0, "ceiling_gb": 66.0}
GIB_KB = 1024 ** 2


@pytest.fixture
def on(monkeypatch):
    def be(facts):
        monkeypatch.setattr(ms, "this_machine", lambda: dict(facts))
    be(STUDIO)
    return be


@pytest.fixture
def conn(tmp_path, on):
    c = ms.connect(tmp_path / "d.db")
    yield c
    c.close()


def _by_hand(conn, lane, spec, incumbent="old", **kw):
    return adopt.record(conn, adopt.Verdict(lane, incumbent, spec, True, "won",
                                            adopt.BY_HAND, votes=12,
                                            agreement=1.0, **kw))


def _run(conn, facts, spec, seconds, peak_gib, passed=True, lane="image",
         path=None):
    """One stored run of `spec` on the machine `facts` names."""
    mid = ms.remember_machine(conn, facts)
    cid = candidates.ensure(conn, spec, lane=lane)
    key = candidates.get(conn, spec)["receipt_key"]
    path = path or f"run-{mid}-{cid}-{seconds}"
    conn.execute("INSERT INTO runs (path, lane, tier, machine_id, generated_at, "
                 "recorded_at) VALUES (?, ?, 'measure', ?, 1.0, 1.0)",
                 (path, lane, mid))
    rid = conn.execute("SELECT id FROM runs WHERE path = ?", (path,)).fetchone()[0]
    conn.execute("INSERT INTO results (run_id, seq, candidate_id, candidate, "
                 "case_id, passed, seconds, peak_kb) VALUES (?,?,?,?,?,?,?,?)",
                 (rid, 1, cid, key, "c1", int(passed), seconds,
                  int(peak_gib * GIB_KB)))
    conn.commit()
    return rid


def test_a_by_hand_adoption_serves_only_the_machine_it_was_made_on(conn, on):
    _by_hand(conn, "image", "mflux:dev")
    assert adopt.adopted(conn) == {"image": "mflux:dev"}
    on(M2)
    ms.remember_machine(conn)
    assert adopt.adopted(conn) == {}


def test_all_machines_is_explicit_and_recorded(conn, on):
    _by_hand(conn, "image", "mflux:dev", all_machines=True)
    row = conn.execute("SELECT all_machines FROM adoptions").fetchone()
    assert row["all_machines"] == 1
    on(M2)
    ms.remember_machine(conn)
    assert adopt.adopted(conn) == {"image": "mflux:dev"}


def test_a_global_adoption_that_cannot_fit_a_machine_is_refused_there(conn, on):
    _run(conn, STUDIO, "mflux:dev", 15.0, 30.0)
    _by_hand(conn, "image", "mflux:dev", all_machines=True)
    on(M2)
    mid = ms.remember_machine(conn)
    assert adopt.adopted(conn) == {}
    got = adopt.refused(conn)
    assert [r["lane"] for r in got] == ["image"]
    assert "30.0 GiB" in got[0]["why"] and "22.0 GiB" in got[0]["why"]
    assert adopt.adopted(conn, mid) == {}


def test_a_refused_global_adoption_falls_back_to_the_previous_one(conn, on):
    _run(conn, STUDIO, "mflux:dev", 15.0, 30.0)
    on(M2)
    adopt.record(conn, adopt.Verdict("image", "typed", "mflux:flux2-klein-4b", True, "won"))
    on(STUDIO)
    _by_hand(conn, "image", "mflux:dev", all_machines=True)
    on(M2)
    assert adopt.adopted(conn) == {"image": "mflux:flux2-klein-4b"}


def test_a_stored_size_over_the_ceiling_is_refused(conn, on):
    conn.execute("INSERT INTO proposals (name, lane, first_seen, last_seen) "
                 "VALUES ('org/huge', 'image', 1.0, 1.0)")
    candidates.ensure(conn, "diffusers:org/huge", proposal="org/huge", lane="image")
    conn.execute("UPDATE proposals SET size_bytes = ? WHERE name = 'org/huge'",
                 (40 * 1024 ** 3,))
    _by_hand(conn, "image", "diffusers:org/huge", all_machines=True)
    on(M2)
    ms.remember_machine(conn)
    assert adopt.adopted(conn) == {}
    assert "stored size" in adopt.refused(conn)[0]["why"]


def test_a_passing_run_on_the_machine_is_evidence_it_fits(conn, on):
    """A peak over the ceiling that nonetheless ran here is the instrument, not the model. #238."""
    on(M2)
    _run(conn, M2, "acestep:steps8", 100.0, 36.3, lane="music")
    _by_hand(conn, "music", "acestep:steps8")
    assert adopt.adopted(conn) == {"music": "acestep:steps8"}


def test_a_model_that_cannot_fit_here_is_never_adopted_here(conn, on):
    _run(conn, STUDIO, "mflux:dev", 15.0, 30.0)
    on(M2)
    with pytest.raises(adopt.Held, match="22.0 GiB"):
        _by_hand(conn, "image", "mflux:dev")
    assert conn.execute("SELECT COUNT(*) FROM adoptions").fetchone()[0] == 0


def test_an_unknown_size_is_served_but_said(conn, on):
    _by_hand(conn, "image", "diffusers:org/mystery", all_machines=True)
    on(M2)
    ms.remember_machine(conn)
    ok, why = adopt.fit(conn, candidates.get(conn, "diffusers:org/mystery")["id"],
                        ms.machine_row(conn))
    assert ok and "unknown" in why
    assert adopt.adopted(conn) == {"image": "diffusers:org/mystery"}


def _pairs(conn, lane, a, b, cases, answers):
    pairs = []
    for case in cases:
        for ans in answers:
            human.record(lane, case, a, b, ans, conn=conn)
        pairs.append({"case": case, "a": a, "b": b})
    return pairs


def test_vote_stats_count_and_agreement(conn):
    pairs = _pairs(conn, "image", "x", "y", ["c1", "c2"], ["b", "b", "a"])
    n, agreement = human.vote_stats("image", pairs, conn=conn)
    assert n == 6 and agreement == pytest.approx(4 / 6)


def test_too_few_votes_is_held_not_lost(conn):
    pairs = _pairs(conn, "image", "x", "y", ["c1", "c2", "c3"], ["b", "b", "b"])
    v = adopt.decide_by_hand("image", "x", "y", pairs, conn=conn)
    assert not v.adopt and v.held and "9 votes" in v.held and "--force" in v.held
    with pytest.raises(adopt.Held):
        adopt.record(conn, v)
    assert conn.execute("SELECT COUNT(*) FROM verdicts WHERE tier = 'adopt'"
                        ).fetchone()[0] == 0


def test_force_adopts_and_records_that_it_was_forced(conn):
    pairs = _pairs(conn, "image", "x", "y", ["c1", "c2", "c3"], ["b", "b", "a"])
    v = adopt.decide_by_hand("image", "x", "y", pairs, force=True, conn=conn)
    assert v.adopt and v.forced and v.votes == 9
    adopt.record(conn, v)
    row = conn.execute("SELECT votes, agreement, forced, all_machines "
                       "FROM adoptions").fetchone()
    assert (row["votes"], row["forced"], row["all_machines"]) == (9, 1, 0)
    assert row["agreement"] == pytest.approx(6 / 9)


def test_enough_votes_adopts_without_force(conn):
    pairs = _pairs(conn, "image", "x", "y", ["c1", "c2", "c3", "c4"],
                   ["b", "b", "b"])
    v = adopt.decide_by_hand("image", "x", "y", pairs, conn=conn)
    assert v.adopt and not v.forced and v.votes == 12


def test_the_minimum_is_a_parameter(conn):
    pairs = _pairs(conn, "image", "x", "y", ["c1"], ["b", "b", "b"])
    assert adopt.decide_by_hand("image", "x", "y", pairs, min_votes=3,
                                conn=conn).adopt


def test_the_cost_delta_against_the_previous_adoption_is_recorded(conn):
    _run(conn, STUDIO, "mflux:flux2-klein-4b", 3.0, 15.0)
    _run(conn, STUDIO, "mflux:dev", 15.0, 20.5)
    _by_hand(conn, "image", "mflux:dev", incumbent="mflux:flux2-klein-4b")
    row = conn.execute("SELECT cost FROM adoptions").fetchone()
    cost = json.loads(row["cost"])
    assert cost["median_s"] == 15.0 and cost["incumbent_median_s"] == 3.0
    assert cost["peak_gb"] == pytest.approx(20.5, abs=0.01)
    assert cost["incumbent_peak_gb"] == pytest.approx(15.0, abs=0.01)
    text = adopt.cost_text(cost)
    assert "5.0x" in text and "20.5 GiB" in text


def test_the_cost_says_how_many_passing_rows_each_median_rests_on(conn):
    _run(conn, STUDIO, "mflux:flux2-klein-4b", 3.0, 15.0)
    _run(conn, STUDIO, "mflux:dev", 15.0, 20.5)
    _run(conn, STUDIO, "mflux:dev", 99.0, 20.5, passed=False)
    _by_hand(conn, "image", "mflux:dev", incumbent="mflux:flux2-klein-4b")
    cost = json.loads(conn.execute("SELECT cost FROM adoptions").fetchone()[0])
    assert (cost["rows"], cost["passed"]) == (2, 1)
    assert (cost["incumbent_rows"], cost["incumbent_passed"]) == (1, 1)
    assert "1 of 2 rows passed" in adopt.cost_text(cost)


def test_no_votes_is_zero_with_no_agreement(conn):
    assert human.vote_stats("image", [], conn=conn) == (0, None)


def test_the_cost_reads_only_this_machines_runs(conn, on):
    _run(conn, M2, "mflux:dev", 99.0, 20.0)
    _by_hand(conn, "image", "mflux:dev", incumbent="mflux:flux2-klein-4b")
    cost = json.loads(conn.execute("SELECT cost FROM adoptions").fetchone()[0])
    assert cost.get("median_s") is None
    assert "no stored run" in adopt.cost_text(cost)


def test_describe_names_scope_how_and_votes(conn, on):
    _by_hand(conn, "image", "mflux:dev", forced=True)
    row = adopt.current(conn)["image"]
    text = adopt.describe(row, ms.machine_row(conn))
    assert "by-hand" in text and "this machine" in text
    assert "12 votes" in text and "forced" in text
    assert "all machines" in adopt.describe({**row, "all_machines": 1}, 99)
    assert "machine" in adopt.describe(row, 99)


def test_a_measured_adoption_is_not_gated_on_votes(conn):
    adopt.record(conn, adopt.Verdict("code", "a", "llamacpp:b", True, "won"))
    assert adopt.adopted(conn) == {"code": "llamacpp:b"}


def _legacy_store(path, on):
    """A store about to be stamped back to schema 48."""
    on(M2)
    c = ms.connect(path)
    return c, ms.remember_machine(c, M2), ms.remember_machine(c, STUDIO)


def _to_48(c):
    c.execute("UPDATE meta SET value = '48' WHERE key = 'schema'")
    c.commit()
    c.close()


def _legacy_adoption(c, lane, spec, machine, at=5.0):
    cid = candidates.ensure(c, spec, lane=lane)
    c.execute("INSERT INTO verdicts (outcome, tier, detail, decided_at, "
              "machine_id, candidate_id) VALUES ('measured', 'adopt', "
              "'preferred by hand', ?, ?, ?)", (at, machine, cid))
    vid = c.execute("SELECT MAX(id) FROM verdicts").fetchone()[0]
    c.execute("INSERT INTO adoptions (lane, candidate_id, verdict_id, machine_id, "
              "how, adopted_at) VALUES (?, ?, ?, ?, 'by-hand', ?)",
              (lane, cid, vid, machine, at))
    return candidates.get(c, spec)["receipt_key"]


def _vote(c, lane, run, key, other, machine, n=3, case="c1"):
    lo, hi = sorted((key, other))
    for _ in range(n):
        c.execute("INSERT INTO human_votes (lane, run, case_id, left_candidate, "
                  "right_candidate, winner, machine_id, at) VALUES "
                  "(?,?,?,?,?,?,?,1.0)", (lane, run, case, lo, hi, key, machine))


def test_the_migration_scopes_a_by_hand_adoption_to_the_machine_that_voted(
        tmp_path, on):
    path = tmp_path / "old.db"
    c, m2, studio = _legacy_store(path, on)
    key = _legacy_adoption(c, "image", "mflux:dev", machine=m2)
    for case in ("c1", "c2", "c3"):
        _vote(c, "image", "r1", key, "mflux/klein", studio, case=case)
    _to_48(c)
    c = ms.connect(path)
    row = dict(c.execute("SELECT * FROM adoptions").fetchone())
    assert row["machine_id"] == studio and row["all_machines"] == 0
    assert row["votes"] == 9 and row["agreement"] == 1.0 and row["forced"] == 0
    guesses = c.execute("SELECT value FROM meta WHERE key = "
                        "'candidate_guesses'").fetchone()
    assert guesses is None or json.loads(guesses[0]) == []
    assert adopt.adopted(c) == {}
    on(STUDIO)
    assert adopt.adopted(c) == {"image": "mflux:dev"}
    c.close()


def test_the_migration_falls_back_to_the_judged_runs_machine(tmp_path, on):
    path = tmp_path / "old.db"
    c, m2, studio = _legacy_store(path, on)
    key = _legacy_adoption(c, "image", "mflux:dev", machine=m2)
    c.execute("INSERT INTO runs (path, lane, machine_id, recorded_at) "
              "VALUES ('r1', 'image', ?, 1.0)", (studio,))
    _vote(c, "image", "r1", key, "mflux/klein", None)
    _to_48(c)
    c = ms.connect(path)
    assert c.execute("SELECT machine_id FROM adoptions").fetchone()[0] == studio
    c.close()


def test_the_migration_records_a_guess_when_nothing_names_the_machine(
        tmp_path, on):
    path = tmp_path / "old.db"
    c, m2, _ = _legacy_store(path, on)
    c.execute("INSERT OR REPLACE INTO meta VALUES ('candidate_guesses', ?)",
              (json.dumps([{"verdict": 1}]),))
    key = _legacy_adoption(c, "music", "acestep:steps8", machine=m2)
    _vote(c, "music", "", key, "acestep:steps16", None, n=12)
    _to_48(c)
    c = ms.connect(path)
    assert c.execute("SELECT machine_id FROM adoptions").fetchone()[0] == m2
    guesses = json.loads(c.execute("SELECT value FROM meta WHERE key = "
                                   "'candidate_guesses'").fetchone()[0])
    assert guesses[0] == {"verdict": 1}
    assert guesses[1]["adoption"] == 1 and guesses[1]["machine"] == m2
    assert guesses[1]["lane"] == "music"
    c.execute("UPDATE meta SET value = '48' WHERE key = 'schema'")
    c.commit()
    c.close()
    c = ms.connect(path)
    again = json.loads(c.execute("SELECT value FROM meta WHERE key = "
                                 "'candidate_guesses'").fetchone()[0])
    assert again == guesses
    c.close()


def test_the_migration_leaves_measured_adoptions_alone(tmp_path, on):
    path = tmp_path / "old.db"
    c, m2, studio = _legacy_store(path, on)
    cid = candidates.ensure(c, "llamacpp:x", lane="code")
    c.execute("INSERT INTO adoptions (lane, candidate_id, machine_id, how, "
              "adopted_at) VALUES ('code', ?, ?, 'measured', 1.0)", (cid, studio))
    _to_48(c)
    c = ms.connect(path)
    row = c.execute("SELECT machine_id, votes FROM adoptions").fetchone()
    assert (row["machine_id"], row["votes"]) == (studio, None)
    c.close()


def test_report_shows_each_lanes_adoption_scope_and_how(conn, on):
    from harness import report
    _by_hand(conn, "image", "mflux:dev", forced=True)
    lanes = {l["lane"]: l for l in report.lanes_state(conn)}
    assert lanes["image"]["adopted_how"] == adopt.BY_HAND
    assert "this machine" in lanes["image"]["adoption"]
    assert "12 votes" in lanes["image"]["adoption"]
    assert lanes["code"]["adoption"] == ""


def test_report_shows_a_refusal_rather_than_serving_it(conn, on):
    from harness import report
    _run(conn, STUDIO, "mflux:dev", 15.0, 30.0)
    _by_hand(conn, "image", "mflux:dev", all_machines=True)
    on(M2)
    ms.remember_machine(conn)
    lanes = {l["lane"]: l for l in report.lanes_state(conn)}
    assert lanes["image"]["serves"] != "mflux:dev"
    assert "mflux:dev" in lanes["image"]["refused"]
    assert "22.0 GiB" in lanes["image"]["refused"]


def test_judge_takes_force_all_machines_and_min_votes():
    from harness import cli
    a = cli.build_parser().parse_args(["judge", "r", "--force", "--all-machines",
                                       "--min-votes", "4"])
    assert a.force and a.all_machines and a.min_votes == 4
    a = cli.build_parser().parse_args(["judge", "r"])
    assert not a.force and not a.all_machines and a.min_votes == adopt.MIN_VOTES
