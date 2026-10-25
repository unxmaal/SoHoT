"""A model's sweep evidence is its newest run with at least FALLBACK_MIN_CASES cases, so a newer smoke run cannot stand for it. #1239."""
from harness import knobs, reverify, runs, sweeps
from tests.test_lane_not_binding_1177 import _cases, record_pair, serve  # noqa: F401
from tests.test_reply_budget_binding_1020 import DAY_AT, LOW_SAMPLING, conn, record  # noqa: F401


def run(conn, spec, outcomes, at):
    return record(conn, spec, outcomes, top=32768, sampling=LOW_SAMPLING, at=at)


def model(conn):
    return sweeps.model(conn, reverify.served(conn)["repo"], runs.here(conn))


def test_a_served_model_with_a_working_108_case_run_and_a_newer_one_case_unpassed_run_is_swept_itself(conn, serve):
    """Live runs 571 (Ornith 12 of 108), 583 (Qwen3.6 8 of 24) and 585 (Ornith 0 of 1, by hand)."""
    serve("ornith")
    run(conn, "ornith", _cases(12, 108), DAY_AT - 9000)
    run(conn, "qwen36", _cases(8, 24, "q"), DAY_AT - 5000)
    run(conn, "ornith", {"smoke": "wrong"}, DAY_AT - 1000)
    swept, why = model(conn)
    assert swept["spec"] == "ornith" and why == ""


def test_a_served_model_whose_only_runs_are_small_is_read_from_its_newest_run(conn, serve):
    serve("ornith")
    run(conn, "ornith", _cases(3, 6), DAY_AT - 9000)
    rid = run(conn, "ornith", _cases(0, 2, "s"), DAY_AT - 1000)
    run(conn, "qwen36", _cases(8, 24, "q"), DAY_AT - 5000)
    swept, why = model(conn)
    assert swept["spec"] == "qwen36" and why.startswith(f"ornith passed 0 of 2 in run {rid}")


def test_a_newer_large_run_still_replaces_an_older_large_one(conn, serve):
    serve("ornith")
    run(conn, "ornith", _cases(12, 108), DAY_AT - 9000)
    rid = run(conn, "ornith", _cases(0, 24, "n"), DAY_AT - 5000)
    run(conn, "ornith", {"smoke": "pass"}, DAY_AT - 1000)
    assert next(iter(sweeps.passing(conn, "repo", runs.here(conn)).values()))["run_id"] == rid
    swept, why = model(conn)
    assert swept is None and why.startswith(f"ornith passed 0 of 24 in run {rid}")


def test_a_sweep_is_projected_from_the_large_run_not_the_newer_smoke_run(conn, serve):
    serve("ornith")
    run(conn, "ornith", _cases(12, 108), DAY_AT - 9000)
    run(conn, "ornith", {"smoke": "pass"}, DAY_AT - 1000)
    item = reverify.served(conn)["repo"]
    assert sweeps.projected(conn, item, knobs.KNOBS["reply_budget"], [32768], runs.here(conn)) == 108.0


def test_a_one_case_paired_loss_does_not_mark_a_model_below_its_incumbent_when_a_larger_paired_run_shows_no_loss(conn, serve):
    serve("ornith", incumbent="qwen4b")
    record_pair(conn, {"ornith": _cases(10, 24), "qwen4b": _cases(5, 24)}, DAY_AT - 6000)
    record_pair(conn, {"ornith": {"s0": "wrong", **_cases(10, 24)}, "qwen4b": {"s0": "pass"}}, DAY_AT - 1000)
    swept, why = model(conn)
    assert swept["spec"] == "ornith" and why == ""
