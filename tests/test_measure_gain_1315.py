"""#1315: the measure queue is ordered by expected gain per GPU-minute, from stored paired cells and screens."""
import json

import pytest

from harness import measure_gain, measure_replay
from harness import memory_store as ms
from harness.commands import loop

NOW = 2_000_000_000.0
DAY = 86400.0
INC = "llamacpp:Ornith-1.5-35B-Q4_K_M"


@pytest.fixture
def conn(tmp_path):
    c = ms.connect(tmp_path / "s.db")
    yield c
    c.close()


@pytest.fixture
def price(monkeypatch):
    """Minutes per row name, set by each test; a name left out is unpriced."""
    got: dict = {}
    monkeypatch.setattr(measure_gain, "minutes", lambda conn, row, lane: (got.get(row["name"]), "unpriced in the test"))
    monkeypatch.setattr(measure_gain, "incumbent_rates", lambda conn, lane: {f"c{i}": 0.5 for i in range(40)})
    return got


def proposal(conn, name, lane="code", parents=()):
    ms.record(conn, ms.Seen(name=name, source="t", lane=lane))
    pid = conn.execute("SELECT id FROM proposals WHERE name = ?", (name,)).fetchone()[0]
    for p in parents:
        conn.execute("INSERT OR IGNORE INTO lineage (proposal_id, parent, kind) VALUES (?, ?, 'finetune')", (pid, p))
    conn.commit()
    return pid


def candidate(conn, spec, key, pid=None, lane="code"):
    conn.execute("INSERT OR IGNORE INTO candidates (proposal_id, spec, receipt_key, lane, created_at) VALUES (?, ?, ?, ?, ?)",
                 (pid, spec, key, lane, NOW))
    return conn.execute("SELECT id FROM candidates WHERE spec = ?", (spec,)).fetchone()[0]


def paired_run(conn, name, gained, lost, same, *, lane="code", at=NOW - 10 * DAY, key=None, parents=()):
    """A measure run of `name` against the incumbent: `gained` cells it alone passed, `lost` the incumbent alone, `same` both."""
    pid = proposal(conn, name, lane, parents)
    key = key or name.replace(":", "/", 1)
    ch, inc = candidate(conn, name, key, pid, lane), candidate(conn, INC, INC, None, lane)
    cur = conn.execute("INSERT INTO runs (path, lane, tier, specs, recorded_at, generated_at) VALUES (?, ?, 'measure', ?, ?, ?)",
                       (f"r-{name}-{at}", lane, json.dumps({INC: INC, key: name}), at, at))
    run_id = cur.lastrowid
    cells = [(1, 0)] * gained + [(0, 1)] * lost + [(1, 1)] * same
    seq = 0
    for i, (mine, theirs) in enumerate(cells):
        for cid, k, passed in ((ch, key, mine), (inc, INC, theirs)):
            seq += 1
            conn.execute("INSERT INTO results (run_id, seq, candidate_id, candidate, case_id, passed) VALUES (?, ?, ?, ?, ?, ?)",
                         (run_id, seq, cid, k, f"c{i}", passed))
    conn.execute("INSERT INTO verdicts (proposal_id, outcome, tier, detail, decided_at, reason, run_id) "
                 "VALUES (?, 'declined', 'adopt', ?, ?, 'candidate', ?)", (pid, f"{lane}: t", at, run_id))
    conn.commit()
    return run_id


def screen(conn, name, passed, *, lane="code", at=NOW - 5 * DAY, parents=()):
    """A screen run of `name` alone, its rows' pass bits `passed`, and its screened verdict."""
    pid = proposal(conn, name, lane, parents)
    cid = candidate(conn, name, name, pid, lane)
    run_id = conn.execute("INSERT INTO runs (path, lane, tier, recorded_at) VALUES (?, ?, 'screen', ?)",
                          (f"s-{name}-{at}", lane, at)).lastrowid
    for i, p in enumerate(passed):
        conn.execute("INSERT INTO results (run_id, seq, candidate_id, candidate, case_id, passed) VALUES (?, ?, ?, ?, ?, ?)",
                     (run_id, i, cid, name, f"c{i}", p))
    conn.commit()
    ms.decide(conn, name, "screened", tier=ms.SCREEN, at=at, reason="candidate", detail="1 case(s) passed a screen")


def names(conn, rows, before=None):
    return [r["name"] for r in measure_gain.order(conn, rows, before=before)[0]]


def r(name, lane="code"):
    return {"name": name, "lane": lane}


def test_a_cheaper_crossing_with_equal_evidence_measures_first(conn, price):
    paired_run(conn, "plan:" + INC, 6, 2, 20)
    price.update({"best-of:3:" + INC: 300.0, "plan:" + INC: 100.0})
    rows = [r("best-of:3:" + INC), r("plan:" + INC)]
    paired_run(conn, "best-of:3:" + INC, 6, 2, 20, at=NOW - 9 * DAY)
    assert names(conn, rows) == ["plan:" + INC, "best-of:3:" + INC]
    price["plan:" + INC] = 600.0
    assert names(conn, rows) == ["best-of:3:" + INC, "plan:" + INC]


def test_a_crossing_with_stored_positive_evidence_outranks_an_unmeasured_model_of_equal_cost(conn, price):
    paired_run(conn, "plan:llamacpp:Other-27B", 12, 2, 30)
    price.update({"fresh/Model-27B": 200.0, "plan:" + INC: 200.0})
    rows = [r("fresh/Model-27B"), r("plan:" + INC)]
    assert names(conn, rows) == ["plan:" + INC, "fresh/Model-27B"]
    gains = {g.name: g for g in measure_gain.order(conn, rows)[1]}
    assert gains["plan:" + INC].evidence and gains["plan:" + INC].evidence[0].source.startswith("method run")
    k = measure_gain.RELATED_CELLS
    assert gains["plan:" + INC].evidence[0].cells == pytest.approx(44 * k / (44 + k))
    assert not gains["fresh/Model-27B"].evidence


def test_a_family_whose_members_lost_ranks_below_an_unmeasured_family_of_equal_cost(conn, price):
    for i in range(2):
        paired_run(conn, f"a{i}/Qwen3.6-27B-ft{i}", 0, 12, 10, parents=("Qwen/Qwen3.6-27B",))
    proposal(conn, "someone/Qwen3.6-27B-Tuned", parents=("Qwen/Qwen3.6-27B",))
    price.update({"someone/Qwen3.6-27B-Tuned": 200.0, "other/Gemma-4-27B": 200.0})
    rows = [r("someone/Qwen3.6-27B-Tuned"), r("other/Gemma-4-27B")]
    assert names(conn, rows) == ["other/Gemma-4-27B", "someone/Qwen3.6-27B-Tuned"]
    tuned = measure_gain.order(conn, rows)[1][1]
    assert [e.source.split()[0] for e in tuned.evidence] == ["family", "family"]


def test_evidence_after_the_replayed_night_is_not_read(conn, price):
    paired_run(conn, "plan:llamacpp:Other-27B", 12, 2, 30, at=NOW - DAY)
    price.update({"fresh/Model-27B": 200.0, "plan:" + INC: 200.0})
    rows = [r("fresh/Model-27B"), r("plan:" + INC)]
    assert names(conn, rows) == ["plan:" + INC, "fresh/Model-27B"]
    assert names(conn, rows, before=NOW - 2 * DAY) == ["fresh/Model-27B", "plan:" + INC]
    assert measure_gain.comparisons(conn, before=NOW - 2 * DAY) == []
    screen(conn, "fresh/Model-27B", [1, 1, 1, 1, 1], at=NOW - DAY)
    assert measure_gain.screen_rows(conn, "fresh/Model-27B", "code", before=NOW - 2 * DAY) == []
    assert len(measure_gain.screen_rows(conn, "fresh/Model-27B", "code")) == 5


def test_an_unpriced_row_keeps_its_place_after_the_priced_ones(conn, price):
    paired_run(conn, "plan:llamacpp:Other-27B", 12, 2, 30)
    price.update({"b/Priced-9B": 500.0, "d/Priced-4B": 50.0})
    rows = [r("plan:" + INC), r("b/Priced-9B"), r("c/Unpriced-1B"), r("d/Priced-4B")]
    got, gains = measure_gain.order(conn, rows)
    assert [x["name"] for x in got] == ["d/Priced-4B", "b/Priced-9B", "plan:" + INC, "c/Unpriced-1B"]
    assert [g.key is None for g in gains] == [False, False, True, True]
    assert "unpriced (unpriced in the test)" in gains[-1].line()


def test_equal_keys_keep_the_survivors_order(conn, price):
    price.update({n: 120.0 for n in ("z/Last-9B", "a/First-9B", "m/Mid-9B")})
    rows = [r("z/Last-9B"), r("a/First-9B"), r("m/Mid-9B")]
    assert names(conn, rows) == ["z/Last-9B", "a/First-9B", "m/Mid-9B"]
    assert names(conn, rows[::-1]) == ["m/Mid-9B", "a/First-9B", "z/Last-9B"]


def test_a_screen_that_beats_the_incumbents_rates_lifts_the_mean(conn, price):
    screen(conn, "good/Model-9B", [1, 1, 1, 1, 1])
    screen(conn, "bad/Model-9B", [0, 0, 0, 0, 0])
    price.update({"good/Model-9B": 100.0, "bad/Model-9B": 100.0})
    gains = {g.name: g for g in measure_gain.order(conn, [r("bad/Model-9B"), r("good/Model-9B")])[1]}
    assert gains["good/Model-9B"].mean > 0 > gains["bad/Model-9B"].mean
    want = (measure_gain.PRIOR_MEAN * measure_gain.PRIOR_CELLS + 5 * 0.5) / (measure_gain.PRIOR_CELLS + 5)
    assert gains["good/Model-9B"].mean == pytest.approx(want)


def test_own_paired_cells_count_in_full_and_a_relatives_are_shrunk(conn, price):
    paired_run(conn, "plan:" + INC, 30, 10, 60)
    paired_run(conn, "plan:llamacpp:Other-27B", 30, 10, 60)
    ctx = measure_gain.context(conn)
    evs = {e.source.split()[0]: e for e in measure_gain.evidence(ctx, "plan:" + INC, "code")}
    assert evs["own"].cells == 100 and evs["own"].net == 20
    k = measure_gain.RELATED_CELLS
    assert evs["method"].cells == pytest.approx(100 * k / (100 + k))
    assert evs["method"].net == pytest.approx(20 * k / (100 + k))
    assert not measure_gain.evidence(ctx, "plan:" + INC, "web"), "another lane's comparison says nothing here"


def test_expected_gain_counts_only_what_clears_the_lanes_effect():
    assert measure_gain.expected_gain(0.0, 1e-9, 0.05) == pytest.approx(0.0, abs=1e-12)
    assert measure_gain.expected_gain(0.2, 1e-9, 0.05) == pytest.approx(0.15)
    wide, narrow = measure_gain.expected_gain(0.0, 0.3, 0.05), measure_gain.expected_gain(0.0, 0.05, 0.05)
    assert wide > narrow > 0, "an unmeasured question is worth more the less is known"
    assert measure_gain.expected_gain(0.1, 0.1, 0.05) > measure_gain.expected_gain(0.0, 0.1, 0.05)


def test_the_measure_step_says_each_rows_key(conn, price, monkeypatch):
    from harness.commands import measure as measure_cmd
    paired_run(conn, "plan:llamacpp:Other-27B", 12, 2, 30)
    rows = [r("fresh/Model-27B"), r("plan:" + INC)]
    price.update({"fresh/Model-27B": 200.0, "plan:" + INC: 200.0})
    monkeypatch.setattr(measure_cmd, "measurable", lambda store, top, want="", **kw: list(rows))
    said: list[str] = []
    got = loop.measure_queue(conn, "", 0, room=lambda row: (True, None, ""), slots=0, say=said.append)
    assert [x["name"] for x in got] == ["plan:" + INC, "fresh/Model-27B"]
    gains = [s for s in said if s.strip().startswith("gain:")]
    assert gains[0].startswith(f"  gain: 1. plan:{INC} (code): gain ") and "key " in gains[0]
    assert "/h" in gains[0] and "method run" in gains[0]


def test_the_walk_cuts_what_the_window_leaves_no_time_for():
    rows = [r("a"), r("b"), r("c"), r("d")]
    mins = {"a": 30.0, "b": 500.0, "c": None, "d": 10.0}
    taken, cut = measure_replay.walk(rows, 3 * 3600, lambda row: mins[row["name"]])
    assert [x["name"] for x in taken] == ["a", "b", "c"]
    assert [x["spend_s"] for x in taken] == [1800.0, 7200.0, 1800.0], "a measurement takes one slice at most"
    assert [x["name"] for x in cut] == ["d"]


def test_the_replay_reads_survivors_as_they_stood_that_night(conn):
    screen(conn, "x/Early-9B", [1], at=NOW - 3 * DAY)
    screen(conn, "y/Late-9B", [1], at=NOW - DAY)
    ms.decide(conn, "x/Early-9B", "declined", tier=ms.ADOPT, at=NOW - 2 * DAY, reason="candidate", detail="code: lost")
    assert [x["name"] for x in measure_replay.survivors_at(conn, NOW - 2.5 * DAY)] == ["x/Early-9B"]
    assert [x["name"] for x in measure_replay.survivors_at(conn, NOW)] == ["y/Late-9B"]
    assert [x["name"] for x in measure_replay.survivors_at(conn, NOW)] == [x["name"] for x in ms.survivors(conn)]


def test_a_measurement_start_is_read_from_its_out_dir():
    import time
    at = measure_replay.started_at("/runs/20261026-020607-adopt-repo")
    assert time.strftime("%Y%m%d-%H%M%S", time.localtime(at)) == "20261026-020607"
    assert measure_replay.started_at("/runs/20261025-210009-387-0000-stt") is None


def test_a_priced_row_with_no_gain_still_goes_before_an_unpriced_one(conn, price, monkeypatch):
    monkeypatch.setattr(measure_gain, "expected_gain", lambda mean, sd, effect: 0.0)
    price["b/Priced-9B"] = 60.0
    assert names(conn, [r("a/Unpriced-9B"), r("b/Priced-9B")]) == ["b/Priced-9B", "a/Unpriced-9B"]


def test_a_comparison_counts_only_once_both_its_run_and_its_verdict_precede_the_night(conn):
    early = paired_run(conn, "plan:" + INC, 6, 2, 20, at=NOW - 3 * DAY)
    conn.execute("UPDATE verdicts SET decided_at = ? WHERE run_id = ?", (NOW - DAY, early))
    late = paired_run(conn, "best-of:3:" + INC, 6, 2, 20, at=NOW - 3 * DAY)
    conn.execute("UPDATE runs SET recorded_at = ? WHERE id = ?", (NOW - DAY, late))
    conn.commit()
    assert measure_gain.comparisons(conn, before=NOW - 2 * DAY) == []
    assert {c.run_id for c in measure_gain.comparisons(conn)} == {early, late}
