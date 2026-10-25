"""A knob sweep ranks, pairs, plans power and calls itself uninformative on the lane's metric, not exact-case pass bits. #1219."""
from harness import paired, power, reasons, sweeps
from harness.checks import claims as claims_check
from tests.test_reverify_lane_metric_733 import NOW, conn, fields, on, record  # noqa: F401

ALPHA = 0.05


def decide(accs, seconds=1.0):
    return [{"candidate": "m", "case_id": f"c{i}", "passed": a >= 1.0, "seconds": seconds,
             "failure_class": "" if a >= 1.0 else "content_failed", "metrics": fields(a)} for i, a in enumerate(accs)]


def repo(resolved, seconds=1.0):
    return [{"candidate": "m", "case_id": f"c{i}", "passed": ok, "seconds": seconds,
             "failure_class": "" if ok else "content_failed", "metrics": {"resolved": float(ok)}}
            for i, ok in enumerate(resolved)]


def claims(recall_ok, empty_ok, seconds=1.0):
    def row(case, ok, stratum):
        return {"candidate": "m", "case_id": case, "passed": ok, "seconds": seconds,
                "failure_class": "" if ok else "content_failed", "metrics": {claims_check.STRATUM: stratum}}
    return ([row(f"r{i}", ok, 0) for i, ok in enumerate(recall_ok)]
            + [row(f"e{i}", ok, 1) for i, ok in enumerate(empty_ok)])


def test_a_value_that_keeps_the_exact_count_but_loses_field_accuracy_is_not_tied():
    """Both values get 10 of 40 cases right in full; the cheap one is right on 0.4 of the other fields, not 0.8."""
    cheap = decide([1.0] * 10 + [0.4] * 30, seconds=1.0)
    dear = decide([1.0] * 10 + [0.8] * 30, seconds=2.0)
    chosen, table = sweeps.decide([2000, 4000], {2000: cheap, 4000: dear}, ALPHA, lane="decide")
    assert chosen == 4000
    assert table["2000"]["lost"] == 30 and table["2000"]["gained"] == 0
    assert not table["2000"]["tied"]


def test_the_best_value_is_the_one_better_on_the_lane_metric():
    """More exact cases at worse field accuracy is not the best on decide."""
    exact = decide([1.0] * 3 + [0.2] * 37, seconds=1.0)
    sharp = decide([1.0] * 2 + [0.9] * 38, seconds=2.0)
    _, table = sweeps.decide([2000, 4000], {2000: exact, 4000: sharp}, ALPHA, lane="decide")
    assert table["4000"]["best"] and not table["2000"]["best"]


def test_a_floored_decide_sweep_is_informative_and_powered():
    """No case right in full at either value, field accuracy 0.8 at both: a tie with power to see a loss, so the cheap one."""
    chosen, table = sweeps.decide([2000, 4000], {2000: decide([0.8] * 200, 1.0), 4000: decide([0.8] * 200, 2.0)},
                                  ALPHA, power.effect_for("decide"), lane="decide")
    assert not sweeps.flat(table)
    assert table["4000"]["power"] > 0
    assert chosen == 2000


def test_the_power_to_see_a_loss_counts_room_on_the_metric():
    """A row right on 0.8 of its fields can lose; on pass bits it reads as already lost."""
    best = decide([0.8] * 200)
    cell = paired.pair(best, best, same_repeat=True, metric="decide_accuracy")
    on_metric = sweeps._power_to_see_a_loss(best, cell, ALPHA, 0.1, "decide_accuracy", 0.0)
    assert on_metric > 0.8
    assert sweeps._power_to_see_a_loss(best, cell, ALPHA, 0.1, "", 0.0) == 0.0


def test_a_decide_sweep_at_the_floor_of_its_metric_is_uninformative():
    chosen, table = sweeps.decide([2000, 4000], {2000: decide([0.0] * 20), 4000: decide([0.0] * 20, 2.0)},
                                  ALPHA, lane="decide")
    assert chosen is None and sweeps.flat(table) == "every value passed 0 of its cases"
    assert table["2000"]["room"] == 0


def test_a_decide_sweep_at_its_best_on_every_case_is_uninformative():
    chosen, table = sweeps.decide([2000, 4000], {2000: decide([1.0] * 20), 4000: decide([1.0] * 20, 2.0)},
                                  ALPHA, lane="decide")
    assert chosen is None and sweeps.flat(table)


def stt(wers, seconds=1.0):
    return [{"candidate": "m", "case_id": f"clip{i}", "passed": False, "seconds": seconds,
             "failure_class": "content_failed", "metrics": {"wer": w, "wer_errors": round(w * 20), "wer_words": 20}}
            for i, w in enumerate(wers)]


def test_an_stt_sweep_with_no_word_perfect_clip_pairs_on_wer():
    """No clip passes at either value; the cheap one doubles the WER on every clip, so it is worse, not a floor."""
    chosen, table = sweeps.decide([10, 60], {10: stt([0.2] * 40, 1.0), 60: stt([0.1] * 40, 2.0)}, ALPHA, lane="stt")
    assert not sweeps.flat(table)
    assert table["60"]["best"] and table["10"]["lost"] == 40
    assert chosen == 60


def test_a_claims_sweep_pairs_per_stratum_at_the_lane_weights():
    """10 recall cases lost for 10 of 50 expect-empty gained: 10 against 10 on pass bits, a loss at the lane's weights."""
    dear = claims([True] * 10, [True] * 40 + [False] * 10, seconds=2.0)
    cheap = claims([False] * 10, [True] * 50, seconds=1.0)
    chosen, table = sweeps.decide([2000, 4000], {2000: cheap, 4000: dear}, ALPHA, lane="claims")
    assert table["4000"]["best"]
    assert table["2000"]["lost"] > table["2000"]["gained"]
    assert chosen == 4000 and not table["2000"]["tied"]


def test_a_timeout_with_no_metric_scores_the_floor_not_below_it():
    """Sweep 4's shape: a timeout row stores no `resolved`; paired with a finished-wrong row of that case it is no change."""
    best = repo([True] * 9 + [False] * 31)
    best[-1].update(failure_class=reasons.TIMEOUT, metrics={})
    other = repo([True] * 9 + [False] * 31, seconds=2.0)
    _, table = sweeps.decide([8000, 16384], {8000: best, 16384: other}, ALPHA, lane="repo")
    assert table["8000"]["best"]
    assert (table["16384"]["lost"], table["16384"]["gained"]) == (0, 0)


def test_a_repo_sweep_chooses_as_it_did_on_pass_bits():
    """resolved is the pass bit on repo, so the metric changes nothing there."""
    values = {2000: repo([True] * 18 + [False] * 22, 1.0), 4000: repo([True] * 20 + [False] * 20, 2.0)}
    chosen, bits = sweeps.decide([2000, 4000], {v: [{**r, "metrics": {}} for r in rows] for v, rows in values.items()},
                                 ALPHA)
    got, table = sweeps.decide([2000, 4000], values, ALPHA, lane="repo")
    assert got == chosen
    assert {v: {k: row[k] for k in bits[v]} for v, row in table.items()} == bits


def test_the_settled_detail_names_the_lane_metric():
    sw = {"knob": "reply_budget", "lane": "decide", "spec": "m"}
    chosen, cost = sweeps.decide([2000, 4000], {2000: decide([0.8] * 200, 1.0), 4000: decide([0.8] * 200, 2.0)},
                                 ALPHA, lane="decide")
    assert "decide_accuracy 0.800" in sweeps.detail(sw, chosen, cost)


def test_a_decide_model_with_no_exact_case_but_right_fields_is_one_a_sweep_can_see(conn):
    record(conn, "decide", [("imajev", f"c{i}", False, fields(0.8)) for i in range(10)], at=NOW)
    got = next(iter(sweeps.passing(conn, "decide", None).values()))
    assert got["passed"] == 0 and got["working"]


def test_the_served_decide_model_with_no_exact_case_is_swept(conn):
    record(conn, "decide", [("imajev", f"c{i}", False, fields(0.8)) for i in range(10)], at=NOW)
    item = {"lane": "decide", "spec": "imajev", "candidate_id": None, "incumbent": "", "incumbent_id": None}
    assert sweeps.model(conn, item, None) == (item, "")


def test_a_decide_model_that_gets_every_field_wrong_is_not(conn):
    record(conn, "decide", [("imajev", f"c{i}", False, fields(0.0)) for i in range(10)], at=NOW)
    assert not next(iter(sweeps.passing(conn, "decide", None).values()))["working"]


def test_below_reads_the_lane_metric(conn):
    """Equal exact counts; the swept model is right on fewer fields than its incumbent in the same run."""
    rows = ([("mine", f"c{i}", i < 2, fields(1.0 if i < 2 else 0.4)) for i in range(10)]
            + [("inc", f"c{i}", i < 2, fields(1.0 if i < 2 else 0.8)) for i in range(10)])
    rid = record(conn, "decide", rows, at=NOW)
    got = sweeps.below(conn, "decide", "mine", ["inc"], None)
    assert got and f"run {rid}" in got and "decide_accuracy" in got
    assert sweeps.below(conn, "decide", "inc", ["mine"], None) == ""
