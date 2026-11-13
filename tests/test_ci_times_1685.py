"""soh ci-times and soh burndown on recorded gh JSON: known rows, a PR whose first runs failed, a reopened issue (#1685)."""
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

from harness import burndown, ci_budget, ci_history, ci_times, cli, paths

FX = Path(__file__).parent / "fixtures" / "ci_times_1685"


def _gh(calls: list | None = None):
    recorded = json.loads((FX / "gh.json").read_text(encoding="utf-8"))
    issues = (FX / "issues.ndjson").read_text(encoding="utf-8")

    def gh(argv):
        if calls is not None:
            calls.append(argv)
        if argv[0] in ("pr", "run"):
            return recorded[f"{argv[0]} {argv[1]}"]
        path = argv[2] if argv[1] == "--paginate" else argv[1]
        if path.startswith(f"repos/{burndown.REPO}/issues?"):
            return issues
        return recorded[re.sub(r"&since=[^&]*", "", path)]
    return gh


@pytest.fixture
def home(tmp_path) -> Path:
    for d in json.loads((FX / "deploys.json").read_text(encoding="utf-8")):
        (tmp_path / "deploys").mkdir(exist_ok=True)
        (tmp_path / "deploys" / f"{d['id']}.json").write_text(json.dumps(d), encoding="utf-8")
    return tmp_path


def _rows(home: Path) -> dict:
    got = ci_times.collect(20, 30, home, gh=_gh())
    return got, {r["pr"]: r for r in got["prs"]}


def test_each_merged_pr_gets_its_final_run_merge_main_ci_and_deploy_latency(home):
    got, rows = _rows(home)
    assert [r["pr"] for r in got["prs"]] == [1901, 1920, 1898, 1875]
    assert rows[1875] == {
        "pr": 1875, "title": rows[1875]["title"], "sha": "37c858f3", "open_to_merge_min": 61.1, "macos_min": 10.8,
        "macos": "success", "ci_wall_min": 60.4, "rounds": 1, "rounds_failed": 0, "main_ci_min": 421.1,
        "main_macos_min": 33.7, "main_macos": "success", "deploy": 61, "merge_to_deploy_min": 322.3}
    assert (rows[1920]["open_to_merge_min"], rows[1920]["macos_min"], rows[1920]["deploy"],
            rows[1920]["merge_to_deploy_min"]) == (19.1, 18.5, 72, 2.0)
    assert (rows[1898]["main_ci_min"], rows[1898]["deploy"], rows[1898]["merge_to_deploy_min"]) == (39.9, 72, 36.8)


def test_a_pr_whose_first_runs_failed_shows_its_final_run_and_counts_every_round(home):
    """#1901: cancelled, then failed, then passed; #1898: two of its runs were rerun and still did not pass."""
    _, rows = _rows(home)
    assert rows[1901]["macos_min"] == 30.7 and rows[1901]["macos"] == "success"
    assert (rows[1901]["rounds"], rows[1901]["rounds_failed"]) == (3, 2)
    assert (rows[1898]["rounds"], rows[1898]["rounds_failed"]) == (5, 4)


def test_main_ci_still_running_and_no_deploy_yet_read_as_unknown_not_zero(home):
    _, rows = _rows(home)
    assert rows[1901]["main_ci_min"] is None and rows[1901]["main_macos"] is None
    assert rows[1901]["deploy"] is None and rows[1901]["merge_to_deploy_min"] is None
    assert rows[1920]["main_ci_min"] is None


def test_a_rolled_back_deploy_ships_nothing(home):
    """A rollback of #1920's commit finished before deploy 72 served it; 72 still shipped it."""
    (home / "deploys" / "73.json").write_text(json.dumps(
        {"id": 73, "sha": "8831f7bb471e4308807da384033ce05f1235e604", "outcome": "rolled_back",
         "finished_at": 1794577400.0}), encoding="utf-8")
    _, rows = _rows(home)
    assert (rows[1920]["deploy"], rows[1920]["merge_to_deploy_min"]) == (72, 2.0)


def test_a_deploy_of_an_older_commit_does_not_ship_a_newer_merge(home):
    """Deploy 71 (24cd51c0) finished after #1898 merged but is behind it on main."""
    _, rows = _rows(home)
    assert ci_times.deploys(home)[-2]["id"] == 71
    assert rows[1898]["deploy"] == 72


def test_a_rerun_on_the_same_commit_is_the_final_run_and_a_running_check_is_left_out():
    rollup = [{"name": "check-macos", "conclusion": "FAILURE", "startedAt": "2026-11-13T10:00:00Z",
               "completedAt": "2026-11-13T10:30:00Z"},
              {"name": "check-macos", "conclusion": "SUCCESS", "startedAt": "2026-11-13T11:00:00Z",
               "completedAt": "2026-11-13T11:20:00Z"},
              {"name": "check-postgres", "conclusion": "", "startedAt": "2026-11-13T11:00:00Z",
               "completedAt": "0001-01-01T00:00:00Z"},
              {"name": "store-touched", "conclusion": "SKIPPED", "startedAt": "2026-11-13T11:00:02Z",
               "completedAt": "2026-11-13T11:00:01Z"}]
    assert [(c["name"], c["conclusion"]) for c in ci_times.final_checks(rollup)] == [("check-macos", "SUCCESS")]


def test_main_ci_is_the_newest_attempt_on_the_merge_commit():
    """A cancelled main check-macos rerun later: main CI is merge to the rerun's end."""
    pr = {"number": 1, "title": "t", "createdAt": "2026-11-13T09:00:00Z", "mergedAt": "2026-11-13T10:00:00Z",
          "mergeCommit": {"oid": "a" * 40}, "statusCheckRollup": []}
    main = [{"name": "check-macos", "conclusion": "cancelled", "started_at": "2026-11-13T10:01:00Z",
             "completed_at": "2026-11-13T10:20:00Z"},
            {"name": "check-macos", "conclusion": "success", "started_at": "2026-11-13T11:00:00Z",
             "completed_at": "2026-11-13T11:30:00Z"}]
    row = ci_times.pr_row(pr, [], main, {}, [])
    assert (row["main_ci_min"], row["main_macos_min"], row["main_macos"]) == (90.0, 30.0, "success")
    running = {"name": "check-macos", "conclusion": None, "started_at": "2026-11-13T12:00:00Z", "completed_at": None}
    assert ci_times.pr_row(pr, [], [*main, running], {}, [])["main_ci_min"] is None


def test_a_branch_name_reused_by_an_older_pr_lends_it_no_rounds():
    runs = [{"path": ".github/workflows/ci.yml", "created_at": "2026-11-01T10:00:00Z", "run_attempt": 1,
             "conclusion": "failure"},
            {"path": ".github/workflows/ci.yml", "created_at": "2026-11-13T10:00:00Z", "run_attempt": 1,
             "conclusion": "success"},
            {"path": ".github/workflows/pages.yml", "created_at": "2026-11-13T10:00:00Z", "run_attempt": 1,
             "conclusion": "failure"}]
    opened, merged = ci_times._ts("2026-11-13T09:59:30Z"), ci_times._ts("2026-11-13T12:00:00Z")
    assert ci_times.rounds(runs, opened, merged) == (1, 0)


def test_a_matrix_leg_is_its_job():
    assert ci_times.base("mutation (harness/adopt.py 2)") == "mutation"
    rows = ci_times.job_rows([{"databaseId": 1, "event": "schedule"}], {1: [
        {"name": "mutation (harness/adopt.py)", "status": "completed", "conclusion": "success",
         "started_at": "2026-11-13T10:00:00Z", "completed_at": "2026-11-13T11:00:00Z"}]})
    assert ci_times.job_table(rows)[0]["timeout"] == 120.0


def test_a_job_no_runner_took_is_not_a_run():
    """#1590: a check-postgres cancelled in the queue (steps [], no runner) read as a 107 min run."""
    queued = {"name": "check-postgres", "status": "completed", "conclusion": "cancelled", "steps": [],
              "started_at": "2026-11-13T01:00:09Z", "completed_at": "2026-11-13T02:47:15Z"}
    ran = {**queued, "conclusion": "success", "steps": [{"name": "Set up job"}],
           "started_at": "2026-11-13T03:00:00Z", "completed_at": "2026-11-13T03:40:00Z"}
    rows = ci_times.job_rows([{"databaseId": 1, "event": "pull_request"}], {1: [queued, ran]})
    assert [(r["conclusion"], r["min"]) for r in rows] == [("success", 40.0)]


def test_each_job_is_set_against_its_ci_yml_timeout(home):
    got, _ = _rows(home)
    jobs = {(t["job"], t["event"]): t for t in got["jobs"]}
    assert jobs[("check-macos", "pull_request")] == {
        "job": "check-macos", "event": "pull_request", "runs": 2, "passed": 2, "failed": 0, "cancelled": 0,
        "p50": 24.6, "p95": 30.1, "max": 30.7, "timeout": 56.0, "p95_share": 0.54}
    assert (jobs[("check-postgres", "pull_request")]["timeout"], jobs[("check-postgres", "pull_request")]["p95"]) == (
        77.0, 46.8)
    assert jobs[("check-windows", "workflow_dispatch")]["timeout"] == 111.0
    assert not any(t["job"].startswith("mutation (") for t in got["jobs"])


def test_the_summary_takes_percentiles_over_the_prs_that_have_the_number(home):
    got, _ = _rows(home)
    assert got["summary"]["main_ci_min"]["n"] == 2 and got["summary"]["merge_to_deploy_min"]["n"] == 3
    assert got["summary"]["macos_min"]["p50"] == 22.1


NOW = datetime(2026, 11, 13, 15, 0, tzinfo=timezone.utc)


def test_burndown_weeks_count_opened_closed_and_open_at_each_end():
    got = burndown.collect(3, 7, gh=_gh(), now=NOW)
    assert got["periods"] == [
        {"start": "2026-10-26", "opened": 1, "closed": 1, "net": 0, "open_at_end": 2},
        {"start": "2026-11-02", "opened": 0, "closed": 0, "net": 0, "open_at_end": 2},
        {"start": "2026-11-09", "opened": 5, "closed": 3, "net": 2, "open_at_end": 4}]
    assert got["open"] == 4 and got["ages"] == {"<7d": 2, "<30d": 0, "30d+": 2}
    assert got["labels"] == [("enhancement", 2), ("(none)", 1), ("blocked", 1), ("priority:low", 1), ("studio", 1)]


def test_each_period_ends_with_the_open_count_its_own_rows_add_up_to():
    """Created or closed exactly on a boundary falls in the period that starts there, on both sides of the sum."""
    issues = [{"created_at": "2026-11-12T00:00:00Z", "closed_at": "2026-11-13T00:00:00Z", "state": "closed"},
              {"created_at": "2026-11-11T08:00:00Z", "closed_at": None, "state": "open"}]
    got = burndown.periods(issues, NOW, 3, 1)
    for before, p in zip(got, got[1:]):
        assert p["open_at_end"] == before["open_at_end"] + p["net"]
    assert [p["open_at_end"] for p in got] == [1, 2, 1]


def test_a_reopened_issue_still_open_counts_open_and_never_closed():
    """#1685 in the fixture was closed on 11-11 and reopened: it carries a closed_at but is open."""
    got = burndown.collect(3, 1, gh=_gh(), now=NOW)
    assert got["periods"] == [
        {"start": "2026-11-11", "opened": 1, "closed": 1, "net": 0, "open_at_end": 3},
        {"start": "2026-11-12", "opened": 0, "closed": 0, "net": 0, "open_at_end": 3},
        {"start": "2026-11-13", "opened": 2, "closed": 1, "net": 1, "open_at_end": 4}]


def test_both_verbs_print_a_table_and_give_the_rows_under_json(home, monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(ci_history, "_gh", _gh(calls))
    monkeypatch.setattr(paths, "home", lambda: home)
    assert cli.main(["ci-times", "--last", "4", "--runs", "4"]) == 0
    out = capsys.readouterr().out
    assert "| #1875 | 61.1 | 10.8 | 60.4 | 1 (0) | 421.1 | 61 | 322.3 |" in out
    assert "| check-macos | pull_request | 2 | 2 | 0 | 0 | 24.6 | 30.1 | 30.7 | 56.0 | 54% |" in out
    assert ["pr", "list", "-R", ci_times.REPO, "--state", "merged", "-L", "4", "--json", ci_times.PR_FIELDS] in calls
    assert cli.main(["ci-times", "--json"]) == 0
    got = json.loads(capsys.readouterr().out)
    assert got["ok"] and got["verb"] == "ci-times" and len(got["prs"]) == 4
    assert cli.main(["burndown", "--days", "2", "--json"]) == 0
    got = json.loads(capsys.readouterr().out)
    assert got["verb"] == "burndown" and got["step_days"] == 1 and len(got["periods"]) == 2
    assert cli.main(["burndown"]) == 0
    assert "| week from | opened | closed | net | open at end |" in capsys.readouterr().out


def test_a_job_missing_from_ci_yml_has_no_timeout_but_an_unreadable_ci_yml_is_an_error(home, tmp_path, monkeypatch,
                                                                                       capsys):
    rows = [{"job": "gone", "event": "push", "run": 1, "conclusion": "success", "min": 3.0}]
    assert ci_times.job_table(rows)[0]["timeout"] is None and ci_times.job_table(rows)[0]["p95_share"] is None
    monkeypatch.setattr(ci_history, "_gh", _gh())
    monkeypatch.setattr(paths, "home", lambda: home)
    monkeypatch.setattr(ci_budget, "WORKFLOW", tmp_path / "missing.yml")
    assert cli.main(["ci-times"]) == 1
    assert "missing.yml" in capsys.readouterr().err


def test_a_gh_failure_is_one_error_line_not_a_traceback(monkeypatch, capsys):
    def down(argv):
        raise RuntimeError("gh pr list failed: HTTP 502")
    monkeypatch.setattr(ci_history, "_gh", down)
    assert cli.main(["ci-times"]) == 1
    assert cli.main(["burndown"]) == 1
    assert capsys.readouterr().err.count("HTTP 502") == 2
