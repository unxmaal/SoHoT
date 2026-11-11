"""A served lane whose cases grew past what its model was ever measured on here is due for a re-run. #1535."""
import pytest

from harness import reverify
from harness import workqueue as wq
from harness.commands import reverify as reverify_cmd
from tests.test_reverify import (DAY, NOW, VERSIONS, _latest, check, conn, on,  # noqa: F401
                                 powered, queued, record_run)
from tests import job_rows

pytestmark = pytest.mark.usefixtures("powered")


def _ids(n, start=0):
    return [f"c{i}" for i in range(start, start + n)]


def _run(spec, ids, passing=None):
    return [(spec, i, passing is None or i in passing) for i in ids]


@pytest.fixture
def lane(monkeypatch):
    """The code lane's cases today, per split; tests grow it by assigning to it."""
    now = {"all": set(_ids(10)), "holdout": set(_ids(4))}
    monkeypatch.setattr(reverify, "lane_now",
                        lambda name, spec, split: set(now[split]) if name == "code" else set())
    return now


def _entry(got):
    [entry] = got["planned"]
    return entry


def test_cases_added_after_the_baseline_queue_a_rerun(conn, lane):
    record_run(conn, "code", _run("q3-4b", _ids(10)), at=NOW - DAY)
    lane["all"] = set(_ids(15))
    got = check(conn)
    assert _entry(got)["triggers"] == [[reverify.CASES, "5 of 15 all cases never measured here"]]
    [job] = queued(conn)
    assert job["argv"][job["argv"].index("--split") + 1] == "all"


def test_an_unchanged_lane_has_no_cases_trigger(conn, lane):
    record_run(conn, "code", _run("q3-4b", _ids(10)), at=NOW - DAY)
    assert _entry(check(conn))["skip"] == "nothing moved" and queued(conn) == []


def test_the_cases_are_counted_on_the_baselines_split(conn, lane):
    record_run(conn, "code", _run("q3-4b", _ids(4)), at=NOW - DAY, receipt={"split": "holdout"})
    lane["all"] = set(_ids(30))
    assert _entry(check(conn))["triggers"] == []
    lane["holdout"] = set(_ids(6))
    assert _entry(check(conn))["triggers"] == [[reverify.CASES, "2 of 6 holdout cases never measured here"]]


def test_a_baseline_that_stopped_early_is_no_gap_when_an_older_run_measured_the_rest(conn, lane):
    record_run(conn, "code", _run("q3-4b", _ids(10)), at=NOW - 3 * DAY)
    record_run(conn, "code", _run("q3-4b", _ids(3)), at=NOW - DAY)
    got = _entry(check(conn))
    assert got["triggers"] == [] and got["baseline_run_id"] is not None


def test_a_baseline_that_shares_no_case_with_the_lane_has_nothing_to_pair_on(conn, lane):
    record_run(conn, "code", _run("q3-4b", ["old-a", "old-b"]), at=NOW - DAY)
    assert _entry(check(conn))["triggers"] == []


def _rerun(conn, results):
    job = queued(conn)[-1]
    job_rows.put({**job, "state": wq.DONE, "rc": 0}, conn=conn)
    record_run(conn, "code", results, at=NOW + 60, job_id=job["id"])
    return check(conn, now=NOW + 120)


def test_the_rerun_pairs_on_the_shared_cases_and_its_new_cases_are_the_next_baseline(conn, lane):
    record_run(conn, "code", _run("q3-4b", _ids(10)), at=NOW - DAY)
    lane["all"] = set(_ids(15))
    check(conn)
    got = _rerun(conn, _run("q3-4b", _ids(15)))
    assert got["settled"][0]["outcome"] == reverify.PASSED
    assert "paired on the 10 cases both runs ran, 5 only one ran left out" in got["settled"][0]["detail"]
    entry = _entry(got)
    assert entry["baseline_run_id"] == got["settled"][0]["run_id"]
    assert entry["triggers"] == [] and len(queued(conn)) == 1


def test_cases_a_rerun_for_new_cases_could_not_run_do_not_requeue_it(conn, lane):
    record_run(conn, "code", _run("q3-4b", _ids(10)), at=NOW - DAY)
    lane["all"] = set(_ids(15))
    check(conn)
    got = _rerun(conn, _run("q3-4b", _ids(13)))
    entry = _entry(got)
    assert entry["triggers"] == [[reverify.CASES, "2 of 15 all cases never measured here"]]
    assert entry["skip"].startswith(f"job {queued(conn)[-1]['id']} already re-ran for new cases")
    assert len(queued(conn)) == 1


def test_another_trigger_still_queues_past_a_rerun_for_new_cases(conn, lane, on):
    record_run(conn, "code", _run("q3-4b", _ids(10)), at=NOW - DAY)
    lane["all"] = set(_ids(15))
    check(conn)
    _rerun(conn, _run("q3-4b", _ids(13)))
    on(versions={**VERSIONS, "mlx-lm": "0.29.1"})
    check(conn, now=NOW + 180)
    assert len(queued(conn)) == 2


def test_a_flagged_lane_whose_cases_grew_keeps_its_rerun_spacing(conn, lane):
    record_run(conn, "code", _run("q3-4b", _ids(10)), at=NOW - DAY)
    lane["all"] = set(_ids(15))
    check(conn)
    job = queued(conn)[-1]
    job_rows.put({**job, "state": wq.FAILED, "rc": 1}, conn=conn)
    check(conn, now=NOW + 120)
    assert _latest(conn)["outcome"] == reverify.UNRUN
    entry = _entry(check(conn, now=NOW + DAY))
    assert entry["triggers"] == [[reverify.CASES, "5 of 15 all cases never measured here"]]
    assert entry["skip"].startswith("flagged unrun:") and "re-run again in" in entry["skip"]
    assert len(queued(conn)) == 1
    check(conn, now=NOW + 120 + reverify.days_for(conn, "code") * DAY + 1)
    assert len(queued(conn)) == 2


def test_the_dry_run_line_names_the_cases_trigger(conn, lane):
    record_run(conn, "code", _run("q3-4b", _ids(10)), at=NOW - DAY)
    lane["all"] = set(_ids(12))
    got = check(conn, dry_run=True)
    assert "cases: 2 of 12 all cases never measured here" in reverify_cmd._line(_entry(got))
    assert queued(conn) == []


def test_lane_now_takes_the_split_and_the_methods_a_case_allows():
    held = reverify.lane_now("svg", "q3-30b", "holdout")
    every = reverify.lane_now("svg", "q3-30b", "all")
    assert held and held < every
    assert reverify.lane_now("svg", "omnisvg:4B", "all") < every
