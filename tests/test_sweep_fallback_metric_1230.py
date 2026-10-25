"""A sweep's fallback model is ranked on a bound of the lane's metric, not its exact-case pass rate. #1230."""
from harness import reasons, sweeps
from harness.checks import claims as claims_check
from tests.test_reverify_lane_metric_733 import NOW, conn, on, record  # noqa: F401

SERVED = {"spec": "served", "candidate_id": None, "incumbent": "", "incumbent_id": None}


def decide(spec, exact, rights, n=10):
    """`exact` cases right on every field, then one case per entry of `rights` right on that many of n."""
    rows = [(spec, f"x{i}", True, {"decide_correct": n, "decide_fields": n, "decide_accuracy": 1.0}) for i in range(exact)]
    return rows + [(spec, f"c{i}", False, {"decide_correct": r, "decide_fields": n, "decide_accuracy": r / n})
                   for i, r in enumerate(rights)]


def stt(spec, exact, errors, words=20):
    rows = [(spec, f"x{i}", True, {"wer_errors": 0, "wer_words": words, "wer": 0.0}) for i in range(exact)]
    return rows + [(spec, f"c{i}", False, {"wer_errors": e, "wer_words": words, "wer": e / words})
                   for i, e in enumerate(errors)]


def claims(spec, recall, empty):
    """recall: pass bits on cases that expect claims; empty: on cases that expect none."""
    return ([(spec, f"r{i}", ok, {claims_check.STRATUM: 0}) for i, ok in enumerate(recall)]
            + [(spec, f"e{i}", ok, {claims_check.STRATUM: 1}) for i, ok in enumerate(empty)])


def test_two_exact_at_085_outrank_three_exact_at_06_on_decide(conn):
    record(conn, "decide", decide("three", 3, [6] * 5 + [5] * 12 + [5] * 4), at=NOW - 2)
    record(conn, "decide", decide("two", 2, [8] * 12 + [9] * 6 + [8] * 4), at=NOW - 1)
    got, note = sweeps.model(conn, {"lane": "decide", **SERVED}, None)
    assert got["spec"] == "two"
    assert "decide_accuracy 0.8" in note


def test_a_lower_word_error_rate_outranks_more_exact_transcripts_on_stt(conn):
    record(conn, "stt", stt("exact", 6, [12] * 18), at=NOW - 2)
    record(conn, "stt", stt("close", 2, [2] * 22), at=NOW - 1)
    got, note = sweeps.model(conn, {"lane": "stt", **SERVED}, None)
    assert got["spec"] == "close"
    assert "wer " in note


def test_a_balanced_claims_model_outranks_a_quiet_one_with_more_passes(conn):
    """quiet passes 21 of 24, mostly by emitting nothing; sharp passes 18 but finds every claim."""
    record(conn, "claims", claims("quiet", [True] + [False] * 3, [True] * 20), at=NOW - 2)
    record(conn, "claims", claims("sharp", [True] * 4, [True] * 14 + [False] * 6), at=NOW - 1)
    got, _ = sweeps.model(conn, {"lane": "claims", **SERVED}, None)
    assert got["spec"] == "sharp"


def test_a_claims_run_whose_strata_cover_a_few_rows_ranks_after_one_they_cover(conn):
    """eval-4b's run 419 shape: most rows predate the strata (#791), so its few stratum rows are not its score."""
    legacy = [("legacy", f"o{i}", True, {}) for i in range(14)] + claims("legacy", [True] * 5, [True] * 5)
    record(conn, "claims", legacy, at=NOW - 2)
    record(conn, "claims", claims("full", [True] * 3 + [False], [True] * 12 + [False] * 8), at=NOW - 1)
    got, _ = sweeps.model(conn, {"lane": "claims", **SERVED}, None)
    assert got["spec"] == "full"


def test_a_decide_metric_over_a_quarter_of_the_run_ranks_after_one_over_all_of_it(conn):
    part = decide("part", 6, []) + [("part", f"f{i}", False, {}) for i in range(18)]
    record(conn, "decide", part, at=NOW - 2)
    record(conn, "decide", decide("whole", 0, [7] * 24), at=NOW - 1)
    got, _ = sweeps.model(conn, {"lane": "decide", **SERVED}, None)
    assert got["spec"] == "whole"


def test_rows_the_harness_never_ran_are_not_a_gap_in_the_metric(conn):
    """RULE #974: four environment_error rows with no metrics leave env's accuracy covering all it was asked."""
    rid = record(conn, "decide", decide("env", 0, [8] * 24) + [("env", f"env{i}", False, {}) for i in range(4)], at=NOW - 2)
    conn.execute("UPDATE results SET failure_class = ? WHERE run_id = ? AND case_id LIKE 'env%'",
                 (reasons.ENVIRONMENT_ERROR, rid))
    conn.commit()
    record(conn, "decide", decide("plain", 0, [7] * 28), at=NOW - 1)
    got, _ = sweeps.model(conn, {"lane": "decide", **SERVED}, None)
    assert got["spec"] == "env"


def test_a_model_without_the_lane_metric_ranks_after_one_with_it(conn):
    """bare's pass-rate bound (23 of 24) is above fields' accuracy bound, but the two are not on one scale."""
    record(conn, "decide", [("bare", f"c{i}", i < 23, {}) for i in range(24)], at=NOW - 2)
    record(conn, "decide", decide("fields", 2, [7] * 22), at=NOW - 1)
    got, _ = sweeps.model(conn, {"lane": "decide", **SERVED}, None)
    assert got["spec"] == "fields"
