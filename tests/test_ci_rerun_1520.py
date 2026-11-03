"""A push-to-main check-macos cancelled at its timeout reruns once; a failure, a superseded or a manual cancel never does (#1520)."""
import json
from datetime import datetime, timezone

import pytest

from harness import ci_rerun

TIP = "ba38b746811328831e8d4c70a44213b7c0c071f2"
LIMIT = 26.0


def _run(**over):
    run = {"id": 41692522061, "event": "push", "head_branch": "main", "conclusion": "cancelled",
           "run_attempt": 1, "head_sha": TIP}
    return {**run, **over}


def _job(minutes, conclusion="cancelled", name=ci_rerun.JOB):
    def iso(t):
        return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"name": name, "conclusion": conclusion, "started_at": iso(1793722000),
            "completed_at": iso(1793722000 + round(minutes * 60))}


def test_a_timeout_on_mains_tip_reruns_once():
    ok, why = ci_rerun.decide(_run(), [_job(26.97)], TIP, LIMIT)
    assert ok and "rerunning it once (attempt 2)" in why


@pytest.mark.parametrize("run,jobs,tip,said", [
    (_run(conclusion="failure"), [_job(20, "failure")], TIP, "never a failure"),
    (_run(conclusion="success"), [_job(20, "success")], TIP, "only a cancelled run"),
    (_run(run_attempt=2), [_job(26.97)], TIP, "already had its 1 automatic rerun"),
    (_run(), [_job(26.97)], "f" * 40, "a rerun would cancel it"),
    (_run(), [_job(LIMIT - 0.1)], TIP, "by a person or a newer push"),
    (_run(event="pull_request", head_branch="x"), [_job(26.97)], TIP, "not a push to main"),
    (_run(event="schedule"), [_job(26.97)], TIP, "not a push to main"),
    (_run(), [_job(26.97, name="check-linux")], TIP, "concluded nothing"),
    (_run(), [_job(26.97, "success")], TIP, "concluded success, not cancelled"),
])
def test_nothing_but_a_timeout_on_the_tip_reruns(run, jobs, tip, said):
    ok, why = ci_rerun.decide(run, jobs, tip, LIMIT)
    assert not ok and said in why, why


def test_a_job_cancelled_at_exactly_its_limit_counts_as_the_timeout():
    assert ci_rerun.decide(_run(), [_job(LIMIT)], TIP, LIMIT)[0]


def test_the_limit_is_check_macos_timeout_in_ci_yml():
    from harness import ci_budget
    assert ci_rerun.limit_minutes() == ci_budget.limit_minutes(ci_rerun.JOB) == ci_budget.MACOS_TIMEOUT_MIN


def _gh(run, jobs, tip, calls):
    def gh(argv):
        calls.append(argv)
        if argv[:2] == ["run", "rerun"]:
            return ""
        path = argv[1]
        if path.endswith("/commits/main"):
            return tip + "\n"
        if "/jobs" in path:
            return json.dumps({"jobs": jobs})
        return json.dumps(run)
    return gh


def test_main_asks_for_a_rerun_only_when_the_decision_says_so(tmp_path):
    limit = ci_rerun.limit_minutes()
    calls = []
    summary = tmp_path / "summary.md"
    assert ci_rerun.main(["41692522061"], gh=_gh(_run(), [_job(limit + 0.9)], TIP, calls),
                         environ={"GITHUB_STEP_SUMMARY": str(summary)}) == 0
    assert ["run", "rerun", "41692522061", "-R", ci_rerun.REPO] in calls
    assert any("attempts/1/jobs" in c[1] for c in calls if c[0] == "api")
    assert "rerunning it once" in summary.read_text(encoding="utf-8")
    calls.clear()
    ci_rerun.main(["41692522061"], gh=_gh(_run(conclusion="failure"), [_job(9, "failure")], TIP, calls), environ={})
    assert not [c for c in calls if c[:2] == ["run", "rerun"]]
    calls.clear()
    ci_rerun.main(["41692522061", "--dry-run"], gh=_gh(_run(), [_job(limit + 0.9)], TIP, calls), environ={})
    assert not [c for c in calls if c[:2] == ["run", "rerun"]]
