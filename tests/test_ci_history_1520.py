"""check-macos history: wall time by path and runner class from job logs, outcomes, p95, and the slowest tests (#1520)."""
import json

from harness import ci_history

LOG = """2026-11-03T15:54:34.6638520Z   SOHOT_FAST_PATH: 1
2026-11-03T15:54:40.1000000Z \x1b[36;1mApple M1 (Virtual)\x1b[0m
2026-11-03T15:54:40.1000001Z 3
2026-11-03T16:18:49.4362940Z ...........                      [ 98%]
2026-11-03T16:18:49.4362941Z ...........                      [100%]
2026-11-03T16:18:49.4965580Z ============================= slowest 60 durations =============================
2026-11-03T16:18:49.4965581Z 103.07s call     tests/test_pii_lane.py::test_neg
2026-11-03T16:18:49.4965582Z 2.50s setup    tests/test_pii_lane.py::test_neg
2026-11-03T16:18:49.4965583Z 84.04s call     tests/test_generated_cases.py::test_ctl[pii_synth-want1]
2026-11-03T16:18:51.1913800Z real 1419.00
2026-11-03T16:18:51.2071770Z user 2148.76
"""


def test_a_log_gives_runner_class_real_seconds_progress_fast_path_and_test_times():
    got = ci_history.from_log(LOG)
    assert got["runner"] == "M1 3cpu" and got["real_s"] == 1419.0 and got["pct"] == 100 and got["fast"] is True
    assert got["tests"] == {"tests/test_pii_lane.py::test_neg": 105.57,
                            "tests/test_generated_cases.py::test_ctl[pii_synth-want1]": 84.04}
    full = ci_history.from_log(LOG.replace("SOHOT_FAST_PATH: 1", "SOHOT_FAST_PATH: 0"))
    assert full["fast"] is False
    assert ci_history.from_log("nothing")["runner"] == "unknown"


def _job(start, end, conclusion="success", step=("00:01:00", None)):
    s0, s1 = step
    return {"id": 7, "name": "check-macos", "status": "completed", "conclusion": conclusion, "run_attempt": 1,
            "started_at": f"2026-11-03T{start}Z", "completed_at": f"2026-11-03T{end}Z",
            "steps": [{"name": "make check", "started_at": f"2026-11-03T{s0}Z",
                       "completed_at": f"2026-11-03T{s1 or end}Z"}]}


RUN = {"databaseId": 1, "event": "push", "headSha": "ba38b746811328831e8d"}


def test_a_job_row_carries_job_and_make_check_minutes():
    row = ci_history.from_job(_job("00:00:00", "00:26:58", "cancelled", ("00:00:54", "00:26:31")), RUN)
    assert row["job_min"] == 26.97 and row["check_min"] == 25.62 and row["sha"] == "ba38b746"
    assert ci_history.from_job({**_job("00:00:00", "00:01:00"), "name": "check-linux"}, RUN) is None
    assert ci_history.from_job({**_job("00:00:00", "00:01:00"), "conclusion": "skipped"}, RUN) is None
    queued = {**_job("00:00:00", "01:47:00", "cancelled"), "steps": []}
    assert ci_history.from_job(queued, RUN) is None, "a job no runner took never ran (#1590)"


def test_a_cancel_is_judged_against_the_limit_its_run_ran_under():
    """#1590: raising check-macos 35 -> 56 turned 15 runs cut at 35 into "superseded" and hid them from the p95."""
    assert ci_history.limit_at("jobs:\n  check-macos:\n    timeout-minutes: 35\n", "check-macos") == 35.0
    assert ci_history.limit_at("jobs:\n  check-macos:\n    runs-on: x\n", "check-macos") == 360.0
    assert ci_history.limit_at("jobs: [", "check-macos") is None and ci_history.limit_at(None, "check-macos") is None
    assert ci_history.limit_at('{"jobs": []}', "check-macos") is None
    cut = {"conclusion": "cancelled", "job_min": 35.6, "limit_min": 35.0}
    assert ci_history.outcome(cut, 56) == "timeout"
    assert ci_history.outcome({**cut, "job_min": 20.0}, 56) == "superseded"
    assert ci_history.outcome({**cut, "limit_min": None}, 56) == "superseded"


def test_collect_records_each_runs_own_limit(tmp_path):
    def gh(argv):
        if argv[0] == "run":
            return json.dumps([RUN])
        if argv[-1].endswith("/logs"):
            return LOG
        if "contents/.github/workflows/ci.yml?ref=" in argv[-1]:
            assert argv[-1].endswith(f"?ref={RUN['headSha']}")
            return "jobs:\n  check-macos:\n    timeout-minutes: 35\n"
        return json.dumps({"jobs": [_job("00:00:00", "00:35:36", "cancelled")]})
    (row,) = ci_history.collect(5, tmp_path, gh=gh)
    assert row["limit_min"] == 35.0 and ci_history.outcome(row, 56) == "timeout"


def test_the_rule_reads_a_p95_that_keeps_the_runs_a_timeout_cut():
    """#1590: 15 of 53 push runs were cut at 35 min; a p95 over finished runs alone read 34.1 and said 35 was enough."""
    rows = [{"fast": False, "runner": "M1 3cpu", "conclusion": "success", "job_min": 30.0, "check_min": 29.0}
            for _ in range(8)]
    rows += [{"fast": False, "runner": "M1 3cpu", "conclusion": "cancelled", "job_min": 35.5, "check_min": 34.0,
              "pct": 80}, {"fast": False, "runner": "M1 3cpu", "conclusion": "cancelled", "job_min": 35.4}]
    (row,) = ci_history.table(rows, 35)
    assert row["job_p95"] == 30.0 and row["timeout"] == 2
    assert row["job_p95_cut"] == round(ci_history.pctl([30.0] * 8 + [44.0, 35.4], 0.95), 1) == 40.1
    assert ci_history.rule_line("check-macos", row, 35).endswith("1.4 x job p95 40.1 = 57 min; timeout-minutes 35 "
                                                                  "below its rule, raise it to 57")
    assert ci_history.rule_line("check-macos", row, 57).endswith("meets its rule")
    assert ci_history.rule_line("coverage-map", row, 35) == ""
    assert "below its rule" in ci_history.render([row], [], 35, name="check-macos")


def test_a_cancel_at_the_limit_is_a_timeout_and_an_earlier_one_superseded():
    assert ci_history.outcome({"conclusion": "cancelled", "job_min": 26.0}, 26) == "timeout"
    assert ci_history.outcome({"conclusion": "cancelled", "job_min": 25.9}, 26) == "superseded"
    assert ci_history.outcome({"conclusion": "success"}, 26) == "passed"
    assert ci_history.outcome({"conclusion": "failure"}, 26) == "failed"


def test_the_table_takes_p95_over_runs_that_ended_by_path_and_runner():
    rows = [{"fast": False, "runner": "M1 3cpu", "conclusion": "success", "job_min": m + 1, "check_min": m}
            for m in range(1, 21)]
    rows.append({"fast": False, "runner": "M1 3cpu", "conclusion": "cancelled", "job_min": 26.9, "check_min": 26.0})
    rows.append({"fast": True, "runner": "M2 Pro 5cpu", "conclusion": "success", "job_min": 8.0, "check_min": 7.0})
    (fast, full) = ci_history.table(rows, 26)
    assert fast["path"] == "fast (PR)" and fast["p95"] == fast["max"] == 7.0
    assert full["runs"] == 21 and full["passed"] == 20 and full["timeout"] == 1
    assert full["p50"] == 10.5 and full["p95"] == 19.1 and full["max"] == 20 and full["job_max"] == 21


def test_the_slowest_tests_are_ranked_by_median_over_full_runs():
    rows = [{"fast": False, "tests": {"a": 10.0, "b": 1.0}}, {"fast": False, "tests": {"a": 30.0, "b": 2.0}},
            {"fast": True, "tests": {"c": 99.0}}]
    assert ci_history.slowest(rows, top=2) == [("a", 20.0, 30.0, 2), ("b", 1.5, 2.0, 2)]


def test_any_job_or_matrix_leg_is_read_from_its_first_make_step():
    """#1588: check-linux, check-windows, check-postgres and each mutation leg are measured like check-macos."""
    leg = {**_job("00:00:00", "02:00:30", "cancelled", ("00:02:00", None)), "name": "mutation (harness/adopt.py 1/2)"}
    leg["steps"] = [{"name": "Run actions/checkout@v4", "started_at": "2026-11-03T00:00:00Z",
                     "completed_at": "2026-11-03T00:01:00Z"}, {**leg["steps"][0], "name": "make mutation"}]
    row = ci_history.from_job(leg, RUN, "mutation")
    assert row["name"] == "mutation (harness/adopt.py 1/2)" and row["check_min"] == 118.5
    assert ci_history.from_job(leg, RUN, "mutation-x") is None and ci_history.from_job(leg, RUN) is None
    pg = {**_job("00:00:00", "00:30:00"), "name": "check-postgres"}
    pg["steps"] = [{**pg["steps"][0], "name": "make test-postgres-suite"}]
    assert ci_history.from_job(pg, RUN, "check-postgres")["check_min"] == 29.0


def test_a_run_cut_at_its_limit_projects_its_length_from_the_progress_it_reached():
    cut = {"fast": False, "runner": "unknown", "conclusion": "cancelled", "job_min": 45.2, "check_min": 42.0, "pct": 74}
    assert ci_history.projected(cut) == round(45.2 + 42.0 * (100 / 74 - 1), 1) == 60.0
    assert ci_history.projected({**cut, "pct": None}) is None
    (row,) = ci_history.table([cut, {**cut, "pct": 20, "job_min": 10.0}], 45)
    assert row["timeout"] == 1 and row["superseded"] == 1 and row["cut_projected_max"] == 60.0
    assert row["path"] == "full (main)"


def test_collect_reads_each_runs_jobs_and_caches_their_logs(tmp_path):
    calls = []

    def gh(argv):
        calls.append(argv)
        if argv[0] == "run":
            return json.dumps([RUN])
        if argv[-1].endswith("/logs"):
            return LOG
        return json.dumps({"jobs": [_job("00:00:00", "00:24:38")]})
    rows = ci_history.collect(5, tmp_path, gh=gh)
    assert len(rows) == 1 and rows[0]["runner"] == "M1 3cpu" and rows[0]["job_min"] == 24.63
    assert "--allow-escape-sequences" in calls[-1]
    n = len(calls)
    ci_history.collect(5, tmp_path, gh=gh)
    assert len(calls) == n + 1, "the second pass reads only the run list; jobs and logs come from the cache"
    assert ci_history.collect(5, tmp_path, gh=gh, name="check-linux", event="schedule") == []
    assert calls[-1][-2:] == ["--event", "schedule"]
