"""Knob PRs merge cleanly when they touch different spots, and a merge never brings back a deleted backlog line (#751, #756)."""
import importlib.util
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from harness import knobs

REPO = Path(__file__).resolve().parent.parent
BACKLOG = Path("tests/gauntlet/knob_backlog")
AREAS = Path("harness/knobs")
ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
       "GIT_COMMITTER_EMAIL": "t@t", "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull}


def git(cwd, *args, check=True):
    return subprocess.run(["git", "-c", "commit.gpgsign=false", *args], cwd=cwd, env=ENV,
                          capture_output=True, text=True, check=check)


def _add_knob(root: Path, area: str, name: str):
    path = root / AREAS / f"{area}.py"
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    end = max(i for i, line in enumerate(lines) if line.rstrip() == "]")
    lines.insert(end, f'    _k("{name}", ["harness/{name}.py:MAX_{name.upper()}"], [1, 2], note="#751 merge test"),\n')
    path.write_text("".join(lines), encoding="utf-8")


def _add_backlog(root: Path, site: str):
    path = root / BACKLOG / "harness.txt"
    lines = path.read_text(encoding="utf-8").splitlines()
    path.write_text("\n".join(sorted({*lines, site})) + "\n", encoding="utf-8")


def _branch(root: Path, name: str, edit):
    git(root, "checkout", "-q", "-b", name, "main")
    edit()
    git(root, "commit", "-q", "-am", name)


def _registry(root: Path) -> dict:
    lists = {}
    for path in sorted((root / AREAS).glob("*.py")):
        if path.stem in ("__init__", "base"):
            continue
        spec = importlib.util.spec_from_file_location(f"_merged_{path.stem}", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        lists[path.stem] = mod.KNOBS
    return knobs.collect(lists)[0]


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "w"
    for rel in (AREAS, BACKLOG):
        shutil.copytree(REPO / rel, root / rel, ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy(REPO / ".gitattributes", root / ".gitattributes")
    git(root, "init", "-q", "-b", "main")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "base")
    return root


def test_two_prs_adding_a_knob_in_different_areas_and_a_backlog_line_each_merge_cleanly(repo):
    first, second = sorted(knobs.areas())[:2]
    _branch(repo, "left", lambda: (_add_knob(repo, first, "left_knob"), _add_backlog(repo, "harness/zz_left.py:MAX_X")))
    _branch(repo, "right", lambda: (_add_knob(repo, second, "right_knob"), _add_backlog(repo, "harness/aa_right.py:MAX_X")))
    bare = repo.parent / "bare.git"
    git(repo.parent, "clone", "-q", "--bare", str(repo), str(bare))
    assert git(bare, "merge-tree", "--write-tree", "left", "right", check=False).returncode == 0, "conflicts with no merge driver"
    git(repo, "checkout", "-q", "left")
    git(repo, "merge", "-q", "--no-edit", "right")
    got = _registry(repo)
    assert {"left_knob", "right_knob"} <= set(got) and len(got) == len(knobs.KNOBS) + 2
    lines = (repo / BACKLOG / "harness.txt").read_text(encoding="utf-8").splitlines()
    assert lines == sorted(lines) and {"harness/zz_left.py:MAX_X", "harness/aa_right.py:MAX_X"} <= set(lines)


def _drop_backlog(root: Path, site: str):
    path = root / BACKLOG / "harness.txt"
    lines = path.read_text(encoding="utf-8").splitlines()
    assert site in lines
    path.write_text("\n".join(s for s in lines if s != site) + "\n", encoding="utf-8")


def _neighbours() -> tuple[str, str]:
    lines = (REPO / BACKLOG / "harness.txt").read_text(encoding="utf-8").splitlines()
    return lines[len(lines) // 2], lines[len(lines) // 2 + 1]


def _settled(repo, how: str) -> tuple[bool, list[str]]:
    git(repo, "checkout", "-q", "left")
    args = ["merge", "-q", "--no-edit", "right"] if how == "merge" else ["rebase", "-q", "right"]
    clean = git(repo, *args, check=False).returncode == 0
    return clean, (repo / BACKLOG / "harness.txt").read_text(encoding="utf-8").splitlines()


@pytest.mark.parametrize("how", ["merge", "rebase"])
def test_two_branches_each_deleting_a_neighbouring_backlog_line_never_resurrect_either(repo, how):
    a, b = _neighbours()
    _branch(repo, "left", lambda: _drop_backlog(repo, a))
    _branch(repo, "right", lambda: _drop_backlog(repo, b))
    clean, lines = _settled(repo, how)
    assert not clean or not {a, b} & set(lines), f"a clean {how} brought back a deleted site"


@pytest.mark.parametrize("how", ["merge", "rebase"])
def test_a_deletion_beside_an_addition_is_kept_or_conflicts(repo, how):
    a, b = _neighbours()
    _branch(repo, "left", lambda: _drop_backlog(repo, a))
    _branch(repo, "right", lambda: _add_backlog(repo, a + "_zz"))
    clean, lines = _settled(repo, how)
    assert not clean or (a not in lines and a + "_zz" in lines and b in lines), f"a clean {how} brought back {a}"


@pytest.mark.parametrize("how", ["merge", "rebase"])
def test_two_branches_deleting_far_apart_backlog_lines_merge_cleanly_and_both_stay_deleted(repo, how):
    lines = (REPO / BACKLOG / "harness.txt").read_text(encoding="utf-8").splitlines()
    a, b = lines[len(lines) // 4], lines[3 * len(lines) // 4]
    _branch(repo, "left", lambda: _drop_backlog(repo, a))
    _branch(repo, "right", lambda: _drop_backlog(repo, b))
    clean, got = _settled(repo, how)
    assert clean, f"a {how} of two far-apart deletions conflicted"
    assert not {a, b} & set(got) and len(got) == len(lines) - 2 and got == sorted(got)


@pytest.mark.parametrize("how", ["merge", "rebase"])
def test_two_branches_adding_a_backlog_line_at_the_same_sorted_spot_conflict(repo, how):
    a, _ = _neighbours()
    _branch(repo, "left", lambda: _add_backlog(repo, a + "_left"))
    _branch(repo, "right", lambda: _add_backlog(repo, a + "_right"))
    clean, _ = _settled(repo, how)
    assert not clean, f"a {how} of two same-spot additions merged silently; the #756 trade-off is a conflict"
