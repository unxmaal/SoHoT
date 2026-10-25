"""reverify judges a lane on the metric the lane ranks and adopts on, never on exact-case pass bits alone. #733."""
import pytest

from harness import adopt, paired, reverify, runs, workqueue as wq
from harness import memory_store as ms
from harness.checks import claims as claims_check

DAY = 86400.0
NOW = 1_800_000_000.0
VERSIONS = {"mlx": "0.30.0", "mlx-lm": "0.28.0", "mflux": "0.11.0",
            "litellm": "1.77.0", "llama.cpp": "6500"}
M2 = {"fingerprint": "Mac14,12/macOS/arm64", "hw_model": "Mac14,12",
      "os": "macOS-27.0.1-arm64-arm-64bit", "arch": "arm64", "memory_gb": 32.0,
      "accelerator": "unified 32GB", "runtimes": "cpu,mlx", "ceiling_gb": 22.0,
      "versions": dict(VERSIONS)}
UPGRADED = {**VERSIONS, "mlx-lm": "0.29.1", "llama.cpp": "6600"}
#: The decide lane's typed default, which enforces the reply schema.
SERVED = "imajev-4b-Q8_0"


@pytest.fixture
def on(monkeypatch):
    def be(**changes):
        facts = {**M2, **changes}
        monkeypatch.setattr(ms, "this_machine", lambda: dict(facts))
    be()
    return be


@pytest.fixture
def conn(tmp_path, on):
    c = ms.connect(tmp_path / "d.db")
    yield c
    c.close()


_SEQ = iter(range(1, 10_000))


def record(conn, lane, rows, *, at, versions=None, job_id=None):
    """rows: [(candidate, case, passed, metrics), ...]."""
    env = {"hw_model": "Mac14,12", "os": "macOS-27.0.1-arm64-arm-64bit", "arch": "arm64",
           "macos": "27.0.1", "versions": dict(VERSIONS if versions is None else versions)}
    stored = [{"candidate": c, "case_id": case, "passed": ok, "seconds": 1.0,
               "failure_class": "" if ok else "content_failed", "metrics": m}
              for c, case, ok, m in rows]
    rid = runs.record(conn, f"runs/m{next(_SEQ)}-{lane}",
                      {"receipt": {"modality": lane}, "environment": env,
                       "specs": {c: c for c, *_ in rows}, "rows": stored}, at=at)
    if job_id is not None:
        conn.execute("UPDATE runs SET job_id = ? WHERE id = ?", (int(job_id), rid))
        conn.commit()
    return rid


def fields(acc: float, n: int = 5) -> dict:
    right = round(acc * n)
    return {"decide_accuracy": right / n, "decide_correct": right, "decide_fields": n}


def decide_rows(spec, accs):
    return [(spec, f"c{i}", a >= 1.0, fields(a)) for i, a in enumerate(accs)]


def finish(conn, rows, lane="decide"):
    reverify.check(conn, now=NOW, lane=lane)
    job = [j for j in wq.jobs(conn=conn) if j["requested_by"] == reverify.REQUESTED_BY][-1]
    wq._write({**job, "state": wq.DONE, "rc": 0}, conn=conn)
    record(conn, lane, rows, at=NOW + 60, job_id=job["id"], versions=UPGRADED)
    reverify.check(conn, now=NOW + 120, lane=lane)
    return dict(conn.execute("SELECT * FROM reverifications WHERE job_id = ?", (job["id"],)).fetchone())


def test_a_decide_run_with_no_exact_case_but_right_fields_is_a_baseline_and_a_pass(conn, on):
    base = record(conn, "decide", decide_rows(SERVED, [0.8] * 10), at=NOW - DAY)
    on(versions=UPGRADED)
    row = finish(conn, decide_rows(SERVED, [0.8] * 10))
    assert row["baseline_run_id"] == base
    assert row["outcome"] == reverify.PASSED, row["detail"]
    assert "decide_accuracy 0.800" in row["detail"]


def test_a_decide_rerun_that_holds_its_exact_count_but_loses_field_accuracy_regresses(conn, on):
    record(conn, "decide", decide_rows(SERVED, [1.0] * 3 + [0.8] * 7), at=NOW - DAY)
    on(versions=UPGRADED)
    row = finish(conn, decide_rows(SERVED, [1.0] * 3 + [0.4] * 7))
    assert row["outcome"] == reverify.REGRESSED, row["detail"]
    assert "7 lost against 0 gained" in row["detail"] and "decide_accuracy" in row["detail"]
    assert (row["reason"], row["failure_class"]) == ("candidate", "content_failed")


def test_losing_exact_cases_while_gaining_more_accuracy_elsewhere_is_not_a_regression(conn, on):
    """Pass bits say 8 lost, 0 gained; per case on decide_accuracy it is 8 against 8, and the pooled accuracy rose."""
    record(conn, "decide", decide_rows(SERVED, [1.0] * 8 + [0.2] * 8), at=NOW - DAY)
    on(versions=UPGRADED)
    row = finish(conn, decide_rows(SERVED, [0.8] * 8 + [0.6] * 8))
    assert row["outcome"] == reverify.PASSED, row["detail"]


def test_a_decide_rerun_that_gets_every_field_wrong_still_fails(conn, on):
    record(conn, "decide", decide_rows(SERVED, [0.8] * 10), at=NOW - DAY)
    on(versions=UPGRADED)
    row = finish(conn, decide_rows(SERVED, [0.0] * 10))
    assert row["outcome"] == reverify.FAILED


def test_an_incumbent_better_on_decide_accuracy_at_equal_exact_counts_is_flagged(conn):
    adopt.record(conn, adopt.Verdict("decide", "q3-8b", SERVED, True, "won"))
    accs_served = [1.0, 1.0] + [0.4] * 8
    accs_inc = [1.0, 1.0] + [0.8] * 8
    row = finish(conn, decide_rows(SERVED, accs_served) + decide_rows("q3-8b", accs_inc))
    assert row["outcome"] == reverify.REGRESSED, row["detail"]
    assert "q3-8b" in row["detail"]


def _judge(conn, lane, spec, before, after):
    base = record(conn, lane, before, at=NOW - DAY)
    job = wq.add(["true"], title="reverify", requested_by=reverify.REQUESTED_BY, conn=conn)
    rid = record(conn, lane, after, at=NOW, job_id=job["id"])
    cid = conn.execute("SELECT candidate_id FROM results WHERE run_id = ? LIMIT 1", (rid,)).fetchone()[0]
    rv = {"lane": lane, "spec": spec, "candidate_id": cid, "incumbent": None,
          "baseline_run_id": base}
    return reverify.judge(conn, rv, {**job, "state": wq.DONE, "rc": 0})


def stt_rows(spec, wers, max_wer=0.2):
    return [(spec, f"clip{i}", w <= max_wer, {"wer": w, "wer_errors": round(w * 20), "wer_words": 20})
            for i, w in enumerate(wers)]


def test_an_stt_rerun_whose_wer_doubles_at_an_equal_pass_count_regresses(conn):
    got = _judge(conn, "stt", "stt:x", stt_rows("stt:x", [0.05] * 10), stt_rows("stt:x", [0.10] * 10))
    assert got[0] == reverify.REGRESSED, got[3]
    assert "wer" in got[3]


def test_an_stt_rerun_with_no_word_perfect_clip_but_a_plausible_wer_is_not_failed(conn):
    before = stt_rows("stt:x", [0.05] * 10, max_wer=0.0)
    got = _judge(conn, "stt", "stt:x", before, stt_rows("stt:x", [0.05] * 10, max_wer=0.0))
    assert got[0] == reverify.PASSED, got[3]


def claims_rows(spec, recall_ok, empty_ok):
    """recall_ok, empty_ok: pass bits for the expect-claims and expect-empty strata."""
    out = [(spec, f"r{i}", ok, {claims_check.STRATUM: 0}) for i, ok in enumerate(recall_ok)]
    return out + [(spec, f"e{i}", ok, {claims_check.STRATUM: 1}) for i, ok in enumerate(empty_ok)]


def test_a_claims_rerun_pairs_per_stratum_at_the_lane_weights(conn):
    """10 recall cases lost, 10 of 50 expect-empty gained: 10 against 10 on pass bits, a regression at the lane's stratum weights."""
    before = claims_rows("c7b", [True] * 10, [True] * 40 + [False] * 10)
    after = claims_rows("c7b", [False] * 10, [True] * 50)
    got = _judge(conn, "claims", "c7b", before, after)
    assert got[0] == reverify.REGRESSED, got[3]


def test_the_stratum_weighting_rounds_against_the_regression_claim(conn):
    """8 recall lost; 7 of 40 expect-empty gained scale to 1.4: rounded up to 2 it is p 0.11, down to 1 it would be p 0.04."""
    before = claims_rows("c7b", [True] * 8, [True] * 33 + [False] * 7)
    after = claims_rows("c7b", [False] * 8, [True] * 40)
    got = _judge(conn, "claims", "c7b", before, after)
    assert got[0] == reverify.PASSED, got[3]


def test_the_stored_verdict_shape_is_unchanged_for_a_pass_bit_lane(conn):
    rows = [("q3-4b", f"c{i}", True, {}) for i in range(10)]
    got = _judge(conn, "code", "q3-4b", rows, rows)
    assert got[0] == reverify.PASSED and got[3] == "q3-4b passed 10 of 10"


# ---- paired.pair on a metric ---------------------------------------------------

def _rows(cand, cases, value, metric="decide_accuracy", repeat=1):
    return [{"candidate": cand, "case_id": c if repeat == 1 else f"{c}#{r}", "passed": False,
             "failure_class": "content_failed", "metrics": {metric: v}}
            for c, v in zip(cases, value) for r in range(1, repeat + 1)]


def test_pair_on_a_metric_sees_a_drop_the_pass_bits_cannot():
    cases = [f"c{i}" for i in range(8)]
    before, after = _rows("m", cases, [0.8] * 8), _rows("m", cases, [0.4] * 8)
    assert paired.pair(before, after).discordant == 0
    got = paired.pair(before, after, metric="decide_accuracy")
    assert (got.lost, got.gained) == (8, 0) and got.p < 0.05


def test_pair_on_a_lower_is_better_metric_counts_a_rise_as_lost():
    cases = [f"c{i}" for i in range(4)]
    got = paired.pair(_rows("m", cases, [0.1] * 4, "wer"), _rows("m", cases, [0.2] * 4, "wer"), metric="wer")
    assert (got.lost, got.gained) == (4, 0)


def test_pair_on_a_metric_keeps_its_refusals():
    before = _rows("m", ["a", "b"], [0.8, 0.8])
    assert paired.pair(before, _rows("m", ["a", "c"], [0.8, 0.8]), metric="decide_accuracy").refused
    got = paired.pair(_rows("m", ["a", "b"], [0.8, 0.8], repeat=3), _rows("m", ["a", "b"], [0.4, 0.4]),
                      same_repeat=True, metric="decide_accuracy")
    assert "repeat differs" in got.refused


def test_identical_repeats_of_a_metric_shrink_like_identical_pass_bits():
    """3 cases x 3 repeats, each case the same value every draw: 9 lost draws are 3 cases, p 0.25 not 0.004."""
    cases = ["a", "b", "c"]
    got = paired.pair(_rows("m", cases, [0.8, 0.6, 1.0], repeat=3), _rows("m", cases, [0.4, 0.2, 0.6], repeat=3),
                      same_repeat=True, metric="decide_accuracy")
    assert got.lost == 9 and got.deff == pytest.approx(3.0)
    assert got.p == pytest.approx(0.25)


def test_a_missing_metric_ranks_last_and_stays_out_of_the_design_effect():
    """Draws vary within each case and not between cases, so rho is 0; a -inf in the ANOVA would read as rho 1."""
    def rows():
        return [{"candidate": "m", "case_id": f"{c}#{r}", "passed": False, "failure_class": "content_failed",
                 "metrics": {"decide_accuracy": v}} for c in "abcd" for r, v in ((1, 0.8), (2, 0.6))]
    before, after = rows(), rows()
    after[0]["metrics"] = {}
    got = paired.pair(before, after, same_repeat=True, metric="decide_accuracy")
    assert (got.lost, got.gained) == (1, 0)
    assert got.deff < 1.2
