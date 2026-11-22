"""#2114: a worktree whose pull request merged, clean of tracked changes, is removed; every other one is kept and listed."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from harness import paths, worktrees

LONG_AGO, FAR_OFF = "2000-01-01T00:00:00Z", "2999-01-01T00:00:00Z"
GH = """#!/bin/sh
echo "$@" >> "$FAKE_GH/calls"
[ -e "$FAKE_GH/fail" ] && { echo "gh: not logged in" >&2; exit 1; }
while [ $# -gt 0 ]; do [ "$1" = --head ] && b="$2"; shift; done
cat "$FAKE_GH/$b.json" 2>/dev/null || echo "[]"
"""


def git(cwd: Path, *argv: str) -> str:
    got = subprocess.run(["git", *argv], cwd=cwd, capture_output=True, text=True, check=True)
    return got.stdout.strip()


class Repo:
    def __init__(self, tmp: Path, monkeypatch):
        self.tmp, self.main, self.gh = tmp, tmp / "sohot", tmp / "gh"
        self.main.mkdir()
        self.gh.mkdir()
        (tmp / "bin").mkdir()
        (tmp / "bin" / "gh").write_text(GH, encoding="utf-8")
        (tmp / "bin" / "gh").chmod(0o755)
        monkeypatch.setenv("PATH", f"{tmp / 'bin'}{os.pathsep}{os.environ['PATH']}")
        monkeypatch.setenv("FAKE_GH", str(self.gh))
        for k, v in (("GIT_AUTHOR_NAME", "t"), ("GIT_AUTHOR_EMAIL", "t@example.invalid"),
                     ("GIT_COMMITTER_NAME", "t"), ("GIT_COMMITTER_EMAIL", "t@example.invalid")):
            monkeypatch.setenv(k, v)
        git(self.main, "init", "-q", "-b", "main")
        (self.main / "a.txt").write_text("a\n", encoding="utf-8")
        (self.main / ".gitignore").write_text("tmp/\n", encoding="utf-8")
        git(self.main, "add", "a.txt", ".gitignore")
        git(self.main, "commit", "-q", "-m", "base")
        monkeypatch.setattr(worktrees, "checkout", lambda: self.main)

    def add(self, name: str, branch: str, state: str | None = None, where: Path | None = None) -> Path:
        """A worktree on `branch` with one commit, and the pull request the fake gh answers for it."""
        wt = (where or self.tmp) / name
        git(self.main, "worktree", "add", "-q", str(wt), "-b", branch)
        (wt / "b.txt").write_text(branch, encoding="utf-8")
        git(wt, "add", "b.txt")
        git(wt, "commit", "-q", "-m", branch)
        if state:
            self.pr(branch, state, git(wt, "rev-parse", "HEAD"))
        return wt

    def pr(self, branch: str, state: str, sha: str, number: int = 7, merged_at: str = LONG_AGO) -> None:
        row = {"number": number, "state": state, "headRefOid": sha, "commits": [{"oid": sha}],
               "mergedAt": merged_at if state == "MERGED" else None}
        (self.gh / f"{branch}.json").write_text(json.dumps([row]), encoding="utf-8")

    def entries(self) -> list[str]:
        return [ln.split(" ", 1)[1] for ln in git(self.main, "worktree", "list", "--porcelain").splitlines()
                if ln.startswith("worktree ")]

    def prune(self, **kw) -> dict:
        kw.setdefault("roots", [])
        kw.setdefault("holding", lambda dirs: {})
        return {t.path.name: t for t in worktrees.prune(**kw)}


@pytest.fixture
def repo(tmp_path, monkeypatch):
    return Repo(tmp_path.resolve(), monkeypatch)


def test_only_the_merged_clean_worktree_goes(repo):
    clean = repo.add("sohot-1", "fix-1", "MERGED")
    (clean / "scratch.log").write_text("x", encoding="utf-8")
    (clean / "tmp").mkdir()
    (clean / "tmp" / "y").write_text("y", encoding="utf-8")
    dirty = repo.add("sohot-2", "fix-2", "MERGED")
    (dirty / "a.txt").write_text("changed\n", encoding="utf-8")
    opened = repo.add("sohot-3", "fix-3", "OPEN")
    got = repo.prune()
    assert not clean.exists() and str(clean) not in repo.entries()
    assert dirty.is_dir() and opened.is_dir() and repo.main.is_dir()
    assert {str(dirty), str(opened), str(repo.main)} <= set(repo.entries())
    assert (dirty / "a.txt").read_text(encoding="utf-8") == "changed\n"
    assert (got["sohot-1"].action, got["sohot-1"].pr, got["sohot-1"].scratch) == (worktrees.REMOVE, 7, 2)
    assert got["sohot-2"].action == worktrees.KEEP and "1 uncommitted change(s) to tracked files" in got["sohot-2"].why
    assert got["sohot-3"].action == worktrees.KEEP and got["sohot-3"].why == "PR #7 is open"
    text = "\n".join(worktrees.lines(list(got.values()), True))
    assert "removed 1, kept 3" in text and "2 untracked path(s) went with it" in text
    assert f"kept {dirty} [fix-2]" in text and f"kept {opened} [fix-3]: PR #7 is open" in text
    assert "fix-1" in git(repo.main, "branch", "--list", "fix-1")


def test_a_staged_change_is_a_tracked_change_and_untracked_alone_is_not(repo):
    staged = repo.add("sohot-1", "fix-1", "MERGED")
    (staged / "new.txt").write_text("n", encoding="utf-8")
    git(staged, "add", "new.txt")
    loose = repo.add("sohot-2", "fix-2", "MERGED")
    (loose / "loose.txt").write_text("n", encoding="utf-8")
    got = repo.prune()
    assert staged.is_dir() and "tracked files" in got["sohot-1"].why
    assert not loose.exists() and got["sohot-2"].scratch == 1


@pytest.mark.parametrize("state, why", [(None, "no pull request"), ("CLOSED", "PR #7 closed without merging")])
def test_no_pr_or_an_unmerged_one_keeps_it(repo, state, why):
    wt = repo.add("sohot-1", "fix-1", state)
    got = repo.prune()
    assert wt.is_dir() and (got["sohot-1"].action, got["sohot-1"].why) == (worktrees.KEEP, why)


def test_an_open_pr_beside_a_merged_one_keeps_it(repo):
    wt = repo.add("sohot-1", "fix-1")
    sha = git(wt, "rev-parse", "HEAD")
    rows = [{"number": 7, "state": "MERGED", "headRefOid": sha, "commits": [{"oid": sha}], "mergedAt": FAR_OFF},
            {"number": 9, "state": "OPEN", "headRefOid": sha, "commits": [{"oid": sha}], "mergedAt": None}]
    (repo.gh / "fix-1.json").write_text(json.dumps(rows), encoding="utf-8")
    assert repo.prune()["sohot-1"].why == "PR #9 is open" and wt.is_dir()


def test_commits_the_merged_pr_never_had_keep_it(repo):
    wt = repo.add("sohot-1", "fix-1", "MERGED")
    (wt / "b.txt").write_text("more", encoding="utf-8")
    git(wt, "commit", "-q", "-am", "after the merge")
    got = repo.prune()
    assert wt.is_dir() and "was committed after PR #7 merged and is not one of its commits" in got["sohot-1"].why


def test_a_head_rebased_away_before_the_merge_goes(repo):
    wt = repo.add("sohot-1", "fix-1")
    repo.pr("fix-1", "MERGED", "e" * 40, merged_at=FAR_OFF)
    assert repo.prune()["sohot-1"].action == worktrees.REMOVE and not wt.exists()


def test_a_merge_date_that_cannot_be_read_keeps_it(repo):
    wt = repo.add("sohot-1", "fix-1")
    repo.pr("fix-1", "MERGED", "e" * 40, merged_at="soon")
    assert repo.prune()["sohot-1"].why.startswith("not read: ") and wt.is_dir()


def test_an_older_commit_of_the_merged_pr_goes(repo):
    wt = repo.add("sohot-1", "fix-1")
    sha = git(wt, "rev-parse", "HEAD")
    row = {"number": 7, "state": "MERGED", "headRefOid": "f" * 40, "commits": [{"oid": sha}, {"oid": "f" * 40}],
           "mergedAt": LONG_AGO}
    (repo.gh / "fix-1.json").write_text(json.dumps([row]), encoding="utf-8")
    assert repo.prune()["sohot-1"].action == worktrees.REMOVE and not wt.exists()


def test_the_main_checkout_and_the_releases_stay_whatever_gh_says(repo, monkeypatch):
    repo.pr("main", "MERGED", git(repo.main, "rev-parse", "HEAD"))
    monkeypatch.setenv("LOCALHARNESS_HOME", str(repo.tmp / "home"))
    releases = repo.tmp / "home" / "releases"
    releases.mkdir(parents=True)
    release = repo.add("136-abc", "release-1", "MERGED", where=releases)
    detached = repo.tmp / "sohot-detached"
    git(repo.main, "worktree", "add", "-q", "--detach", str(detached))
    assert releases in worktrees.protected() and repo.main in worktrees.protected()
    assert paths.DEFAULT_HOME / "releases" in worktrees.protected() and paths.DEFAULT_HOME != repo.tmp / "home"
    got = repo.prune(roots=None)
    assert repo.main.is_dir() and release.is_dir() and detached.is_dir()
    assert got["sohot"].why == "the main checkout"
    assert got["136-abc"].why == "a release or the checkout this runs from"
    assert got["sohot-detached"].why == "no branch, so no pull request"
    assert all(t.action == worktrees.KEEP for t in got.values())
    assert not (repo.gh / "calls").exists()


def test_a_locked_worktree_stays(repo):
    wt = repo.add("sohot-1", "fix-1", "MERGED")
    git(repo.main, "worktree", "lock", str(wt))
    assert repo.prune()["sohot-1"].why == "locked" and wt.is_dir()


@pytest.mark.parametrize("how", ["fails", "missing", "garbage"])
def test_a_gh_that_cannot_answer_removes_nothing(repo, monkeypatch, how):
    wt = repo.add("sohot-1", "fix-1", "MERGED")
    if how == "fails":
        (repo.gh / "fail").write_text("", encoding="utf-8")
    elif how == "missing":
        (repo.tmp / "bin" / "gh").unlink()
        monkeypatch.setattr(worktrees, "GH", "gh-that-is-not-installed")
    else:
        (repo.gh / "fix-1.json").write_text("not json", encoding="utf-8")
    got = repo.prune()
    assert wt.is_dir() and got["sohot-1"].action == worktrees.KEEP and got["sohot-1"].why.startswith("not read: ")


@pytest.mark.parametrize("held, why", [({"x": ["pid 1 zsh (cwd)"]}, "1 live process(es) run from it: pid 1 zsh (cwd)"),
                                       (None, "no way to tell on this platform which live processes run from it")])
def test_a_worktree_a_live_process_runs_from_stays(repo, held, why):
    wt = repo.add("sohot-1", "fix-1", "MERGED")
    got = repo.prune(holding=lambda dirs: None if held is None else {d: held["x"] for d in dirs})
    assert wt.is_dir() and got["sohot-1"].why == why


def test_a_worktree_holding_a_kept_one_stays_and_one_holding_a_merged_one_goes(repo):
    outer = repo.add("sohot-1", "fix-1", "MERGED")
    inner = repo.add("wt2", "fix-2", "OPEN", where=outer / "tmp")
    outer2 = repo.add("sohot-3", "fix-3", "MERGED")
    inner2 = repo.add("wt4", "fix-4", "MERGED", where=outer2 / "tmp")
    got = repo.prune()
    assert inner.is_dir() and got["sohot-1"].why == "holds the worktree wt2"
    assert not outer2.exists() and not inner2.exists()
    assert sorted(repo.entries()) == sorted([str(repo.main), str(outer), str(inner)])


def test_a_change_made_after_the_survey_keeps_it(repo, monkeypatch):
    wt = repo.add("sohot-1", "fix-1", "MERGED")
    real = worktrees.survey

    def then_edit(*a, **k):
        trees = real(*a, **k)
        (wt / "a.txt").write_text("late\n", encoding="utf-8")
        return trees
    monkeypatch.setattr(worktrees, "survey", then_edit)
    got = repo.prune()
    assert (wt / "a.txt").read_text(encoding="utf-8") == "late\n"
    assert got["sohot-1"].action == worktrees.KEEP and got["sohot-1"].why.startswith("not removed: 1 uncommitted")


def test_survey_and_the_plain_command_remove_nothing(repo, capsys):
    from harness import cli
    wt = repo.add("sohot-1", "fix-1", "MERGED")
    trees = worktrees.survey(roots=[], holding=lambda dirs: {})
    assert wt.is_dir() and [t.action for t in trees] == [worktrees.KEEP, worktrees.REMOVE]
    assert cli.main(["worktrees"]) == 0
    out = capsys.readouterr().out
    assert wt.is_dir() and "would remove 1, keep 1" in out and f"would remove {wt} [fix-1]: PR #7 merged" in out


def test_the_command_with_prune_removes(repo, capsys, monkeypatch):
    from harness import cli, holders
    monkeypatch.setattr(holders, "holding", lambda dirs: {})
    wt = repo.add("sohot-1", "fix-1", "MERGED")
    assert cli.main(["worktrees", "--prune"]) == 0
    assert not wt.exists() and "removed 1, kept 1" in capsys.readouterr().out


def test_the_sweep_prunes_from_the_live_home_only(repo, monkeypatch):
    from harness import holders, monitor
    monkeypatch.setattr(holders, "holding", lambda dirs: {})
    wt = repo.add("sohot-1", "fix-1", "MERGED")
    said: list[str] = []
    assert not monitor.live_home()
    assert "skipped" in worktrees.sweep(said.append) and wt.is_dir()
    assert "not pruned" in said[0] and "live home" in said[0]
    monkeypatch.setattr(monitor, "live_home", lambda home=None: True)
    got = worktrees.sweep(said.append)
    assert not wt.exists() and got["removed"] == [str(wt)] and "removed 1, kept 1" in said[1]


def test_the_sweep_reports_a_repository_it_cannot_read(tmp_path, monkeypatch):
    from harness import monitor
    monkeypatch.setattr(monitor, "live_home", lambda home=None: True)
    monkeypatch.setattr(worktrees, "checkout", lambda: tmp_path)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    said: list[str] = []
    assert "skipped" in worktrees.sweep(said.append) and "not pruned" in said[0]


def test_the_loops_disk_step_runs_the_sweep(monkeypatch):
    from harness.commands import loop
    ran: list[str] = []
    monkeypatch.setattr(loop, "_beat", lambda tier: None)
    monkeypatch.setattr(worktrees, "sweep", lambda say=print: ran.append("worktrees") or {})
    monkeypatch.setattr(loop, "_sweeps", lambda: None)
    loop._upkeep("knob sweeps")
    assert ran == []
    loop._upkeep(loop.UPKEEP[-1])
    assert ran == ["worktrees"]


def test_no_test_reads_the_real_checkout_by_default():
    assert worktrees.checkout() != paths.REPO and not (worktrees.checkout() / ".git").exists()
