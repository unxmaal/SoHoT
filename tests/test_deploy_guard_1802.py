"""The deploy guard reads the check-macos job, not the run: a run still busy with check-postgres does not hold a deploy. #1802."""
from __future__ import annotations

import copy
import io
import json
import subprocess
from pathlib import Path

import pytest

from harness import deploy
from harness import deploy_guard as g

FIXTURES = Path(__file__).parent / "fixtures" / "deploy_guard_1802"
SHA = "c" * 40


def _recorded(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


QUEUED = "push_queued_43030954088"
GOING = "schedule_in_progress_43032598280"
FAILED_RUN = "push_failed_macos_passed_43025395596"
NEVER_STARTED = "push_cancelled_pending_43034629611"


def fake(by_sha: dict, calls: list | None = None):
    """gh answering `run list --commit S` with by_sha[S]'s recorded run row and `run view ID` with its recorded jobs."""
    rows = {sha: {**rec["run"], "headSha": sha} for sha, rec in by_sha.items()}
    jobs = {rec["run"]["databaseId"]: rec["jobs"] for rec in by_sha.values()}

    def gh(argv):
        if calls is not None:
            calls.append(argv)
        if argv[:2] == ["run", "list"]:
            sha = argv[argv.index("--commit") + 1]
            push = argv[argv.index("--event") + 1] == "push"
            return json.dumps([rows[sha]] if push and sha in rows else [])
        return json.dumps({"jobs": jobs[int(argv[2])]})
    return gh


def no_git(argv, repo=None):
    return subprocess.CompletedProcess(argv, 1, "", "no such ref")


def test_the_recordings_are_what_their_names_say():
    going, queued = _recorded(GOING), _recorded(QUEUED)
    macos = next(j for j in going["jobs"] if j["name"] == g.JOB)
    assert going["run"]["status"] != "completed" and (macos["status"], macos["conclusion"]) == ("completed", "success")
    assert [j["status"] for j in queued["jobs"] if j["name"] == g.JOB] == ["queued"]
    failed = _recorded(FAILED_RUN)
    assert failed["run"]["conclusion"] == "failure" and _recorded(NEVER_STARTED)["jobs"] == []


def test_a_run_still_going_deploys_once_its_check_macos_passed():
    """Main's 07a0d4cb passed check-macos at 13:15 and its run ended at 13:57 on check-postgres (#1802)."""
    state, why = g.own(SHA, fake({SHA: _recorded(GOING)}))
    assert state == g.PASSED and str(_recorded(GOING)["run"]["databaseId"]) in why
    err = io.StringIO()
    assert g.check(SHA, environ={}, gh=fake({SHA: _recorded(GOING)}), err=err, git=no_git) == g.OK


def test_a_run_that_failed_on_another_job_deploys_on_its_passed_check_macos():
    assert g.own(SHA, fake({SHA: _recorded(FAILED_RUN)}))[0] == g.PASSED


def test_a_check_macos_waiting_for_a_runner_waits():
    state, why = g.own(SHA, fake({SHA: _recorded(QUEUED)}))
    assert state == g.WAITING and "gh run watch" in why
    ok, why, by = g.judge(SHA, fake({SHA: _recorded(QUEUED)}), git=no_git)
    assert not ok and by == ""


def test_a_run_cancelled_before_it_started_refuses():
    state, why = g.own(SHA, fake({SHA: _recorded(NEVER_STARTED)}))
    assert state == g.FAILED and "no check-macos job" in why


@pytest.mark.parametrize("status,conclusion", [("completed", "failure"), ("completed", "cancelled"),
                                               ("completed", "skipped"), ("in_progress", ""), ("queued", "")])
def test_a_check_macos_that_has_not_passed_never_deploys_while_the_run_goes_on(status, conclusion):
    """RULE #756: never deploy a sha whose own check-macos did not pass, however the rest of the run stands."""
    rec = copy.deepcopy(_recorded(GOING))
    macos = next(j for j in rec["jobs"] if j["name"] == g.JOB)
    macos.update(status=status, conclusion=conclusion)
    assert g.own(SHA, fake({SHA: rec}))[0] == g.WAITING
    assert not g.judge(SHA, fake({SHA: rec}), git=no_git)[0]


def test_a_passed_check_macos_job_named_otherwise_does_not_count():
    rec = copy.deepcopy(_recorded(GOING))
    for j in rec["jobs"]:
        j["name"] = j["name"].replace(g.JOB, "check-macos-old")
    assert g.own(SHA, fake({SHA: rec}))[0] == g.WAITING


def _git(cwd, *args) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def world(tmp_path):
    """A deploy checkout live at L, and two merges pushed to origin main after it, oldest first."""
    origin, link, other = tmp_path / "origin.git", tmp_path / "deploy", tmp_path / "other"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    for d in (link, other):
        subprocess.run(["git", "clone", "-q", str(origin), str(d)], check=True)
        _git(d, "config", "user.email", "t@example.invalid")
        _git(d, "config", "user.name", "t")
    _git(other, "commit", "-q", "--allow-empty", "-m", "live")
    _git(other, "push", "-q", "origin", "HEAD:main")
    _git(link, "pull", "-q", "origin", "main")
    merges = []
    for i in range(2):
        _git(other, "commit", "-q", "--allow-empty", "-m", f"merge {i} (#{1800 + i})")
        merges.append(_git(other, "rev-parse", "HEAD"))
    _git(other, "push", "-q", "origin", "HEAD:main")
    return link, merges


def test_the_poll_deploys_the_older_merge_whose_check_macos_passed_while_its_run_and_the_tips_go_on(world):
    """The 2026-11-11 shape: the tip's check-macos queued for a runner, the merge before it green but its run busy."""
    link, (older, tip) = world
    gh = fake({tip: _recorded(QUEUED), older: _recorded(GOING)})
    got = deploy.poll(src=link, green=lambda s: g.judge(s, gh=gh, repo=link), own=lambda s: (g.WAITING, "running"),
                      alert=lambda m: None, environ={})
    assert got["queued"] and got["queued"]["output"] == older, got["why"]
