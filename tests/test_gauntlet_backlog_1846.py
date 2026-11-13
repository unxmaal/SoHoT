"""The gauntlet backlog is closed to new rows against the merge base, so a fix PR only deletes its own lines (#1846)."""
import dataclasses
import shutil

import pytest
import yaml
from gauntlet import ratchet

from tests.gauntlet import classes, registry
from tests.test_knob_merge import git

REPO = registry.REPO
BACKLOG = registry.BACKLOG_REL
SNAPSHOT = registry.REGISTRY.snapshot_file.relative_to(REPO)


def _lines(root=REPO) -> list[str]:
    return (root / BACKLOG).read_text(encoding="utf-8").splitlines()


def _write(root, lines):
    (root / BACKLOG).write_text("".join(f"{s}\n" for s in lines), encoding="utf-8")


def _assert_no_row_joins_the_backlog(root):
    reg = dataclasses.replace(registry.REGISTRY, root=root, backlog_file=root / BACKLOG, snapshot_file=root / SNAPSHOT)
    assert reg.base_backlog() is not None
    led = {cid: {"unbound": rows} for cid, rows in reg.backlog().items()}
    assert ratchet.backlog_problems(reg, led) == []


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "w"
    (root / BACKLOG).parent.mkdir(parents=True)
    shutil.copy(REPO / BACKLOG, root / BACKLOG)
    shutil.copy(REPO / SNAPSHOT, root / SNAPSHOT)
    git(root, "init", "-q", "-b", "main")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "base")
    git(root, "update-ref", "refs/remotes/origin/main", "HEAD")
    return root


def _class_and_last() -> tuple[tuple[str, ...], str, str]:
    """Every row of the smallest class, and the last and third-to-last rows of another class with three or more."""
    backlog = registry.REGISTRY.backlog()
    small, rows = min(backlog.items(), key=lambda kv: len(kv[1]))
    cid, big = next((cid, big) for cid, big in backlog.items() if len(big) >= 3 and cid != small)
    return tuple(f"{small} {s}" for s in rows), f"{cid} {big[-1]}", f"{cid} {big[-3]}"


def test_two_branches_dropping_different_rows_merge_cleanly_and_the_ratchet_stays_green(repo):
    whole, last, third = _class_and_last()
    for name, drop in (("left", (*whole, last)), ("right", (third,))):
        git(repo, "checkout", "-q", "-b", name, "main")
        _write(repo, [s for s in _lines(repo) if s not in drop])
        git(repo, "commit", "-q", "-am", name)
    assert git(repo, "merge-tree", "--write-tree", "left", "right", check=False).returncode == 0
    git(repo, "checkout", "-q", "left")
    git(repo, "merge", "-q", "--no-edit", "right")
    assert set(_lines()) - set(_lines(repo)) == {*whole, last, third}
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
