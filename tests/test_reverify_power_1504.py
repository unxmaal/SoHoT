"""A re-run that passes on fewer shared cases than power.TARGET needs to see a loss is underpowered, never a plain pass. #1504."""
import pytest

from harness import adopt, power, reverify, runs
from tests.test_reverify import (DAY, NOW, VERSIONS, _latest, _queue_and_finish, check, conn, on,  # noqa: F401
                                 record_run)


def _all_pass(n):
    return [("q3-4b", f"c{i}", True) for i in range(n)]


def _minimum():
    """Shared cases a baseline passing every case needs, at repeat 1, to see a loss of the code lane's effect."""
    return power.cases_needed([0.0], power.effect_for("code"), rho=0.0, stochastic=False,
                              alpha=adopt.ALPHA, target=power.TARGET, cap=1)


def _rerun(conn, on, before, after):
    record_run(conn, "code", before, at=NOW - DAY)
    on(versions={**VERSIONS, "mlx-lm": "0.29.1"})
    _queue_and_finish(conn, after)
    check(conn, now=NOW + 120)
    return _latest(conn)


def test_the_minimum_comes_from_the_power_machinery_and_is_more_than_a_handful():
    assert 10 < _minimum() < power.MAX_CASES


def test_a_pass_on_a_shared_set_below_the_minimum_is_underpowered_and_names_the_count_and_minimum(conn, on):
    need = _minimum()
    row = _rerun(conn, on, _all_pass(5), _all_pass(20))
    assert row["outcome"] == reverify.UNDERPOWERED != reverify.PASSED
    assert "paired on the 5 cases both runs ran, 15 only one ran left out" in row["detail"]
    assert f"on 5 shared cases at repeat 1, needs {need}" in row["detail"]
    assert " passed 20 of 20; " in row["detail"]
    assert f"run {row['run_id']} is the next baseline" in row["detail"]


def test_an_underpowered_rerun_is_not_flagged_and_is_the_next_baseline(conn, on):
    row = _rerun(conn, on, _all_pass(5), _all_pass(20))
    assert row["outcome"] not in reverify.FLAGGED
    assert "code" not in reverify.flags(conn)
    cid = reverify.served(conn)["code"]["candidate_id"]
    assert reverify.baseline(conn, "code", cid, runs.here(conn))["id"] == row["run_id"]


@pytest.mark.parametrize("short, outcome", [(1, reverify.UNDERPOWERED), (0, reverify.PASSED)])
def test_the_verdict_turns_at_the_minimum(conn, on, short, outcome):
    n = _minimum() - short
    row = _rerun(conn, on, _all_pass(n), _all_pass(n))
    assert row["outcome"] == outcome, row["detail"]
    if outcome == reverify.PASSED:
        assert row["detail"].endswith(f" passed {n} of {n}")


def test_a_significant_regression_on_a_small_shared_set_is_still_a_regression(conn, on):
    row = _rerun(conn, on, _all_pass(10), [("q3-4b", f"c{i}", i < 2) for i in range(10)])
    assert row["outcome"] == reverify.REGRESSED
    assert "8 lost against 0 gained" in row["detail"]
