"""#701: rank keys and thresholds that measured the instrument rather than the model."""
from pathlib import Path

import pytest

from evals import core
from harness import adopt, judge, usage, winners
from harness.checks import decide, speech

pytestmark = pytest.mark.usefixtures("sat_exam")

SCHEMA = {f"q{i}": {"type": "boolean", "description": f"question {i}"} for i in range(5)}
GOLD = {f"q{i}": True for i in range(5)}


def _receipts(monkeypatch, lane, summary):
    from harness import runs
    run = {"lane": lane, "path": "p", "id": 1}
    monkeypatch.setattr(runs, "summaries", lambda conn, tier=None: [(run, dict(summary), [])])
    return winners.from_receipts(None, plain_only=False)[lane]["candidate"]


# ---- decide ranks on pooled accuracy, not acc^5 ---------------------------------

DECIDE = {"sharper": {"pass_rate": 0.40, "median_s": 1.0, "metrics": {"decide_accuracy": 0.85}},
          "luckier": {"pass_rate": 0.45, "median_s": 1.0, "metrics": {"decide_accuracy": 0.84}}}


def test_decide_ranks_on_pooled_accuracy_not_exact_case_pass_rate(monkeypatch):
    assert _receipts(monkeypatch, "decide", DECIDE) == "sharper"


def test_accuracy_over_the_half_that_did_not_crash_does_not_win(monkeypatch):
    rows = {"crashy": {"pass_rate": 0.45, "median_s": 1.0, "total": 20,
                       "metrics": {"decide_accuracy": 0.95}, "metric_n": {"decide_accuracy": 10}},
            "steady": {"pass_rate": 0.40, "median_s": 1.0, "total": 20,
                       "metrics": {"decide_accuracy": 0.85}, "metric_n": {"decide_accuracy": 20}}}
    assert _receipts(monkeypatch, "decide", rows) == "steady"


def test_the_decide_adopt_gate_reads_accuracy():
    assert adopt.better(DECIDE["luckier"], DECIDE["sharper"], lane="decide")
    assert not adopt.better(DECIDE["sharper"], DECIDE["luckier"], lane="decide")


def test_a_decide_screen_with_correct_fields_and_no_exact_case_is_screened():
    from harness import screen
    summary = {"m": {"total": 1, "passed": 0, "pass_rate": 0.0,
                     "metrics": {"decide_accuracy": 0.8}}}
    assert screen.outcome(0, summary).outcome == "screened"


# ---- one-hot rows carry no calibration and are never ranked on it ------------------

def test_a_one_hot_decide_row_reports_no_brier_or_decisions():
    got = decide.check({f"q{i}": "A" for i in range(5)}, SCHEMA, GOLD).metrics
    assert got["calibrated"] == 0.0
    assert "decide_brier" not in got and "decide_brier_sum" not in got
    assert "decisions" not in got


def test_a_one_hot_candidate_summary_has_no_brier_or_ece():
    rows = [core.Result(f"c{i}", "m", True, 1.0, 0, "",
                        metrics={**decide.check({f"q{j}": "B" for j in range(5)}, SCHEMA, GOLD).metrics,
                                 "decide_brier": 0.0, "decide_brier_sum": 0.0,
                                 "decisions": [[1.0, 1]] * 5})
            for i in range(30)]
    got = core.summarize(rows)["m"]["metrics"]
    assert "decide_brier" not in got and "decide_ece" not in got
    assert got["decide_accuracy"] == 1.0


def test_a_one_hot_row_is_not_ranked_against_a_calibrated_row_on_brier(monkeypatch):
    rows = {"a-onehot": {"pass_rate": 0.5, "median_s": 1.0,
                         "metrics": {"decide_accuracy": 0.8, "decide_brier": 0.4, "calibrated": 0.0}},
            "b-calibrated": {"pass_rate": 0.5, "median_s": 1.0,
                             "metrics": {"decide_accuracy": 0.8, "decide_brier": 0.3, "calibrated": 1.0}}}
    assert "decide_brier" not in winners.shared_metrics(rows.values(), lane="decide")
    assert _receipts(monkeypatch, "decide", rows) == "a-onehot"


# ---- stt: orthography is not an error; the lane ranks on corpus WER ------------------

def test_mr_and_mister_are_one_word_to_the_normaliser():
    assert speech.wer("MISTER SMITH CAME TO DOCTOR JONES", "Mr. Smith came to Dr Jones") == 0.0
    assert speech.wer("MISSUS GRAY", "Mrs Gray") == 0.0


def test_an_stt_case_passes_a_mr_transcript_of_a_mister_reference():
    case = core.Case(id="mr", modality="stt", prompt="Mister Smith came",
                     assertions={"max_wer": 0.0}, source=Path("mr.yaml"))
    assert core.score(case, "Mr Smith came").passed


def test_stt_ranks_on_corpus_wer_before_pass_rate(monkeypatch):
    rows = {"exact-orthography": {"pass_rate": 0.95, "median_s": 1.0, "metrics": {"wer": 0.030}},
            "fewer-errors": {"pass_rate": 0.90, "median_s": 1.0, "metrics": {"wer": 0.020}}}
    assert _receipts(monkeypatch, "stt", rows) == "fewer-errors"


# ---- ocr: no silent lenient default ------------------------------------------------

def test_an_image_case_with_a_text_assertion_and_no_max_cer_is_refused(tmp_path):
    (tmp_path / "sign.yaml").write_text(
        "id: sign\nmodality: image\nprompt: a sign reading OPEN\nassert:\n  text: OPEN\n",
        encoding="utf-8")
    with pytest.raises(ValueError, match="max_cer"):
        core.load_cases(tmp_path)


def test_the_ocr_checker_has_no_default_threshold():
    from harness.checks import ocr
    assert not hasattr(ocr, "DEFAULT_MAX_CER")


def test_every_committed_text_case_names_its_max_cer():
    for lane in ("image", "ocr"):
        for case in core.load_cases(Path(core.__file__).parent / "cases" / lane):
            if case.assertions.get("text"):
                assert "max_cer" in case.assertions, case.id


# ---- the judge control is labelled by quality, not by an old machine's ceiling ---------

def test_no_control_model_is_known_bad_for_its_size():
    for shape in ("bare", "carded"):
        lost = {item[0] for item in judge.SHAPES[shape] if item[-1] == "lost"}
        assert "mlx-community/Qwen3-30B-A3B-Instruct-2507-4bit" not in lost, shape
    assert [i[0] for i in judge.CONTROL_BARE] == [i[0] for i in judge.CONTROL_CARDED]


# ---- usage: one client's retry burst is one piece of evidence ------------------------

NOW = 1_800_000_000.0
DAY = 86400.0


def _req(at, client, err=""):
    return {"at": at, "alias": "sohot-code", "lane": "code", "served": "s", "spec": "x",
            "client": client, "call_type": "acompletion", "stream": 0, "prompt_tokens": 1,
            "completion_tokens": 1, "ttft_s": None, "total_s": 1.0, "tool_calls": 0,
            "tool_calls_valid": 0, "finish_reason": "", "error_class": err, "error_code": ""}


@pytest.fixture
def conn():
    from harness import memory_store as ms
    c = ms.connect()
    yield c
    c.close()


def _switch(conn, at):
    conn.execute("INSERT INTO gateway_switches (lane, old_spec, new_spec, how, requested_at, "
                 "switched_at, in_flight) VALUES ('code', 'old', 'new', 'idle', ?, ?, 0)",
                 (at - 60, at))
    conn.commit()


def _spread(at, n, sign, bad=0, err="APIError"):
    return [_req(at + sign * (100 + i * 600), f"client-{i % 7}", err if i < bad else "")
            for i in range(n)]


def test_one_client_retrying_thirty_failures_after_a_switch_is_not_a_regression(conn):
    at = NOW - DAY
    _switch(conn, at)
    rows = _spread(at, 100, -1, bad=2) + _spread(at, 70, 1)
    rows += [_req(at + 50 + i, "agent-loop", "APIError") for i in range(30)]
    usage.insert(conn, [(r, None) for r in rows])
    assert usage.regressions(usage.around_switches(conn, since=7 * DAY, now=NOW)) == []


def test_errors_spread_over_many_sessions_are_still_a_regression(conn):
    at = NOW - DAY
    _switch(conn, at)
    rows = _spread(at, 100, -1, bad=2) + _spread(at, 100, 1, bad=30)
    usage.insert(conn, [(r, None) for r in rows])
    [w] = usage.regressions(usage.around_switches(conn, since=7 * DAY, now=NOW))
    assert "error rate" in w


def test_gateway_error_classes_are_not_the_models_regression(conn):
    at = NOW - DAY
    _switch(conn, at)
    rows = _spread(at, 100, -1, bad=2) + _spread(at, 100, 1, bad=30, err="RateLimitError")
    usage.insert(conn, [(r, None) for r in rows])
    assert usage.regressions(usage.around_switches(conn, since=7 * DAY, now=NOW)) == []


def test_one_steady_client_whose_errors_rise_after_a_switch_is_a_regression(conn):
    at = NOW - DAY
    _switch(conn, at)
    rows = [_req(at - 2000 + i * 10, "only-client") for i in range(100)]
    rows += [_req(at + 100 + i * 10, "only-client", "APIError" if i % 2 else "") for i in range(100)]
    usage.insert(conn, [(r, None) for r in rows])
    [w] = usage.regressions(usage.around_switches(conn, since=7 * DAY, now=NOW))
    assert "error rate" in w


def test_gateway_error_classes_are_not_in_the_shown_error_rate():
    rows = [_req(NOW + i, "c", "RateLimitError" if i < 5 else "") for i in range(10)]
    rows.append(_req(NOW + 20, "c", "APIError"))
    got = usage.stats(rows)
    assert got["errors"] == 1 and got["error_rate"] == pytest.approx(1 / 11)
    assert got["gateway_errors"] == 5


def test_the_live_audit_does_not_call_a_rate_limit_burst_the_models_failure(monkeypatch):
    from harness import live_audit
    rows = [_req(NOW + i, "c", "RateLimitError" if i < 10 else "") for i in range(30)]
    monkeypatch.setattr(usage, "real_use", lambda conn: {"code": usage.stats(rows)})
    monkeypatch.setattr(usage, "drop_warning", lambda conn, start: [])
    [got] = live_audit._gateway_errors(None)
    assert "gateway" in got and "requests failed" not in got


# ---- the decide paired gate reads per-case accuracy, not exact-case bits ---------------

def _decide_rows(name, acc, n=20):
    return [{"candidate": name, "case_id": f"c{i}", "passed": acc[i] == 1.0,
             "metrics": {"decide_accuracy": acc[i], "decide_correct": acc[i] * 5,
                         "decide_fields": 5}} for i in range(n)]


def test_a_decide_challenger_right_on_more_fields_in_every_case_is_adopted():
    rows = _decide_rows("inc", [0.6] * 20) + _decide_rows("chal", [0.8] * 20)
    inc = {"candidate": "inc", "pass_rate": 0.0, "metrics": {"decide_accuracy": 0.6}}
    chal = {"candidate": "chal", "pass_rate": 0.0, "metrics": {"decide_accuracy": 0.8}}
    got = adopt.decide("decide", inc, chal, rows)
    assert got.adopt, got.why


def test_fewer_exact_cases_is_not_significantly_worse_when_field_accuracy_is_higher():
    rows = _decide_rows("inc", [1.0] * 8 + [0.2] * 12) + _decide_rows("chal", [0.8] * 20)
    assert adopt._worse(rows, "inc", "chal", "decide") == ""
    cell, _, _ = adopt.paired_p(rows, "inc", "chal", "decide")
    assert (cell.gained, cell.lost) == (12, 8)


def test_no_control_label_rests_on_the_stt_lane_701_found_biased():
    for shape in ("bare", "carded"):
        assert "mlx-community/whisper-large-v3-mlx" not in {i[0] for i in judge.SHAPES[shape]}, shape


def test_the_text_render_case_does_not_call_its_max_cer_measured():
    text = (Path(core.__file__).parent / "cases" / "image" / "text-render.yaml").read_text(encoding="utf-8")
    assert "unmeasured" in text and "#730" in text


# ---- #726 rounding and alpha meet #701's lane metric ----------------------------

def test_decide_worse_pairs_on_accuracy_and_still_rounds_against_the_worse_claim(monkeypatch):
    from harness import power
    monkeypatch.setattr(power, "rows_icc", lambda rows, names: (0.5, 2.0))
    rows = _decide_rows("inc", [0.8] * 10, n=10) + _decide_rows("chal", [0.6] * 9 + [1.0], n=10)
    bits = adopt.paired_p(rows, "inc", "chal")[0]
    assert (bits.lost, bits.gained) == (0, 1)
    cell, p_worse, _ = adopt.paired_p(rows, "inc", "chal", "decide", against="incumbent")
    _, p_gain, _ = adopt.paired_p(rows, "inc", "chal", "decide")
    assert (cell.lost, cell.gained) == (9, 1)
    assert p_worse > p_gain
    assert adopt._worse(rows, "inc", "chal", "decide") == ""


def test_decide_worse_on_accuracy_answers_to_the_alpha_it_is_given():
    rows = _decide_rows("inc", [0.8] * 20) + _decide_rows("chal", [0.6] * 20)
    assert "significantly worse" in adopt._worse(rows, "inc", "chal", "decide")
    assert adopt._worse(rows, "inc", "chal", "decide", alpha=1e-9) == ""
    assert adopt._worse(rows, "inc", "chal") == ""


def test_the_live_audit_says_a_window_dropped_rows_beside_model_and_gateway_errors_apart(monkeypatch):
    from harness import live_audit
    rows = [_req(NOW + i, "c", "RateLimitError" if i < 10 else "APIError" if i < 20 else "") for i in range(30)]
    monkeypatch.setattr(usage, "real_use", lambda conn: {"code": usage.stats(rows)})
    monkeypatch.setattr(usage, "drop_warning", lambda conn, start: ["7 gateway usage row(s) were dropped"])
    drop, model, gateway = live_audit._gateway_errors(None)
    assert "dropped" in drop
    assert "failed in the model" in model and "gateway" not in model
    assert "gateway or client refused" in gateway


def test_a_wer_lane_counts_its_repeats_correlation_on_the_wer_it_pairs_on():
    """#1007: repeats whose pass bits alternate but whose WER never moves are one case each, not two."""
    rows = []
    for i in range(8):
        for k in (1, 2):
            rows.append({"candidate": "inc", "case_id": f"c{i}#{k}", "passed": k == 1, "seconds": 1.0,
                         "metrics": {"wer": 0.1 if i % 2 else 0.0}})
            rows.append({"candidate": "ch", "case_id": f"c{i}#{k}", "passed": k == 2, "seconds": 1.0,
                         "metrics": {"wer": 0.0}})
    cell, p, note = adopt.paired_p(rows, "inc", "ch", "stt")
    assert (cell.gained, cell.lost, p) == (8, 0, 0.125)
    assert note == "4 gained against 0 lost once correlated repeats are counted as cases (rho 1.00, repeat 2.0)"
