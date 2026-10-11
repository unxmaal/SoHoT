"""Two PRs that each add a knob in a different area and a backlog line merge with no conflict (#751)."""
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


def test_two_backlog_lines_at_the_same_spot_merge_by_union_where_git_reads_the_attributes(repo):
    _branch(repo, "left", lambda: _add_backlog(repo, "harness/mm_a.py:MAX_X"))
    _branch(repo, "right", lambda: _add_backlog(repo, "harness/mm_b.py:MAX_X"))
    git(repo, "checkout", "-q", "left")
    git(repo, "merge", "-q", "--no-edit", "right")
    lines = (repo / BACKLOG / "harness.txt").read_text(encoding="utf-8").splitlines()
    assert {"harness/mm_a.py:MAX_X", "harness/mm_b.py:MAX_X"} <= set(lines)
