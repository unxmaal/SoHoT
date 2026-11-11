"""A re-run whose case set grew or shrank since its baseline pairs on the cases both ran; a repo re-run is past the repo screen. #1496, #1497."""
import pytest

from harness import adopt, baseline, paired, reverify, runs
from tests.test_reverify import (DAY, NOW, VERSIONS, _latest, _queue_and_finish, check, conn, on,  # noqa: F401
                                 powered, queued, record_run, upgraded)
from tests import job_rows

pytestmark = pytest.mark.usefixtures("powered")


def _cases(spec, ids, passing=None):
    return [(spec, i, passing is None or i in passing) for i in ids]


def _ids(prefix, n, start=0):
    return [f"{prefix}{i}" for i in range(start, start + n)]


def _rerun(conn, results):
    _queue_and_finish(conn, results)
    check(conn, now=NOW + 120)
    return _latest(conn)


# ---- #1496: superset, subset, partial overlap, disjoint ----------------------

def test_a_rerun_over_more_cases_than_its_baseline_pairs_on_the_ones_both_ran(upgraded):
    row = _rerun(upgraded, _cases("q3-4b", _ids("c", 15)))
    assert row["outcome"] == reverify.PASSED
    assert "paired on the 10 cases both runs ran, 5 only one ran left out" in row["detail"]


def test_a_rerun_over_fewer_cases_than_its_baseline_pairs_on_the_ones_both_ran(upgraded):
    row = _rerun(upgraded, _cases("q3-4b", _ids("c", 8)))
    assert row["outcome"] == reverify.PASSED
    assert "paired on the 8 cases both runs ran, 2 only one ran left out" in row["detail"]


def test_a_regression_on_the_shared_cases_of_a_larger_rerun_is_still_flagged(upgraded):
    row = _rerun(upgraded, _cases("q3-4b", _ids("c", 20), passing=set(_ids("c", 10, start=8))))
    assert row["outcome"] == reverify.REGRESSED
    assert "8 lost against 0 gained" in row["detail"] and "10 only one ran left out" in row["detail"]


def test_case_sets_that_only_partly_overlap_are_refused_with_the_reason(upgraded):
    row = _rerun(upgraded, _cases("q3-4b", _ids("c", 10, start=5)))
    assert row["outcome"] == reverify.UNRUN
    assert "the case sets differ: 5 only before, 5 only after" in row["detail"]


def test_disjoint_case_sets_are_refused_and_the_rerun_is_the_next_baseline(upgraded):
    conn = upgraded
    row = _rerun(conn, _cases("q3-4b", _ids("d", 10)))
    assert row["outcome"] == reverify.UNRUN and "share no case" in row["detail"]
    assert f"run {row['run_id']} is the baseline for the next re-run" in row["detail"]
    cid = reverify.served(conn)["code"]["candidate_id"]
    assert reverify.baseline(conn, "code", cid, runs.here(conn))["id"] == row["run_id"]


def test_after_a_disjoint_refusal_the_next_rerun_pairs_with_it(upgraded):
    conn = upgraded
    _rerun(conn, _cases("q3-4b", _ids("d", 10)))
    check(conn, now=NOW + 8 * DAY)
    job = queued(conn)[-1]
    from harness import workqueue as wq
    job_rows.put({**job, "state": wq.DONE, "rc": 0}, conn=conn)
    record_run(conn, "code", _cases("q3-4b", _ids("d", 10)), at=NOW + 8 * DAY + 60, job_id=job["id"],
               versions={**VERSIONS, "mlx-lm": "0.29.1"})
    check(conn, now=NOW + 8 * DAY + 120)
    assert _latest(conn)["outcome"] == reverify.PASSED


@pytest.mark.parametrize("after, kept, left", [
    (["a", "b", "c"], ["a", "b"], 1),
    (["a"], ["a"], 1),
    (["a", "b"], ["a", "b"], 0),
    (["b", "c"], ["b", "c"], 0),
    (["x"], ["x"], 0),
])
def test_nested_cuts_both_runs_to_the_shared_cases_only_when_one_set_holds_the_other(after, kept, left):
    before = [{"case_id": f"{k}#1"} for k in ("a", "b")]
    got_before, got_after, got_left = paired.nested(before, [{"case_id": f"{k}#1"} for k in after])
    assert [r["case_id"][0] for r in got_after] == kept and got_left == left
    if left:
        assert {r["case_id"] for r in got_before} == {r["case_id"] for r in got_after}


# ---- #1497: the repo re-run and its incumbent --------------------------------

def _argv(conn, lane):
    [entry] = reverify.plan(conn, now=NOW, facts=reverify_facts(), lane=lane)
    return entry["argv"]


def reverify_facts():
    from harness import memory_store as ms
    return ms.this_machine()


def test_a_repo_rerun_runs_past_the_repo_screen(conn):
    assert "--unscreened" in _argv(conn, "repo")


def test_another_lanes_rerun_has_no_screen_flag(conn):
    assert "--unscreened" not in _argv(conn, "code")


def test_the_repo_incumbent_is_the_repo_lanes_own_and_never_another_lanes_served_model(conn):
    adopt.record(conn, adopt.Verdict("web", "q3-4b", "web-served", True, "won"))
    adopt.record(conn, adopt.Verdict("repo", "repo-before", "repo-now", True, "won"))
    got = reverify.served(conn)
    assert got["repo"]["incumbent"] == "repo-before"
    assert got["repo"]["incumbent"] != got["web"]["spec"]


def test_an_incumbent_that_never_passed_on_the_lane_is_not_rerun_beside_it(conn):
    adopt.record(conn, adopt.Verdict("repo", "repo-before", "repo-now", True, "won"))
    record_run(conn, "repo", _cases("repo-before", _ids("r", baseline.MIN_CASES), passing=set()), at=NOW - DAY)
    assert reverify.served(conn)["repo"]["incumbent"] == ""
    assert "repo-before" not in _argv(conn, "repo")[_argv(conn, "repo").index("--candidates") + 1]


@pytest.mark.parametrize("n, passing", [(baseline.MIN_CASES - 1, set()), (baseline.MIN_CASES, {"r0"})])
def test_an_incumbent_too_little_seen_or_that_passed_a_case_is_kept(conn, n, passing):
    adopt.record(conn, adopt.Verdict("repo", "repo-before", "repo-now", True, "won"))
    record_run(conn, "repo", _cases("repo-before", _ids("r", n), passing=passing), at=NOW - DAY)
    assert reverify.served(conn)["repo"]["incumbent"] == "repo-before"
