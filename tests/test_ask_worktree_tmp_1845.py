"""local_complete reads files in the tmp/ of every git worktree of the checkout, and nothing else in them. #1845."""
import os
import subprocess
import sys

import pytest

from harness import ask
from tests.test_mcp_delegate import Fake, fake  # noqa: F401

symlinks = pytest.mark.skipif(sys.platform == "win32", reason="symlinks need privileges on Windows")


def _git(where, *args):
    subprocess.run(["git", "-C", str(where), "-c", "user.email=t@example.invalid", "-c", "user.name=t", *args],
                   check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A checkout with an agent worktree, a sibling worktree and a release the server runs from."""
    checkout = tmp_path / "sohot"
    checkout.mkdir()
    _git(checkout, "init", "-q", "-b", "main")
    _git(checkout, "commit", "-q", "--allow-empty", "-m", "base")
    agent = checkout / ".claude" / "worktrees" / "agent-1"
    sibling = tmp_path / "sohot-9"
    release = tmp_path / "releases" / "50-abc"
    for i, wt in enumerate((agent, sibling, release)):
        _git(checkout, "worktree", "add", "-q", "-b", f"b{i}", str(wt))
    for wt in (checkout, agent, sibling):
        (wt / "tmp" / "1845").mkdir(parents=True)
        (wt / "tmp" / "1845" / "x.log").write_text("FAILED test_q\n", encoding="utf-8", newline="\n")
        (wt / ".env").write_text("TOKEN=secret\n", encoding="utf-8")
    monkeypatch.setattr(ask, "running_checkout", lambda: release)
    monkeypatch.delenv(ask.ROOTS_ENV, raising=False)
    return checkout, agent, sibling


@pytest.fixture
def mcp_server():
    return pytest.importorskip("harness.mcp_server", reason="needs the `mcp` group: uv run --group mcp pytest")


def test_the_tool_reads_a_file_in_an_agent_worktrees_tmp(fake, mcp_server, repo):  # noqa: F811
    _, agent, _ = repo
    fake.reply = "test_q"
    f = agent / "tmp" / "1845" / "x.log"
    got = mcp_server.local_complete(paths=[str(f)], question="what failed?")
    assert got.files == [{"path": os.path.realpath(f), "bytes": 14}] and got.call_id


@pytest.mark.parametrize("which", [0, 1, 2], ids=["checkout", "agent", "sibling"])
def test_every_worktrees_tmp_is_readable(repo, which):
    f = repo[which] / "tmp" / "1845" / "x.log"
    [got] = ask.read([str(f)], ask.default_roots())
    assert got.path == os.path.realpath(f)


@pytest.mark.parametrize("which", [0, 1, 2], ids=["checkout", "agent", "sibling"])
def test_nothing_else_in_a_worktree_is_readable(repo, which):
    wt = repo[which]
    (wt / "harness" / "tmp").mkdir(parents=True)
    (wt / "harness" / "tmp" / "k.log").write_text("x\n", encoding="utf-8")
    for f in (wt / ".env", wt / "harness" / "tmp" / "k.log"):
        with pytest.raises(ask.Refused, match="outside the roots"):
            ask.read([str(f)], ask.default_roots())


def test_the_tool_refuses_a_worktrees_env_as_an_mcp_error(fake, mcp_server, repo):  # noqa: F811
    from mcp.server.mcpserver.exceptions import ToolError
    with pytest.raises(ToolError, match="outside the roots"):
        mcp_server.local_complete(paths=[str(repo[1] / ".env")], question="q")
    assert fake.seen == []


@symlinks
def test_a_symlink_in_tmp_to_the_worktrees_env_is_refused(repo):
    agent = repo[1]
    (agent / "tmp" / "env.log").symlink_to(agent / ".env")
    with pytest.raises(ask.Refused, match="symlink out"):
        ask.read([str(agent / "tmp" / "env.log")], ask.default_roots())


@symlinks
def test_a_tmp_that_is_a_symlink_out_of_its_worktree_is_refused(repo, tmp_path):
    sibling = repo[2]
    secrets = tmp_path / "secrets"
    secrets.mkdir()
    (secrets / "key").write_text("k\n", encoding="utf-8")
    (sibling / "tmp" / "1845" / "x.log").unlink()
    (sibling / "tmp" / "1845").rmdir()
    (sibling / "tmp").rmdir()
    (sibling / "tmp").symlink_to(secrets)
    with pytest.raises(ask.Refused, match="symlink out"):
        ask.read([str(sibling / "tmp" / "key")], ask.default_roots())


def test_the_refusal_names_the_worktrees_once_rather_than_each(repo):
    with pytest.raises(ask.Refused) as got:
        ask.read([str(repo[1] / ".env")], ask.default_roots())
    names = str(got.value).split("reads: ", 1)[1]
    assert "tmp/ of 4 git worktrees of " in names and os.path.realpath(repo[2]) not in names


def test_code_outside_any_git_checkout_adds_no_worktree_roots(tmp_path, monkeypatch):
    monkeypatch.setattr(ask, "running_checkout", lambda: tmp_path)
    monkeypatch.delenv(ask.ROOTS_ENV, raising=False)
    assert ask.worktrees(tmp_path) == []
    assert not any(r.top for r in ask.default_roots())


@pytest.mark.gauntlet("nothing-and-failed-return-the-same-value", site="harness/ask.py:worktrees:except")
def test_an_unreadable_git_layout_adds_no_worktree_roots_and_still_reads_the_others(tmp_path, monkeypatch):
    wt = tmp_path / "wt"
    wt.mkdir()
    (wt / ".git").write_text("not a gitdir line\n", encoding="utf-8")
    monkeypatch.setattr(ask, "running_checkout", lambda: wt)
    monkeypatch.setenv(ask.ROOTS_ENV, str(tmp_path / "logs"))
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "a.log").write_text("x\n", encoding="utf-8")
    assert ask.worktrees(wt) == []
    assert ask.read([str(tmp_path / "logs" / "a.log")], ask.default_roots())


def test_the_running_checkout_is_the_code_this_runs_from():
    from harness import paths
    assert ask.running_checkout() == paths.REPO
