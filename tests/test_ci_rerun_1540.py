"""A check-macos no runner picked up reruns once on a PR or main; one cancelled after its steps started never does on a PR (#1540)."""
import json
from pathlib import Path

import pytest
import yaml

from harness import ci_rerun

FIXTURES = Path(__file__).parent / "fixtures" / "ci_rerun_1540"
LIMIT = ci_rerun.limit_minutes()


def _recorded(run_id: int) -> tuple[dict, list[dict]]:
    run = json.loads((FIXTURES / f"{run_id}.json").read_text(encoding="utf-8"))
    return run, run.pop("jobs")


def test_a_pr_job_no_runner_picked_up_reruns_once_on_the_prs_head():
    run, jobs = _recorded(41866072673)
    assert run["conclusion"] == "failure" and not next(j for j in jobs if j["name"] == ci_rerun.JOB)["steps"]
    ok, why = ci_rerun.decide(run, jobs, run["head_sha"], LIMIT, pr=1539)
    assert ok and "before any step ran (no runner) on PR #1539's head 0d0276c3" in why and "attempt 2" in why, why


@pytest.mark.parametrize("run_id,said", [
    (40865841515, "with its steps started: its own timeout or a newer push"),
    (41478766032, "with its steps started: its own timeout or a newer push"),
])
def test_a_pr_job_cancelled_after_its_steps_started_is_not_rerun(run_id, said):
    run, jobs = _recorded(run_id)
    ok, why = ci_rerun.decide(run, jobs, run["head_sha"], LIMIT, pr=1)
    assert not ok and said in why, why


def test_a_superseded_or_closed_or_rerun_or_forked_no_runner_job_is_not_rerun():
    run, jobs = _recorded(41481584505)
    assert ci_rerun.decide(run, jobs, run["head_sha"], LIMIT)[0]
    ok, why = ci_rerun.decide(run, jobs, "f" * 40, LIMIT, pr=1500)
    assert not ok and "PR #1500's head is now ffffffff" in why, why
    ok, why = ci_rerun.decide(run, jobs, "", LIMIT)
    assert not ok and "the head of no open PR" in why, why
    ok, why = ci_rerun.decide({**run, "run_attempt": 2}, jobs, run["head_sha"], LIMIT)
    assert not ok and "already had its 1 automatic rerun" in why, why
    ok, why = ci_rerun.decide({**run, "head_repository": {"full_name": "someone/SoHoT"}}, jobs, run["head_sha"], LIMIT)
    assert not ok and "from a fork" in why, why


def test_a_no_runner_job_on_mains_tip_reruns_too():
    run, jobs = _recorded(41866072673)
    push = {**run, "event": "push", "head_branch": "main"}
    ok, why = ci_rerun.decide(push, jobs, run["head_sha"], LIMIT)
    assert ok and "before any step ran (no runner) on main" in why, why


def _gh(run, jobs, pulls, calls):
    def gh(argv):
        calls.append(argv)
        if argv[:2] == ["run", "rerun"]:
            return ""
        if "/pulls?" in argv[1]:
            return json.dumps(pulls)
        if "/jobs" in argv[1]:
            return json.dumps({"jobs": jobs})
        return json.dumps(run)
    return gh


def test_main_finds_the_open_pr_from_the_runs_branch_and_reruns_only_on_its_head():
    run, jobs = _recorded(41866072673)
    calls = []
    pulls = [{"number": 1539, "head": {"sha": run["head_sha"]}}]
    ci_rerun.main([str(run["id"])], gh=_gh(run, jobs, pulls, calls), environ={})
    assert ["run", "rerun", str(run["id"]), "-R", ci_rerun.REPO] in calls
    assert any(c[1].endswith("pulls?state=open&head=unxmaal:reverify-grown-1535") for c in calls if c[0] == "api")
    calls.clear()
    ci_rerun.main([str(run["id"])], gh=_gh(run, jobs, [{"number": 1539, "head": {"sha": "e" * 40}}], calls), environ={})
    assert not [c for c in calls if c[:2] == ["run", "rerun"]]
    calls.clear()
    ci_rerun.main([str(run["id"])], gh=_gh(run, jobs, [], calls), environ={})
    assert not [c for c in calls if c[:2] == ["run", "rerun"]]


def test_the_workflow_lets_a_failed_pr_run_reach_the_decision():
    wf = yaml.safe_load((ci_rerun.WORKFLOW.parent / "rerun-cancelled.yml").read_text(encoding="utf-8"))
    job = wf["jobs"]["rerun-once"]
    cond = " ".join(job["if"].split())
    for term in ("'pull_request'", "conclusion == 'failure'", "conclusion == 'cancelled'",
                 "head_repository.full_name == github.repository", "run_attempt <= 1"):
        assert term in cond, term
    assert job["permissions"]["actions"] == "write"
