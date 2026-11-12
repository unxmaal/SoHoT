"""The gauntlet backlog is closed to new rows against the merge base, so a fix PR only deletes its own lines (#1846)."""
import dataclasses
import shutil

import pytest
import yaml
from gauntlet import ratchet

from harness import knob_backlog
from tests.gauntlet import classes, registry
from tests.test_knob_merge import git

REPO = registry.REPO
BACKLOG = registry.BACKLOG_REL


def _lines(root=REPO) -> list[str]:
    return (root / BACKLOG).read_text(encoding="utf-8").splitlines()


def _write(root, lines):
    (root / BACKLOG).write_text("".join(f"{s}\n" for s in lines), encoding="utf-8")


def _assert_no_row_joins_the_backlog(root):
    got = registry.backlog_added(root)
    if got is None:
        pytest.fail(f"{knob_backlog.BASE} is not in this clone, so the gauntlet backlog has no merge base to be "
                    "compared with: git fetch origin main (a CI checkout needs fetch-depth: 0)")
    assert not got, (f"not in {BACKLOG} at the merge base with {knob_backlog.BASE}: bind a test to each hit "
                     "or waive it in tests/gauntlet/classes.py, and delete these lines:\n  " + "\n  ".join(got))


def test_no_row_joins_the_gauntlet_backlog():
    _assert_no_row_joins_the_backlog(REPO)


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "w"
    (root / BACKLOG).parent.mkdir(parents=True)
    shutil.copy(REPO / BACKLOG, root / BACKLOG)
    git(root, "init", "-q", "-b", "main")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "base")
    git(root, "update-ref", "refs/remotes/origin/main", "HEAD")
    return root


def _sole_and_last() -> tuple[str, str, str]:
    """A class's only row, and the last and third-to-last rows of a class with three or more."""
    backlog = registry.load_backlog()
    sole = next(f"{cid} {rows[0]}" for cid, rows in backlog.items() if len(rows) == 1)
    cid, rows = next((cid, rows) for cid, rows in backlog.items() if len(rows) >= 3)
    return sole, f"{cid} {rows[-1]}", f"{cid} {rows[-3]}"


def test_dropping_rows_needs_no_other_edit_and_adding_or_swapping_one_fails(repo):
    git(repo, "checkout", "-q", "-b", "work")
    sole, last, _ = _sole_and_last()
    kept = [s for s in _lines(repo) if s not in (sole, last)]
    _write(repo, kept)
    _assert_no_row_joins_the_backlog(repo)
    reg = dataclasses.replace(registry.REGISTRY, root=repo)
    led = {cid: {"unbound": rows} for cid, rows in registry.load_backlog(repo).items()}
    assert ratchet.backlog_problems(reg, led) == []

    new = "a-child-that-outlives-its-owner harness/new.py:spawn"
    _write(repo, sorted([*kept, new]))
    with pytest.raises(AssertionError, match=r"a-child-that-outlives-its-owner harness/new\.py:spawn"):
        _assert_no_row_joins_the_backlog(repo)
    swapped = sorted([*(s for s in _lines() if s != sole), new])
    assert len(swapped) == len(_lines())
    _write(repo, swapped)
    with pytest.raises(AssertionError, match=r"harness/new\.py:spawn"):
        _assert_no_row_joins_the_backlog(repo)


def test_two_branches_dropping_different_rows_merge_cleanly_and_the_ratchet_stays_green(repo):
    sole, last, third = _sole_and_last()
    for name, drop in (("left", (sole, last)), ("right", (third,))):
        git(repo, "checkout", "-q", "-b", name, "main")
        _write(repo, [s for s in _lines(repo) if s not in drop])
        git(repo, "commit", "-q", "-am", name)
    assert git(repo, "merge-tree", "--write-tree", "left", "right", check=False).returncode == 0
    git(repo, "checkout", "-q", "left")
    git(repo, "merge", "-q", "--no-edit", "right")
    assert set(_lines()) - set(_lines(repo)) == {sole, last, third}
    _assert_no_row_joins_the_backlog(repo)


@pytest.mark.parametrize("how", ["merge", "rebase"])
def test_two_branches_dropping_neighbouring_rows_never_resurrect_either(repo, how):
    a, b = _lines(repo)[10:12]
    for name, drop in (("left", a), ("right", b)):
        git(repo, "checkout", "-q", "-b", name, "main")
        _write(repo, [s for s in _lines(repo) if s != drop])
        git(repo, "commit", "-q", "-am", name)
    git(repo, "checkout", "-q", "left")
    clean = git(repo, *(["merge", "-q", "--no-edit"] if how == "merge" else ["rebase", "-q"]), "right",
                check=False).returncode == 0
    assert not clean or not {a, b} & set(_lines(repo)), f"a clean {how} brought back a dropped row"


def test_a_clone_without_the_base_fails_saying_what_to_fetch(repo):
    git(repo, "update-ref", "-d", "refs/remotes/origin/main")
    with pytest.raises(pytest.fail.Exception, match="fetch-depth: 0"):
        _assert_no_row_joins_the_backlog(repo)


def test_every_ci_job_that_runs_make_check_checks_out_the_whole_history():
    jobs = yaml.safe_load((REPO / ".github/workflows/ci.yml").read_text(encoding="utf-8"))["jobs"]
    checking = {name: job for name, job in jobs.items()
                if any("make check" in step.get("run", "") for step in job.get("steps", []))}
    assert checking
    shallow = [name for name, job in checking.items()
               if not any(step.get("uses", "").startswith("actions/checkout")
                          and step.get("with", {}).get("fetch-depth") == 0 for step in job["steps"])]
    assert not shallow, f"these jobs run the backlog ratchet on a shallow clone; give their checkout fetch-depth: 0: {shallow}"


def test_the_backlog_is_one_sorted_row_per_line_of_a_known_class():
    text = (REPO / BACKLOG).read_text(encoding="utf-8")
    lines = text.splitlines()
    assert text.endswith("\n") and lines == sorted(set(lines))
    bad = [s for s in lines if len(s.split(" ")) != 2 or s.split(" ")[0] not in classes.INDEX]
    assert not bad, f"each line is '<class id in tests/gauntlet/classes.py INDEX> <site>': {bad}"
