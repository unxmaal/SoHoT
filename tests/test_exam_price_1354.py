"""A challenger with its own runs of this exam here is priced from them before the decode ratio; the plan names its source. #1354."""
import pytest

from harness import completion, holdout, power, runs
from harness import memory_store as ms

LANE = "code"
EXAM = (frozenset({"e1", "e2", "e3", "e4"}), frozenset({"e1", "e2"}))
BUDGET = completion.budget(LANE)
SETTINGS = (BUDGET, ())


def _rows(spec, seconds, cases, tok_s, failure_class=None):
    return [{"case_id": c, "candidate": spec, "passed": True, "seconds": s, "peak_kb": 0, "detail": "",
             "failure_class": failure_class, "metrics": {"tokens_per_s": tok_s}}
            for c, s in zip(cases, seconds if isinstance(seconds, (list, tuple)) else [seconds] * len(cases))]


@pytest.fixture
def priced(store_run):
    """The incumbent decodes 3x faster than the challenger, so the decode ratio would price the challenger at 3 x 50 s."""
    store_run("inc-1", LANE, rows=_rows("inc", 50.0, ("e1", "e2", "e3", "e4"), 120.0), receipt={"max_tokens": BUDGET})

    def price(exam=EXAM, settings=SETTINGS):
        conn = ms.connect()
        try:
            return power.challenger_seconds(conn, LANE, "ch", incumbent="inc", incumbent_s=50.0,
                                            settings=settings, machines=runs.here(conn), exam=exam)
        finally:
            conn.close()
    return price


def test_own_rows_covering_the_exam_here_beat_the_decode_ratio(store_run, priced):
    store_run("ch-1", LANE, rows=_rows("ch", [80.0, 100.0, 120.0], ("e1", "e2", "e3"), 40.0),
              receipt={"max_tokens": BUDGET})
    s, source, basis = priced()
    assert source == "exam" and s == pytest.approx(100.0)
    assert "3 row(s)" in basis and f"{BUDGET}-token budget" in basis


def test_runs_that_miss_the_cover_set_leave_the_decode_ratio(store_run, priced):
    store_run("ch-1", LANE, rows=_rows("ch", 80.0, ("e1", "e3", "e4"), 40.0), receipt={"max_tokens": BUDGET})
    store_run("ch-2", LANE, rows=_rows("ch", 80.0, ("e2", "x9"), 40.0), tier="screen", receipt={"max_tokens": BUDGET})
    s, source, _ = priced()
    assert source == "decode ratio" and s == pytest.approx(50.0 * 120.0 / 40.0)


def test_rows_off_the_exam_count_toward_neither_cover_nor_mean(store_run, priced):
    store_run("ch-1", LANE, rows=_rows("ch", [60.0, 60.0, 900.0], ("e1", "e2", "dev-x"), 40.0),
              receipt={"max_tokens": BUDGET})
    assert priced()[:2] == (pytest.approx(60.0), "exam")


def test_a_larger_budget_bounds_the_run_and_a_smaller_one_does_not(store_run, priced):
    store_run("ch-small", LANE, rows=_rows("ch", 10.0, ("e1", "e2"), 40.0), receipt={"max_tokens": BUDGET // 2})
    assert priced()[1] == "decode ratio"
    store_run("ch-big", LANE, rows=_rows("ch", 70.0, ("e1", "e2"), 40.0), receipt={"max_tokens": BUDGET * 2})
    store_run("ch-bigger", LANE, rows=_rows("ch", 500.0, ("e1", "e2"), 40.0), receipt={"max_tokens": BUDGET * 4})
    s, source, basis = priced()
    assert (s, source) == (pytest.approx(70.0), "exam") and f"upper bound at {BUDGET}" in basis


def test_another_machines_runs_do_not_price_this_one(store_run, priced):
    store_run("ch-1", LANE, rows=_rows("ch", 80.0, ("e1", "e2"), 40.0), hw_model="OtherBox1,1",
              receipt={"max_tokens": BUDGET})
    assert priced()[1] == "floor"


def test_cases_that_never_ran_do_not_cover_the_exam(store_run, priced):
    from harness import reasons
    store_run("ch-1", LANE, rows=_rows("ch", 80.0, ("e1",), 40.0) + _rows("ch", 1.0, ("e2",), 40.0, reasons.NEVER_RAN[0]),
              receipt={"max_tokens": BUDGET})
    assert priced()[1] == "decode ratio"


def test_a_repair_harness_run_does_not_price_the_patch_exam(store_run, priced):
    store_run("ch-1", LANE, rows=_rows("ch", 80.0, ("e1", "e2"), 40.0), receipt={"max_tokens": BUDGET, "harness": "repair"})
    assert priced()[1] == "decode ratio"


def test_the_repo_exam_is_covered_by_its_screen_subset_and_other_lanes_by_the_holdout():
    from evals import repo_screen
    cases, need = power.exam_of("repo")
    assert need == {c.id for c in repo_screen.pick(holdout.lane_cases("repo"))} and need < cases
    split = holdout.for_lane(LANE)
    assert power.exam_of(LANE) == (frozenset(split.dev) | frozenset(split.holdout), frozenset(split.holdout))


def test_every_plan_prices_through_pair_cost_and_names_the_source(store_run, priced):
    store_run("ch-1", LANE, rows=_rows("ch", 90.0, ("e1", "e2"), 40.0), receipt={"max_tokens": BUDGET})
    conn = ms.connect()
    try:
        _, _, est = power.pair_cost(conn, LANE, incumbent="inc", incumbent_spec="", incumbent_s=50.0,
                                    challenger="ch", settings=SETTINGS, machines=runs.here(conn))
    finally:
        conn.close()
    assert est["challenger_source"] == "decode ratio"  # pair_cost's own exam is the shipped code holdout
    assert "by decode ratio: the incumbent's 50s" in power.challenger_note(est)
    note = power.challenger_note({"challenger_s": 90.0, "challenger_source": "exam", "challenger_basis": "b"})
    assert note == "challenger seconds per call 90s by exam: b"
    assert power.challenger_note({"challenger_s": 50.0, "challenger_source": "like incumbent"}) == ""
