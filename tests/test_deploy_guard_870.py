"""The deploy guard: only a main commit whose own push run of check-macos passed is deployed. #870."""
import io
import json

import pytest

from harness import deploy_guard as g

SHA = "a" * 40
OTHER = "b" * 40


def fake(runs, jobs=None, calls=None):
    """A gh that answers `run list` with runs and `run view ID` with jobs[ID]."""
    def gh(argv):
        if calls is not None:
            calls.append(argv)
        if argv[:2] == ["run", "list"]:
            return json.dumps(runs)
        return json.dumps({"jobs": (jobs or {})[int(argv[2])]})
    return gh


def run(rid=1, sha=SHA, status="completed", conclusion="success"):
    return {"databaseId": rid, "headSha": sha, "status": status, "conclusion": conclusion,
            "url": f"https://github.com/unxmaal/SoHoT/actions/runs/{rid}"}


def job(conclusion="success", name="check-macos"):
    return {"name": name, "status": "completed", "conclusion": conclusion}


def check(gh, environ=None):
    err = io.StringIO()
    return g.check(SHA, environ={} if environ is None else environ, gh=gh, err=err), err.getvalue()


def test_a_green_run_for_this_commit_deploys():
    calls = []
    rc, out = check(fake([run()], {1: [job()]}, calls))
    assert rc == g.OK and "passed" in out
    assert calls[0][:2] == ["run", "list"]
    for flag, value in (("--workflow", g.WORKFLOW), ("--branch", "main"), ("--event", "push"), ("--commit", SHA)):
        assert calls[0][calls[0].index(flag) + 1] == value


@pytest.mark.parametrize("conclusion", ["failure", "cancelled", "timed_out", "skipped", None])
def test_a_check_that_did_not_pass_refuses(conclusion):
    rc, out = check(fake([run(conclusion="failure")], {1: [job(conclusion)]}))
    assert rc == g.REFUSED and "REFUSING" in out and f"{g.OVERRIDE}=1" in out


def test_a_run_without_the_check_job_refuses():
    rc, out = check(fake([run()], {1: [job(name="check-linux")]}))
    assert rc == g.REFUSED and "no check-macos job" in out


def test_no_run_refuses():
    rc, out = check(fake([]))
    assert rc == g.REFUSED and "no push run" in out


def test_a_run_for_another_commit_is_not_this_commits_run():
    """gh can hand back a run for a different head (KB #480); its green says nothing about SHA."""
    rc, out = check(fake([run(sha=OTHER)], {1: [job()]}))
    assert rc == g.REFUSED and "no push run" in out


def test_an_unfinished_run_refuses_and_says_how_to_wait():
    rc, out = check(fake([run(rid=42, status="in_progress", conclusion="")]))
    assert rc == g.REFUSED
    assert "still in_progress" in out and "runs/42" in out and "gh run watch 42" in out


def test_a_green_rerun_beside_a_red_run_deploys():
    rc, _ = check(fake([run(1, conclusion="failure"), run(2)], {1: [job("failure")], 2: [job()]}))
    assert rc == g.OK


@pytest.mark.parametrize("exc", [g.GhError("gh is not installed or not on PATH"),
                                 g.GhError("gh run list failed (rc 4): not logged in")])
def test_no_answer_from_gh_refuses(exc):
    def gh(argv):
        raise exc
    rc, out = check(gh)
    assert rc == g.REFUSED and "cannot ask GitHub" in out and str(exc) in out


def test_unreadable_gh_output_refuses():
    rc, out = check(lambda argv: "not json")
    assert rc == g.REFUSED and "unreadable" in out


def test_override_deploys_without_asking_and_says_so():
    def gh(argv):
        raise AssertionError("the override must not depend on gh")
    rc, out = check(gh, environ={g.OVERRIDE: "1"})
    assert rc == g.OK and "WARNING" in out and "WITHOUT" in out


def test_override_must_be_exactly_one():
    rc, _ = check(fake([run()], {1: [job("failure")]}), environ={g.OVERRIDE: "yes"})
    assert rc == g.REFUSED


def test_missing_gh_binary_is_a_gh_error(monkeypatch):
    monkeypatch.setenv("PATH", "")
    with pytest.raises(g.GhError, match="not installed"):
        g._gh(["run", "list"])
