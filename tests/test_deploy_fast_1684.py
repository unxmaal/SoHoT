"""Merge to live in minutes: a passed PR run on main's exact tree deploys, and the poll runs each minute. #1684."""
from __future__ import annotations

import json
import os
import plistlib
import subprocess
import sys
from pathlib import Path

import pytest

import shells
from harness import deploy
from harness import deploy_guard as g
from harness import workqueue as wq

REPO = Path(__file__).resolve().parents[1]


def _git(cwd, *args) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True).stdout.strip()


def _write(work: Path, files: dict) -> None:
    for rel, text in files.items():
        (work / rel).write_text(text, encoding="utf-8")
    _git(work, "add", "-A")


@pytest.fixture
def gitworld(tmp_path):
    """origin with main at A and a checkout to judge from; helpers make PR heads and squash merges."""
    origin, work, live = tmp_path / "origin.git", tmp_path / "work", tmp_path / "live"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    subprocess.run(["git", "clone", "-q", str(origin), str(work)], check=True)
    _git(work, "config", "user.email", "t@example.invalid")
    _git(work, "config", "user.name", "t")
    _write(work, {"a": "a\n"})
    _git(work, "commit", "-q", "-m", "first")
    _git(work, "push", "-q", "origin", "HEAD:main")
    base = _git(work, "rev-parse", "HEAD")

    def pr(n: int, files: dict, on: str) -> str:
        _git(work, "checkout", "-q", "--detach", on)
        _write(work, files)
        _git(work, "commit", "-q", "-m", f"pr {n}")
        head = _git(work, "rev-parse", "HEAD")
        _git(work, "push", "-q", "origin", f"{head}:refs/pull/{n}/head")
        return head

    def squash(subject: str, files: dict) -> str:
        _git(work, "fetch", "-q", "origin", "main")
        _git(work, "checkout", "-q", "--detach", "origin/main")
        _write(work, files)
        _git(work, "commit", "-q", "-m", subject)
        sha = _git(work, "rev-parse", "HEAD")
        _git(work, "push", "-q", "origin", "HEAD:main")
        return sha

    def checkout() -> Path:
        if not live.exists():
            subprocess.run(["git", "clone", "-q", str(origin), str(live)], check=True)
        _git(live, "fetch", "-q", "origin", "main")
        return live

    return {"origin": origin, "work": work, "base": base, "pr": pr, "squash": squash, "checkout": checkout}


def _run(rid, sha, status="completed", conclusion="success"):
    return {"databaseId": rid, "headSha": sha, "status": status, "conclusion": conclusion,
            "url": f"https://github.com/unxmaal/SoHoT/actions/runs/{rid}"}


def fake_gh(own_runs, pr_runs, jobs, calls):
    """push run list -> own_runs, pull_request run list -> pr_runs, run view ID -> jobs[ID]."""
    def gh(argv):
        calls.append(argv)
        if argv[:2] == ["run", "list"]:
            return json.dumps(pr_runs if argv[argv.index("--event") + 1] == "pull_request" else own_runs)
        rid = int(argv[2])
        return json.dumps({"jobs": [{"name": g.JOB, "status": "completed", "conclusion": jobs[rid]}] if rid in jobs else []})
    return gh


def _pr_lists(calls):
    return [c for c in calls if c[:2] == ["run", "list"] and "pull_request" in c]


def test_main_whose_tree_equals_a_passed_pr_head_deploys_on_the_pr_run(gitworld):
    head = gitworld["pr"](7, {"x": "x\n"}, gitworld["base"])
    sha = gitworld["squash"]("add x (#7)", {"x": "x\n"})
    calls = []
    gh = fake_gh([_run(1, sha, "in_progress", "")], [_run(2, head)], {2: "success"}, calls)
    ok, why, by = g.judge(sha, gh, repo=gitworld["checkout"]())
    assert ok and by == g.BY_PR, why
    assert "PR #7" in why and head[:12] in why and why.endswith("main's own run is waiting")
    assert _pr_lists(calls)[0][_pr_lists(calls)[0].index("--commit") + 1] == head


def test_main_on_no_run_yet_still_deploys_on_the_same_tree_pr_run(gitworld):
    head = gitworld["pr"](7, {"x": "x\n"}, gitworld["base"])
    sha = gitworld["squash"]("add x (#7)", {"x": "x\n"})
    gh = fake_gh([], [_run(2, head)], {2: "success"}, [])
    assert g.judge(sha, gh, repo=gitworld["checkout"]())[2] == g.BY_PR


def test_a_different_tree_refuses_without_asking_github_about_the_pr(gitworld):
    """Main moved under the PR: the squash holds #6's file, the PR head does not."""
    head = gitworld["pr"](7, {"x": "x\n"}, gitworld["base"])
    gitworld["squash"]("add y (#6)", {"y": "y\n"})
    sha = gitworld["squash"]("add x (#7)", {"x": "x\n"})
    calls = []
    gh = fake_gh([_run(1, sha, "in_progress", "")], [_run(2, head)], {2: "success"}, calls)
    ok, why, by = g.judge(sha, gh, repo=gitworld["checkout"]())
    assert not ok and by == "" and "different tree" in why and "still in_progress" in why
    assert _pr_lists(calls) == []


@pytest.mark.parametrize("pr_run,conclusion", [("completed", "failure"), ("in_progress", ""), (None, "")])
def test_a_pr_run_that_did_not_pass_refuses(gitworld, pr_run, conclusion):
    head = gitworld["pr"](7, {"x": "x\n"}, gitworld["base"])
    sha = gitworld["squash"]("add x (#7)", {"x": "x\n"})
    runs = [] if pr_run is None else [_run(2, head, pr_run, conclusion)]
    ok, why, _ = g.judge(sha, fake_gh([], runs, {2: conclusion}, []), repo=gitworld["checkout"]())
    assert not ok and "PR #7" in why and "same tree" not in why


def test_a_pr_run_for_another_head_is_not_this_heads_run(gitworld):
    gitworld["pr"](7, {"x": "x\n"}, gitworld["base"])
    sha = gitworld["squash"]("add x (#7)", {"x": "x\n"})
    ok, why, _ = g.judge(sha, fake_gh([], [_run(2, "f" * 40)], {2: "success"}, []), repo=gitworld["checkout"]())
    assert not ok and "no pull_request run" in why


def test_a_same_tree_head_that_lacks_mains_parent_refuses(gitworld):
    """Its PR run tested a merge of that head into an older main, not this tree."""
    sha = gitworld["squash"]("add x (#7)", {"x": "x\n"})
    work = gitworld["work"]
    stray = _git(work, "commit-tree", f"{sha}^{{tree}}", "-m", "same tree, no history")
    _git(work, "push", "-q", "origin", f"{stray}:refs/pull/7/head")
    ok, why, _ = g.judge(sha, fake_gh([], [_run(2, stray)], {2: "success"}, []), repo=gitworld["checkout"]())
    assert not ok and "lacks main's" in why


def test_a_subject_naming_no_pr_refuses(gitworld):
    sha = gitworld["squash"]("direct push", {"x": "x\n"})
    ok, why, _ = g.judge(sha, fake_gh([], [], {}, []), repo=gitworld["checkout"]())
    assert not ok and "names no pull request" in why


def test_mains_own_failed_run_outranks_a_passed_pr_run(gitworld):
    head = gitworld["pr"](7, {"x": "x\n"}, gitworld["base"])
    sha = gitworld["squash"]("add x (#7)", {"x": "x\n"})
    calls = []
    gh = fake_gh([_run(1, sha)], [_run(2, head)], {1: "failure", 2: "success"}, calls)
    ok, why, _ = g.judge(sha, gh, repo=gitworld["checkout"]())
    assert not ok and "failure" in why and _pr_lists(calls) == []


def test_mains_own_pass_needs_no_pr_and_no_git():
    def git(argv, repo):
        raise AssertionError("main's own pass must not touch git")
    calls = []
    ok, _, by = g.judge("a" * 40, fake_gh([_run(1, "a" * 40)], [], {1: "success"}, calls), git=git)
    assert ok and by == g.BY_MAIN and _pr_lists(calls) == []


# --- the poll: each minute, idle costs no gh call, a PR-run deploy is confirmed by main's own run ---------------

@pytest.fixture
def live(tmp_path):
    origin, link = tmp_path / "origin.git", tmp_path / "deploy"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    subprocess.run(["git", "clone", "-q", str(origin), str(link)], check=True)
    _git(link, "config", "user.email", "t@example.invalid")
    _git(link, "config", "user.name", "t")
    _git(link, "commit", "-q", "--allow-empty", "-m", "first")
    _git(link, "push", "-q", "origin", "HEAD:main")
    return {"origin": origin, "link": link}


def _push_new_main(live) -> str:
    other = live["link"].parent / "other"
    if not other.exists():
        subprocess.run(["git", "clone", "-q", str(live["origin"]), str(other)], check=True)
        _git(other, "config", "user.email", "t@example.invalid")
        _git(other, "config", "user.name", "t")
    _git(other, "pull", "-q", "origin", "main")
    _git(other, "commit", "-q", "--allow-empty", "-m", "next (#9)")
    _git(other, "push", "-q", "origin", "HEAD:main")
    return _git(other, "rev-parse", "HEAD")


def _never(*a):
    raise AssertionError("an idle poll must make no gh call")


def test_an_idle_poll_makes_no_gh_call(live):
    got = deploy.poll(src=live["link"], green=_never, own=_never, alert=_never, environ={})
    assert got["queued"] is None and "already deployed" in got["why"] and got["confirm"] == ""


def test_a_sha_queued_on_its_pr_run_is_confirmed_by_mains_own_run(live):
    sha = _push_new_main(live)
    said = []
    got = deploy.poll(src=live["link"], green=lambda s: (True, "PR #9 passed", g.BY_PR), own=_never,
                      alert=said.append, environ={})
    assert got["queued"]["output"] == sha
    assert deploy._borrowed().read_text(encoding="utf-8") == sha
    again = deploy.poll(src=live["link"], green=_never, own=lambda s: (g.WAITING, "running"), alert=said.append,
                        environ={})
    assert again["confirm"] == "" and deploy._borrowed().exists() and said == []
    last = deploy.poll(src=live["link"], green=_never, own=lambda s: (g.FAILED, "check-macos concluded failure"),
                       alert=said.append, environ={})
    assert len(said) == 1 and sha[:12] in said[0] and "failure" in said[0] and last["confirm"] == said[0]
    assert not deploy._borrowed().exists()
    deploy.poll(src=live["link"], green=_never, own=_never, alert=said.append, environ={})
    assert len(said) == 1


@pytest.mark.parametrize("state", [g.PASSED, g.CANCELLED])
def test_a_passed_or_superseded_own_run_clears_the_confirm_without_an_alert(live, state):
    deploy._borrowed().write_text("c" * 40, encoding="utf-8")
    got = deploy.poll(src=live["link"], green=_never, own=lambda s: (state, "said"), alert=_never, environ={})
    assert state in got["confirm"] and not deploy._borrowed().exists()


def test_a_sha_queued_on_mains_own_run_needs_no_confirm(live):
    _push_new_main(live)
    deploy.poll(src=live["link"], green=lambda s: (True, "main passed", g.BY_MAIN), own=_never, environ={})
    deploy.poll(src=live["link"], green=lambda s: (True, "main passed"), own=_never, environ={})
    assert not deploy._borrowed().exists()
    with wq._store() as c:
        assert len(c.execute("SELECT id FROM jobs WHERE kind = ?", (deploy.KIND,)).fetchall()) == 1


@pytest.mark.skipif(sys.platform != "darwin", reason="launchd units are macOS-only")
def test_the_deploy_poll_runs_every_minute(tmp_path):
    env = {k: v for k, v in os.environ.items() if k not in ("DEPLOY_EVERY_MIN", "LH_ROLE")}
    proc = subprocess.run([shells.BASH, str(REPO / "scripts" / "launchd.sh"), "generate", str(tmp_path)],
                          capture_output=True, text=True, env=env)
    assert proc.returncode == 0, proc.stderr
    unit = plistlib.loads(next(tmp_path.glob("*.deploy.plist")).read_bytes())
    assert [c["Minute"] for c in unit["StartCalendarInterval"]] == list(range(60))
