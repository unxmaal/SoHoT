"""#1267: a lane's saturated tag reads its ranked metric pooled over holdout, not exact-case passes."""
from harness import adopt, holdout, report, winners
from harness import memory_store as ms
from harness.checks import claims as claims_check

HELD = tuple(f"h-{i:02d}" for i in range(20))
SPLIT = holdout.Split("any", dev=("d-00", "d-01", "d-02"), holdout=HELD, too_small=False)


def row(cid, passed, **metrics):
    return {"case_id": cid, "candidate": "local-large", "passed": passed, "seconds": 1.0, "peak_kb": 0,
            "detail": "", "metrics": metrics}


def state(store_run, monkeypatch, lane, rows):
    monkeypatch.setattr(winners, "typed", lambda: {lane: "local-large"})
    monkeypatch.setattr(adopt, "current", lambda conn, machine=None: {})
    monkeypatch.setattr(holdout, "for_lane", lambda name, root=None: SPLIT)
    # Dev rows at the ceiling, so a reader that counted them would read saturation that holdout does not show.
    store_run(f"20261025-000001-{lane}", lane, rows=rows + [row(c, False) for c in SPLIT.dev])
    conn = ms.connect()
    try:
        return {s["lane"]: s for s in report.lanes_state(conn)}[lane]
    finally:
        conn.close()


def decide(cid, correct, fields=100):
    return row(cid, correct == fields, decide_accuracy=correct / fields, decide_correct=correct,
               decide_fields=fields)


def stt(cid, errors, words):
    return row(cid, errors == 0, wer=errors / words, wer_errors=errors, wer_words=words)


def claims(cid, passed, expect_empty):
    return row(cid, passed, **{claims_check.STRATUM: int(expect_empty)})


def test_decide_saturation_reads_field_accuracy(store_run, monkeypatch):
    got = state(store_run, monkeypatch, "decide", [decide(c, 97) for c in HELD])
    assert got["saturated"] is True
    assert got["holdout_pass_rate"] == 0.0
    assert (got["holdout_metric"], got["holdout_score"]) == ("decide_accuracy", 0.97)


def test_a_decide_incumbent_short_of_the_ceiling_is_not_saturated(store_run, monkeypatch):
    got = state(store_run, monkeypatch, "decide", [decide(c, 100 if i % 2 else 80) for i, c in enumerate(HELD)])
    assert got["saturated"] is False
    assert got["holdout_score"] == 0.9


def test_a_claims_model_that_passes_by_silence_is_not_saturated(store_run, monkeypatch):
    rows = [claims(c, True, True) for c in HELD[:19]] + [claims(HELD[19], False, False)]
    got = state(store_run, monkeypatch, "claims", rows)
    assert got["saturated"] is False
    assert got["holdout_pass_rate"] == 0.95
    assert got["holdout_metric"] == "claims_balanced" and got["holdout_score"] < holdout.SATURATED


def test_a_claims_model_right_on_both_strata_is_saturated(store_run, monkeypatch):
    rows = [claims(c, True, i % 4 != 0) for i, c in enumerate(HELD)]
    got = state(store_run, monkeypatch, "claims", rows)
    assert got["saturated"] is True
    assert got["holdout_score"] == 1.0


def test_stt_saturation_reads_pooled_wer(store_run, monkeypatch):
    got = state(store_run, monkeypatch, "stt", [stt(c, 2, 100) for c in HELD])
    assert got["saturated"] is True
    assert got["holdout_pass_rate"] == 0.0
    assert (got["holdout_metric"], got["holdout_score"]) == ("wer", 0.02)


def test_an_stt_model_with_one_garbled_clip_is_not_saturated(store_run, monkeypatch):
    rows = [stt(c, 0, 10) for c in HELD[:19]] + [stt(HELD[19], 100, 100)]
    got = state(store_run, monkeypatch, "stt", rows)
    assert got["saturated"] is False
    assert got["holdout_pass_rate"] == 0.95
    assert got["holdout_score"] == round(100 / 290, 3)


def test_a_lane_metric_missing_from_holdout_rows_is_not_read_as_pass_rate(store_run, monkeypatch):
    got = state(store_run, monkeypatch, "decide", [row(c, True) for c in HELD])
    assert got["saturated"] is False
    assert got["holdout_pass_rate"] == 1.0
    assert got["holdout_score"] is None


def test_a_lane_metric_covering_part_of_the_holdout_is_not_saturated(store_run, monkeypatch):
    got = state(store_run, monkeypatch, "decide", [decide(c, 100) for c in HELD[:10]] + [row(c, False) for c in HELD[10:]])
    assert got["saturated"] is False
    assert got["holdout_score"] is None


def test_a_pass_rate_lane_still_saturates_on_passes(store_run, monkeypatch):
    got = state(store_run, monkeypatch, "svg", [row(c, i != 0) for i, c in enumerate(HELD)])
    assert got["saturated"] is True
    assert (got["holdout_metric"], got["holdout_score"]) == ("pass_rate", 0.95)


def test_a_lower_is_better_metric_saturates_at_or_below_one_less_the_threshold():
    edge = round(1 - holdout.SATURATED, 3)
    assert holdout.saturated(edge, "wer") and not holdout.saturated(edge + 0.001, "wer")
    assert holdout.saturated(holdout.SATURATED, "decide_accuracy") and not holdout.saturated(0.94, "decide_accuracy")
    assert not holdout.saturated(None, "wer")


def test_the_report_names_the_metric_a_lane_saturated_on(store_run, monkeypatch):
    got = state(store_run, monkeypatch, "decide", [decide(c, 97) for c in HELD])
    assert report.saturation_text(got) == "decide_accuracy 0.970"
    assert "saturated: decide_accuracy 0.970" in report._lane_rows([{**got, "age_days": 0.1}], {})


def test_a_stored_report_from_before_the_metric_names_its_pass_rate():
    assert report.saturation_text({"holdout_pass_rate": 1.0}) == "pass_rate 1.000"
