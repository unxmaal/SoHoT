"""A multi-file diff without `diff --git` lines applies under --recount. #940."""
import re
import subprocess
from pathlib import Path

import pytest

from evals import repo
from evals.core import load_cases

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "repo_recount_940"
#: Opus 5.5's stored diffs from run 467, each graded invalid_patch "patch failed" before #940.
REAL = sorted(p.stem for p in FIXTURES.glob("*.diff"))

TWO_FILES = ("--- a/x\n+++ b/x\n@@ -1,3 +1,3 @@\n a\n-b\n+B\n c\n"
             "--- a/y\n+++ b/y\n@@ -1,3 +1,3 @@\n p\n-q\n+Q\n r\n")


def _repo(path: Path, files: dict) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    for rel, text in files.items():
        (path / rel).parent.mkdir(parents=True, exist_ok=True)
        (path / rel).write_bytes(text.encode("utf-8"))
    run = lambda *a: subprocess.run(["git", *a], cwd=path, check=True, capture_output=True)  # noqa: E731
    run("init", "-q")
    run("add", "-A")
    run("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "base", "--allow-empty")
    return path


def _text(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def test_the_issue_two_file_diff_applies(tmp_path):
    task = _repo(tmp_path, {"x": "a\nb\nc\n", "y": "p\nq\nr\n"})
    assert repo.apply(task, TWO_FILES) == (True, "")
    assert (_text(task / "x"), _text(task / "y")) == ("a\nB\nc\n", "p\nQ\nr\n")


def test_a_created_file_before_a_changed_one_applies(tmp_path):
    task = _repo(tmp_path, {"x": "a\nb\nc\n"})
    diff = "--- /dev/null\n+++ b/n/new.py\n@@ -0,0 +1 @@\n+x\n" + TWO_FILES.split("--- a/y")[0]
    assert repo.apply(task, diff) == (True, "")
    assert (_text(task / "n" / "new.py"), _text(task / "x")) == ("x\n", "a\nB\nc\n")


def test_a_deleted_file_applies(tmp_path):
    task = _repo(tmp_path, {"x": "a\nb\nc\n", "y": "p\nq\nr\n"})
    diff = "--- a/y\n+++ /dev/null\n@@ -1,3 +0,0 @@\n-p\n-q\n-r\n" + TWO_FILES.split("--- a/y")[0]
    assert repo.apply(task, diff) == (True, "")
    assert not (task / "y").exists()


def test_a_git_diff_is_left_as_git_wrote_it():
    git = ("diff --git a/x b/x\nindex 1111111..2222222 100644\n--- a/x\n+++ b/x\n@@ -1 +1 @@\n-a\n+b\n"
           "diff --git a/y b/y\nold mode 100644\nnew mode 100755\n")
    assert repo.with_git_headers(git) == git


def test_only_a_header_without_its_own_git_line_gets_one():
    mixed = ("diff --git a/w b/w\n--- a/w\n+++ b/w\n@@ -1 +1 @@\n-1\n+2\n"
             "diff --git a/x b/x\nold mode 100644\nnew mode 100755\nindex 1111111..2222222\n" + TWO_FILES)
    out = repo.with_git_headers(mixed)
    assert re.findall(r"^diff --git .*$", out, re.M) == ["diff --git a/w b/w", "diff --git a/x b/x",
                                                         "diff --git a/y b/y"]


def test_removed_and_added_lines_that_look_like_headers_inside_a_hunk_are_not_headers():
    body = "--- a/x\n+++ b/x\n@@ -1,3 +1,3 @@\n a\n--- a/q\n+++ b/q\n c\n"
    assert repo.with_git_headers(body).count("diff --git") == 1


@pytest.mark.parametrize("case", REAL)
def test_the_pilot_diffs_apply_to_their_base(case, tmp_path):
    params = next(c.params for c in load_cases(ROOT / "evals" / "cases" / "repo") if c.id == case)
    diff = (FIXTURES / f"{case}.diff").read_bytes().decode("utf-8")
    paths = sorted(set(re.findall(r"^\+\+\+ b/(\S+)", diff, re.M)))
    got = subprocess.run(["git", "-C", str(ROOT), "cat-file", "-e", f"{params['base']}^{{commit}}"],
                         capture_output=True)
    if got.returncode:
        pytest.skip("a shallow checkout lacks the base commit; CI fetches full history")
    files = {p: subprocess.run(["git", "-C", str(ROOT), "show", f"{params['base']}:{p}"], check=True,
                               capture_output=True).stdout.decode("utf-8") for p in paths}
    task = _repo(tmp_path / "task", files)
    assert len(paths) >= 2 and "diff --git" not in diff
    assert repo.apply(task, diff) == (True, "")
    assert subprocess.run(["git", "diff", "--name-only"], cwd=task, capture_output=True,
                          text=True).stdout.split() == paths
