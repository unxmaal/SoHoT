"""The poll deploys the newest main commit since live whose check-macos passed, not only the tip. #1702."""
from __future__ import annotations

import json
import subprocess

import pytest

from harness import deploy
from harness import deploy_guard as g


def _git(cwd, *args) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def world(tmp_path):
    """origin main at L (the live release checkout) and a pusher; push(n) lands n commits, returns them oldest first."""
    origin, link, other = tmp_path / "origin.git", tmp_path / "deploy", tmp_path / "other"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    for d in (link, other):
        subprocess.run(["git", "clone", "-q", str(origin), str(d)], check=True)
        _git(d, "config", "user.email", "t@example.invalid")
        _git(d, "config", "user.name", "t")
    _git(other, "commit", "-q", "--allow-empty", "-m", "live")
    _git(other, "push", "-q", "origin", "HEAD:main")
    _git(link, "pull", "-q", "origin", "main")

    def push(n: int) -> list[str]:
        shas = []
        for i in range(n):
            _git(other, "commit", "-q", "--allow-empty", "-m", f"merge {i} (#{900 + i})")
            shas.append(_git(other, "rev-parse", "HEAD"))
        _git(other, "push", "-q", "origin", "HEAD:main")
        return shas

    return {"link": link, "other": other, "push": push}


def fake_gh(states: dict, calls: list):
    """Push runs of check-macos per sha: 'in_progress', or a conclusion; PR runs never exist."""
    ids = {sha: i + 1 for i, sha in enumerate(states)}
    by_id = {i: states[sha] for sha, i in ids.items()}

    def gh(argv):
        calls.append(argv)
        if argv[:2] == ["run", "list"]:
            sha = argv[argv.index("--commit") + 1]
            if argv[argv.index("--event") + 1] != "push" or sha not in states:
                return "[]"
            st = states[sha]
            return json.dumps([{"databaseId": ids[sha], "headSha": sha, "url": f"u/{ids[sha]}",
                                "status": "in_progress" if st == "in_progress" else "completed",
                                "conclusion": "" if st == "in_progress" else st}])
        return json.dumps({"jobs": [{"name": g.JOB, "conclusion": by_id[int(argv[2])]}]})
    return gh


def _poll(world, states, calls=None):
    calls = [] if calls is None else calls
    gh = fake_gh(states, calls)
    return deploy.poll(src=world["link"], green=lambda s: g.judge(s, gh=gh, repo=world["link"]),
                       own=lambda s: (g.WAITING, "running"), alert=lambda m: None, environ={})


def test_the_tip_in_progress_queues_the_newest_passed_older_commit(world):
    c = world["push"](4)
    got = _poll(world, {c[3]: "in_progress", c[2]: "cancelled", c[1]: "success", c[0]: "success"})
    assert got["queued"]["output"] == c[1], got["why"]


def test_a_failed_newer_commit_falls_back_to_an_older_passed_one(world):
    c = world["push"](5)
    got = _poll(world, {c[4]: "in_progress", c[3]: "cancelled", c[2]: "failure", c[1]: "cancelled",
                        c[0]: "success"})
    assert got["queued"]["output"] == c[0], got["why"]


def test_nothing_older_than_the_live_release_is_queued(world):
    old = _git(world["link"], "rev-parse", "HEAD")
    world["push"](1)
    _git(world["link"], "pull", "-q", "origin", "main")
    c = world["push"](2)
    calls = []
    got = _poll(world, {c[1]: "in_progress", c[0]: "failure", old: "success"}, calls)
    assert got["queued"] is None and "older main commit" in got["why"]
    assert not any(old in a for a in calls)


def test_a_later_passed_commit_supersedes_the_queued_older_one(world):
    c = world["push"](3)
    first = _poll(world, {c[2]: "in_progress", c[1]: "in_progress", c[0]: "success"})
    assert first["queued"]["output"] == c[0]
    again = _poll(world, {c[2]: "in_progress", c[1]: "in_progress", c[0]: "success"})
    assert again["queued"] is None and "already queued" in again["why"]
    later = _poll(world, {c[2]: "success", c[1]: "in_progress", c[0]: "success"})
    assert later["queued"]["output"] == c[2] and later["superseded"] == [first["queued"]["id"]]


def test_a_live_release_off_main_only_judges_the_tip(world):
    _git(world["link"], "commit", "-q", "--allow-empty", "-m", "local")
    c = world["push"](2)
    assert deploy.newer(world["link"], c[1], _git(world["link"], "rev-parse", "HEAD")) == [c[1]]
    got = _poll(world, {c[1]: "in_progress", c[0]: "success"})
    assert got["queued"] is None
