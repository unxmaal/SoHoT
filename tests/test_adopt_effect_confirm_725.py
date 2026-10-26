"""Per-lane effect from same-config rerun churn, and a dev confirmation before a gate win serves. #725."""
import argparse
import json
import time

import pytest

from harness import adopt, effects, holdout, knobs, power, reasons
from harness import memory_store as ms
from harness import paths, screen, workqueue
from harness.commands import adopt as adopt_cmd
from harness.commands import measure as measure_cmd

FAKE_MACHINE = {"fingerprint": "test/rig", "hw_model": "", "os": "", "arch": "",
                "memory_gb": 0.0, "accelerator": "", "runtimes": "", "ceiling_gb": 0.0}


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv(paths.ENV_VAR, str(tmp_path))
    monkeypatch.setattr(ms.machines, "_THIS_MACHINE", FAKE_MACHINE)
    real = ms.connect
    monkeypatch.setattr(ms, "connect", lambda *a, **k: real(tmp_path / "d.db"))
    c = ms.connect()
    yield c
    c.close()


def _run(c, lane, key, draws, *, tier="measure", budget=4096, path=None):
    """One stored run of `key`: draws is case -> list of pass bits, one per repeat."""
    rid = c.execute("INSERT INTO runs (path, lane, tier, receipt, recorded_at) VALUES (?,?,?,?,?)",
                    (path or f"r{time.monotonic_ns()}", lane, tier,
                     json.dumps({"modality": lane, "max_tokens": budget}), time.time())).lastrowid
    seq = 0
    for case, bits in draws.items():
        for k, bit in enumerate(bits, 1):
            seq += 1
            c.execute("INSERT INTO results (run_id, seq, candidate, case_id, repeat_index, passed) "
                      "VALUES (?,?,?,?,?,?)", (rid, seq, key, case if len(bits) == 1 else f"{case}#{k}", k, int(bit)))
    c.commit()
    return rid


# --- the effect ------------------------------------------------------------

def test_rerun_churn_is_the_share_of_cells_a_same_config_rerun_flips(conn):
    cases = [f"c{i}" for i in range(40)]
    _run(conn, "code", "m", {c: [True] for c in cases})
    _run(conn, "code", "m", {c: [i >= 8] for i, c in enumerate(cases)})
    got = effects.churn(conn)["code"]
    assert got["cases"] == 40 and got["configs"] == 1
    assert got["churn"] == pytest.approx(0.1)
    assert effects.effect_of(got) == pytest.approx(0.1)


def test_draws_under_different_configs_are_not_pooled_as_reruns(conn):
    cases = [f"c{i}" for i in range(40)]
    _run(conn, "code", "m", {c: [True] for c in cases}, budget=4096)
    _run(conn, "code", "m", {c: [False] for c in cases}, budget=8192)
    _run(conn, "code", "other", {c: [False] for c in cases}, budget=4096)
    assert effects.churn(conn).get("code", {}).get("cases", 0) == 0


def test_a_lane_with_too_few_rerun_cases_keeps_the_default_effect(conn):
    _run(conn, "tts", "m", {f"c{i}": [True, False] for i in range(effects.MIN_CASES - 1)})
    got = effects.derive(conn)["tts"]
    assert got["cases"] == effects.MIN_CASES - 1
    assert got["effect"] is None
    _run(conn, "tts", "m", {"extra": [True, True]})
    assert effects.derive(conn)["tts"]["effect"] is not None


def test_a_churn_under_the_floor_registers_the_floor(conn):
    _run(conn, "decide", "m", {f"c{i}": [True, i != 0] for i in range(40)})
    from harness import cuts
    effects.derive(conn, record=False)
    cuts.flush(conn)
    assert conn.execute("SELECT COUNT(*) FROM limit_cuts").fetchone()[0] == 0
    got = effects.derive(conn)["decide"]
    assert 0 < got["churn"] < effects.FLOOR
    assert got["effect"] == effects.FLOOR
    cuts.flush(conn)
    knob, what = conn.execute("SELECT knob, what FROM limit_cuts").fetchone()
    assert knob == "adopt_effect_floor" and "decide 0.0125" in what


def test_soh_knobs_effects_reads_a_copy_and_writes_nothing_to_this_home(conn, tmp_path, capsys):
    from harness import cli
    _run(conn, "decide", "m", {f"c{i}": [True, i != 0] for i in range(40)})
    copy = tmp_path / "copy.db"
    conn.execute(f"VACUUM INTO '{copy}'")
    assert cli.main(["knobs", "effects", "--store", str(copy)]) == 0
    out = capsys.readouterr().out
    assert "decide" in out and "0.0125" in out and "replay: 0 adopt verdict(s)" in out
    from harness import cuts
    cuts.flush(conn)
    assert conn.execute("SELECT COUNT(*) FROM limit_cuts").fetchone()[0] == 0


def test_the_effect_knob_registers_each_lane_effect_with_its_unit_and_range():
    k = knobs.KNOBS["adopt_effect"]
    assert k.unit == "share"
    assert power.EFFECT, "the per-lane effects are registered"
    for lane, value in power.EFFECT.items():
        assert value >= effects.FLOOR
        assert k.default(lane) == value == power.effect_for(lane)
        assert value in k.values_for(lane), lane
    assert power.effect_for("no-such-lane") == power.DEFAULT_EFFECT
    for name in ("adopt_effect_floor", "adopt_effect_min_cases"):
        assert name in knobs.KNOBS


@pytest.mark.gauntlet("a-closed-table-fronting-an-open-set", site="harness/power.py:EFFECT")
def test_a_lane_the_effect_table_does_not_name_plans_at_the_default():
    from harness import lanes
    assert set(power.EFFECT) <= set(lanes.ALL)
    for lane in set(lanes.ALL) - set(power.EFFECT):
        assert power.effect_for(lane) == power.DEFAULT_EFFECT
    assert power.effect_for(" Code ") == power.EFFECT["code"]


def _verdict(c, lane, outcome, detail, failure_class="", plan=None, name="org/x"):
    ms.record(c, ms.Seen(name=name, source="test", lane=lane))
    vid = ms.decide(c, name, outcome, tier=ms.ADOPT, detail=detail, reason=reasons.LIMIT if failure_class else reasons.CANDIDATE)
    c.execute("UPDATE verdicts SET failure_class = ?, power = ? WHERE id = ?",
              (failure_class, json.dumps(plan or {}), vid))
    c.commit()
    return vid


def test_replay_names_a_powered_null_that_a_smaller_effect_makes_underpowered(conn):
    null = _verdict(conn, "code", "declined", "code: better on the metric, but 3 lost against 5 gained is p=0.73",
                    plan={"effect": 0.2, "mde": 0.15, "enough": True, "target": 0.8, "power": 0.9}, name="org/a")
    worse = _verdict(conn, "code", "declined", "code: does not beat the incumbent; significantly worse: 9 lost",
                     plan={"effect": 0.2, "mde": 0.15, "enough": True, "target": 0.8}, name="org/b")
    won = _verdict(conn, "svg", "measured", "svg: beats local-large on the lane's metric, 8 gained against 0 lost",
                   name="org/c")
    same = {r["id"]: r for r in effects.replay(conn, {"code": 0.2})}
    assert same[null]["replayed"] == same[null]["stored"] == "candidate"
    got = {r["id"]: r for r in effects.replay(conn, {"code": 0.1})}
    assert (got[null]["stored"], got[null]["replayed"]) == ("candidate", reasons.UNDERPOWERED)
    assert got[worse]["replayed"] == "candidate"
    assert (got[won]["stored"], got[won]["replayed"]) == ("adopted", reasons.CONFIRMING)


def test_the_power_header_names_each_lanes_effect(conn, monkeypatch, capsys):
    monkeypatch.setattr(power, "EFFECT", {"code": 0.06})
    monkeypatch.setattr(holdout, "splits", lambda root=None: {"code": holdout.Split("code", ("d1",), ("h1",), False)})
    monkeypatch.setattr(adopt_cmd, "_profile", lambda lane, receipts, conn: ("k", "s", {}, None, (0, ()), []))
    monkeypatch.setattr(power, "pair_cost", lambda *a, **k: (None, 2, {}))
    monkeypatch.setattr(adopt, "comparisons", lambda conn, lane, version: 0)
    adopt_cmd.cmd_power(argparse.Namespace(lane="code", receipt=None, challenger="", effect=None,
                                           power_budget_min=None))
    head = capsys.readouterr().out.splitlines()[0]
    assert "+0.20" not in head
    assert "each lane's effect" in head


# --- the confirmation ------------------------------------------------------

SPLIT = holdout.Split("code", dev=tuple(f"d{i}" for i in range(10)), holdout=("h1", "h2", "h3"), too_small=False)


def _rows(cells, inc="inc", ch="ch"):
    """cells: case -> (incumbent passed, challenger passed)."""
    out = []
    for case, (i, c) in cells.items():
        out.append({"candidate": inc, "case_id": case, "passed": i, "seconds": 1.0, "metrics": {}})
        out.append({"candidate": ch, "case_id": case, "passed": c, "seconds": 1.0, "metrics": {}})
    return out


def _won(lane="code"):
    return adopt.Verdict(lane, "inc", "ch", True, "beats inc on the lane's metric, 3 gained against 0 lost, p=0.01",
                         evidence={"split": SPLIT.as_dict()})


def test_a_holdout_win_whose_dev_cells_confirm_it_is_adopted():
    rows = _rows({**{f"d{i}": (False, True) for i in range(8)}, "d8": (True, True), "d9": (True, True)})
    got = adopt.confirm(_won(), rows, SPLIT)
    assert got.adopt, got.why
    assert "confirmed on 10 dev case(s): 8 gained against 0 lost" in got.why
    assert got.evidence["confirm"]["gained"] == 8


def test_a_holdout_win_that_dev_does_not_confirm_is_not_served():
    tie = _rows({**{f"d{i}": (False, True) for i in range(3)}, **{f"d{i}": (True, False) for i in range(3, 4)},
                 **{f"d{i}": (True, True) for i in range(4, 10)}})
    got = adopt.confirm(_won(), tie, SPLIT)
    assert not got.adopt
    assert got.failure_class == reasons.UNDERPOWERED, got.why
    assert "not confirmed on 10 dev case(s): 3 gained against 1 lost" in got.why and "detectable" in got.why
    worse = _rows({f"d{i}": (True, False) for i in range(10)})
    got = adopt.confirm(_won(), worse, SPLIT)
    assert not got.adopt and got.failure_class == ""
    assert "significantly worse" in got.why
    assert adopt.outcome_of(got) == ("declined", reasons.CANDIDATE)


def test_cases_the_challenger_was_screened_on_are_not_confirmation_cells(conn):
    rows = _rows({**{f"d{i}": (False, True) for i in range(8)}, "d8": (True, True), "d9": (True, True)})
    _run(conn, "code", "ch", {f"d{i}": [True] for i in range(8)}, tier="screen")
    _run(conn, "code", "ch", {"d9": [True]}, tier="measure")
    _run(conn, "code", "inc", {"d8": [True]}, tier="screen")
    seen = adopt.screened_cases(conn, "code", ("ch",))
    assert seen == frozenset(f"d{i}" for i in range(8))
    cells = adopt.confirmation_cells(rows, SPLIT, seen)
    assert {holdout.base_id(r["case_id"]) for r in cells} == {"d8", "d9"}
    got = adopt.confirm(_won(), rows, SPLIT, seen)
    assert not got.adopt and "not confirmed on 2 dev case(s)" in got.why


def test_a_holdout_win_with_no_dev_rows_is_held_and_queues_a_night_confirmation(conn, tmp_path):
    rows = _rows({"h1": (False, True), "h2": (False, True), "h3": (False, True)})
    got = adopt.confirm(_won(), rows, SPLIT)
    assert not got.adopt and got.failure_class == reasons.CONFIRMING
    assert adopt.outcome_of(got) == ("declined", reasons.LIMIT)
    small = holdout.Split("svg", ("a", "b", "c"), ("a", "b", "c"), True)
    assert adopt.confirm(_won("svg"), _rows({"a": (False, True)}), small).failure_class == reasons.CONFIRMING
    got = adopt.Verdict(got.lane, got.incumbent, got.challenger, got.adopt, got.why, got.how, got.failure_class,
                        {**got.evidence, "confirm": {**got.evidence["confirm"], "incumbent": "inc-spec",
                                                      "challenger": "org/x", "repeat": 1}})
    ms.record(conn, ms.Seen(name="org/x", source="test", lane="code"))
    now = time.time()
    measure_cmd._record(got, "org/x", None, tmp_path / "no-run")
    vid = conn.execute("SELECT MAX(id) FROM verdicts").fetchone()[0]
    assert conn.execute("SELECT COUNT(*) FROM adoptions").fetchone()[0] == 0
    jobs = workqueue.pending(conn)
    assert len(jobs) == 1
    job = conn.execute("SELECT argv, not_before, night_gate FROM jobs").fetchone()
    assert json.loads(job["argv"])[-2:] == ["--confirm", str(vid)]
    assert job["night_gate"] == 1
    assert job["not_before"] == pytest.approx(workqueue.night_start(now), abs=5)
    adopt.queue_confirmation(conn, vid, got)
    assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1


def _confirming(conn, tmp_path, monkeypatch, incumbent="inc-spec"):
    rows = _rows({"h1": (False, True), "h2": (False, True), "h3": (False, True)})
    held = adopt.confirm(_won(), rows, SPLIT, frozenset({"d0"}))
    held = adopt.Verdict(held.lane, held.incumbent, held.challenger, False, held.why, held.how, held.failure_class,
                         {**held.evidence, "confirm": {**held.evidence["confirm"], "incumbent": incumbent,
                                                        "challenger": "org/x", "repeat": 1}})
    ms.record(conn, ms.Seen(name="org/x", source="test", lane="code"))
    monkeypatch.setattr(adopt, "queue_confirmation", lambda *a, **k: None)
    measure_cmd._record(held, "org/x", None, tmp_path / "no-run")
    monkeypatch.setattr(holdout, "for_lane", lambda lane, root=None: SPLIT)
    monkeypatch.setattr(adopt, "default_for", lambda lane, fallback, conn=None: "inc-spec")
    monkeypatch.setattr(screen, "candidate_for", lambda lane, name: name)
    return conn.execute("SELECT MAX(id) FROM verdicts").fetchone()[0]


def _fake_run(monkeypatch, cells, seen):
    class Done:
        returncode = 0
        stderr = ""

    def launch(argv, **kw):
        seen["argv"] = argv
        return Done()

    rows = _rows(cells, inc="inc-key", ch="ch-key")
    for r in rows:
        r["candidate"] = r["candidate"]
    summary = {k: {"passed": sum(r["passed"] for r in rows if r["candidate"] == k), "total": len(cells),
                   "pass_rate": 0.5, "median_s": 1.0, "metrics": {}} for k in ("inc-key", "ch-key")}
    monkeypatch.setattr(measure_cmd, "_launch", launch)
    monkeypatch.setattr(measure_cmd, "_receipt_at", lambda out: {
        "specs": {"inc-key": "inc-spec", "ch-key": "org/x"}, "summary": summary, "rows": rows})


def test_the_confirmation_job_adopts_when_dev_confirms_the_win(conn, tmp_path, monkeypatch):
    vid = _confirming(conn, tmp_path, monkeypatch)
    seen = {}
    _fake_run(monkeypatch, {**{f"d{i}": (False, True) for i in range(9)}, "d9": (True, True)}, seen)
    assert adopt_cmd.cmd_adopt(argparse.Namespace(power=False, from_measurement=False, confirm=vid)) == 0
    argv = seen["argv"]
    assert argv[argv.index("--split") + 1] == "dev"
    assert argv[argv.index("--candidates") + 1] == "inc-spec,org/x"
    row = conn.execute("SELECT outcome, detail FROM verdicts ORDER BY id DESC LIMIT 1").fetchone()
    assert row["outcome"] == "measured", row["detail"]
    assert "confirmed on 9 dev case(s)" in row["detail"]
    assert conn.execute("SELECT COUNT(*) FROM adoptions WHERE lane = 'code'").fetchone()[0] == 1


def test_the_confirmation_job_declines_when_dev_shows_the_challenger_worse(conn, tmp_path, monkeypatch):
    vid = _confirming(conn, tmp_path, monkeypatch)
    _fake_run(monkeypatch, {f"d{i}": (True, False) for i in range(10)}, {})
    assert adopt_cmd.cmd_adopt(argparse.Namespace(power=False, from_measurement=False, confirm=vid)) == 0
    row = conn.execute("SELECT outcome, reason, detail FROM verdicts ORDER BY id DESC LIMIT 1").fetchone()
    assert (row["outcome"], row["reason"]) == ("declined", reasons.CANDIDATE), row["detail"]
    assert "significantly worse" in row["detail"]
    assert conn.execute("SELECT COUNT(*) FROM adoptions").fetchone()[0] == 0


def test_a_confirmation_against_a_changed_incumbent_records_nothing(conn, tmp_path, monkeypatch, capsys):
    vid = _confirming(conn, tmp_path, monkeypatch, incumbent="older-spec")
    seen = {}
    _fake_run(monkeypatch, {f"d{i}": (False, True) for i in range(10)}, seen)
    before = conn.execute("SELECT COUNT(*) FROM verdicts").fetchone()[0]
    assert adopt_cmd.cmd_adopt(argparse.Namespace(power=False, from_measurement=False, confirm=vid)) == 0
    assert "argv" not in seen
    assert conn.execute("SELECT COUNT(*) FROM verdicts").fetchone()[0] == before
    assert "no longer serves older-spec" in capsys.readouterr().out


# --- the confirmation's exact record ---------------------------------------

DECIDE = holdout.Split("decide", dev=tuple(f"d{i}" for i in range(10)), holdout=("h1", "h2", "h3"), too_small=False)


def _row(who, case, passed, accuracy):
    return {"candidate": who, "case_id": case, "passed": passed, "seconds": 1.0,
            "metrics": {"decide_accuracy": accuracy}}


def _plain(why="won"):
    return adopt.Verdict("decide", "inc", "ch", True, why)


def test_the_confirmation_reads_the_lane_metric_and_keeps_the_evidence_it_was_given():
    ids = [f"d{i}" for i in range(10)]
    rows = [x for c in ids for x in (_row("inc", c, c in ("d0", "d1"), 0.5), _row("ch", c, False, 1.0))]
    v = adopt.Verdict("decide", "inc", "ch", True, "won", evidence={"x": 1, "confirm": {"kept": 1}})
    got = adopt.confirm(v, rows, DECIDE, frozenset({"z9"}))
    assert got.adopt is True and got.failure_class == ""
    assert got.why == "won; confirmed on 10 dev case(s): 10 gained against 0 lost, p=0.002"
    assert got.evidence == {"x": 1, "confirm": {"kept": 1, "screened": ["z9"], "cases": 10, "gained": 10, "lost": 0,
                                                "p": 0.001953125}}


def test_a_confirmation_over_correlated_repeats_says_how_it_counted_them():
    rows = [x for i in range(10) for k in (1, 2)
            for x in (_row("inc", f"d{i}#{k}", False, 0.0), _row("ch", f"d{i}#{k}", False, 1.0))]
    got = adopt.confirm(_plain(), rows, DECIDE)
    assert got.why == ("won; confirmed on 10 dev case(s): 20 gained against 0 lost, p=0.002 (10 gained against 0 "
                       "lost once correlated repeats are counted as cases (rho 1.00 assumed, repeat 2.0))")


def test_a_worse_and_a_held_confirmation_are_recorded_exactly():
    ids = [f"d{i}" for i in range(10)]
    rows = [x for c in ids for x in (_row("inc", c, True, 1.0), _row("ch", c, False, 0.0))]
    got = adopt.confirm(_plain(), rows, DECIDE)
    assert got.adopt is False and got.failure_class == ""
    assert got.why == ("won the holdout, but on 10 dev case(s) it is significantly worse: 10 lost against 0 gained, "
                       "p=0.00 (won)")
    assert got.evidence == {"confirm": {"screened": [], "cases": 10, "gained": 0, "lost": 10, "p": 0.001953125}}
    held = adopt.confirm(_plain(), [], DECIDE)
    assert held.adopt is False and held.failure_class == reasons.CONFIRMING
    assert held.why == ("held for confirmation: no case outside the holdout ran, so the incumbent serves until a "
                        "night run of the dev cases confirms it (won)")
    assert held.evidence == {"confirm": {"screened": []}}


def test_an_unconfirmed_win_names_the_smallest_gain_its_cells_could_see():
    split = holdout.Split("decide", dev=tuple(f"d{i}" for i in range(40)), holdout=("h1", "h2", "h3"), too_small=False)
    rows = []
    for i in range(40):
        inc = 0.0 if i < 20 else 1.0
        ch = (1.0 if i < 12 else 0.0) if i < 20 else (0.0 if i < 28 else 1.0)
        rows += [_row("inc", f"d{i}", False, inc), _row("ch", f"d{i}", False, ch)]
    got = adopt.confirm(_plain(), rows, split)
    assert got.adopt is False and got.failure_class == reasons.UNDERPOWERED
    assert got.why == ("won the holdout, not confirmed on 40 dev case(s): 12 gained against 8 lost, p=0.503; smallest "
                       "gain these cells could see: +0.38 per cell at power 0.8; this null is not evidence of no "
                       "difference (won)")
    assert got.evidence["confirm"] == {"screened": [], "cases": 40, "gained": 12, "lost": 8,
                                       "p": pytest.approx(0.5034, abs=1e-4)}


def test_the_smallest_gain_reads_lane_metric_draws_and_their_correlation():
    cells = []
    for i in range(40):
        if i < 10:
            cells += [_row("inc", f"d{i}#1", False, 0.0), _row("inc", f"d{i}#2", False, 1.0)]
        else:
            cells += [_row("inc", f"d{i}", False, 0.0 if i < 25 else 1.0)]
    assert adopt._confirm_sees(cells, "inc", "decide") == "; smallest gain these cells could see: +0.36 per cell at power 0.8"
    two = []
    for i in range(40):
        a, b = (0.0, 1.0) if i < 10 else ((0.0, 0.0) if i < 25 else (1.0, 1.0))
        two += [_row("inc", f"d{i}#1", False, a), _row("inc", f"d{i}#2", False, b)]
    assert power.rows_icc([{**r, "passed": power.draw(r, "decide")} for r in two], ("inc",)) == (
        pytest.approx(0.5094, abs=1e-4), 2.0)
    assert adopt._confirm_sees(two, "inc", "decide") == "; smallest gain these cells could see: +0.30 per cell at power 0.8"


def test_a_confirmation_worse_on_the_lane_metric_alone_is_a_loss():
    ids = [f"d{i}" for i in range(10)]
    rows = [x for c in ids for x in (_row("inc", c, False, 1.0), _row("ch", c, False, 0.0))]
    got = adopt.confirm(_plain(), rows, DECIDE)
    assert got.failure_class == "" and "significantly worse: 10 lost against 0 gained" in got.why


def test_a_lane_named_by_nothing_reads_screens_stored_without_one(conn):
    _run(conn, "", "ch", {"x1": [True]}, tier="screen")
    assert adopt.screened_cases(conn, None, ("ch",)) == frozenset({"x1"})
    assert adopt.screened_cases(conn, "code", ("", None)) == frozenset()


def test_only_a_measured_gate_win_is_confirmed():
    rows = _rows({"d0": (False, True)})
    hand = adopt.Verdict("code", "inc", "ch", True, "preferred by hand", adopt.BY_HAND)
    assert adopt.confirm(hand, rows, SPLIT) is hand
    lost = adopt.Verdict("code", "inc", "ch", False, "no")
    assert adopt.confirm(lost, rows, SPLIT) is lost


def test_confirmation_cells_come_from_dev_and_a_fresh_run_of_a_lane_too_small_to_split():
    small = holdout.Split("svg", ("a", "b"), ("a", "b"), True)
    rows = _rows({"a": (False, True), "b": (True, True)})
    assert adopt.confirmation_cells(rows, small) == []
    assert adopt.confirmation_cells(rows, small, fresh=True) == rows
    assert adopt.confirmation_cells(rows, small, frozenset({"a"}), True) == rows[2:]
    assert adopt.confirmation_cells(rows, None) == []
    assert adopt.confirmation_cells([], SPLIT) == []
    got = adopt.confirm(_won("svg"), _rows({"a": (False, True), "b": (False, True), "c": (False, True)}),
                        holdout.Split("svg", ("a", "b", "c"), ("a", "b", "c"), True), fresh=True)
    assert "on 3 dev case(s)" in got.why


def test_the_confirmation_job_is_the_adopt_command_and_lands_in_the_given_store(conn, monkeypatch, tmp_path):
    import sys
    monkeypatch.chdir(tmp_path)
    assert adopt.confirm_argv(12) == [sys.executable, "-m", "harness.cli", "adopt", "--confirm", "12"]

    def elsewhere(*a, **k):
        raise AssertionError("opened another store")

    monkeypatch.setattr(ms, "connect", elsewhere)
    v = adopt.Verdict("code", "inc", "ch", False, "held", failure_class=reasons.CONFIRMING)
    assert adopt.queue_confirmation(conn, 12, v, now=0.0) is not None
    row = conn.execute("SELECT title, cwd, requested_by, not_before FROM jobs").fetchone()
    assert dict(row) == {"title": "confirm code: ch over inc on dev (verdict 12)", "cwd": str(paths.REPO),
                         "requested_by": "adopt", "not_before": workqueue.night_start(0.0)}
    conn.execute("UPDATE jobs SET state = ?", (workqueue.DONE,))
    assert adopt.queue_confirmation(conn, 12, v, now=0.0) is not None, "a finished confirmation does not block a new one"
