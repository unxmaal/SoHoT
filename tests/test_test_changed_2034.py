"""`make test-changed` runs the tests a branch reaches against origin/main, and the whole suite when a shared file changed. #2034."""
import re
import subprocess
from pathlib import Path

from tests.gauntlet import scope

REPO = Path(__file__).resolve().parent.parent


def _run(monkeypatch, tmp_path, *files):
    out, seen = tmp_path / "selected.txt", {}

    def call(argv, env):
        seen.update(argv=argv, env=env)
        return 7

    monkeypatch.setattr(scope.subprocess, "call", call)
    monkeypatch.setenv("SOHOT_SELECTED", "stale-listing")
    rc = scope.main(["--files", *files, "--out", str(out), "--run", "pytest", "tests/", "-q"])
    return rc, out, seen


def test_a_changed_source_file_runs_only_the_tests_that_reach_it(monkeypatch, tmp_path):
    rc, out, seen = _run(monkeypatch, tmp_path, "harness/ci_rerun.py")
    listed = out.read_text(encoding="utf-8").split()
    assert rc == 7 and seen["argv"] == ["pytest", "tests/", "-q"]
    assert seen["env"]["SOHOT_SELECTED"] == str(out)
    assert "tests/test_ci_rerun_1520.py" in listed and "tests/test_scope_1567.py" not in listed


def test_a_conftest_change_runs_the_full_suite(monkeypatch, tmp_path):
    out = tmp_path / "selected.txt"
    out.write_text("tests/test_ci_rerun_1520.py\n", encoding="utf-8")
    rc, out, seen = _run(monkeypatch, tmp_path, "tests/conftest.py")
    assert rc == 7 and not out.exists()
    assert "SOHOT_SELECTED" not in seen["env"]


def test_the_make_target_selects_against_origin_main_and_runs_the_suite_on_it():
    text = (REPO / "Makefile").read_text(encoding="utf-8")
    recipe = re.search(r"^test-changed:.*\n((?:\t.*\n)+)", text, re.M)
    assert recipe, "Makefile has no test-changed target"
    body = recipe.group(1)
    assert "tests.gauntlet.scope --base origin/main" in body and "--run" in body
    assert "pytest tests/" in body and "$(PYTEST_N)" in body


def test_a_branch_change_counts_whether_committed_edited_or_new(tmp_path):
    def git(*argv):
        subprocess.run(["git", *argv], cwd=tmp_path, check=True, capture_output=True)

    git("init", "-q", "-b", "main")
    for name in ("committed.py", "edited.py", "same.py"):
        (tmp_path / name).write_text("X = 1\n", encoding="utf-8")
    git("add", ".")
    git("-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-qm", "base")
    git("checkout", "-qb", "work")
    (tmp_path / "committed.py").write_text("X = 2\n", encoding="utf-8")
    git("-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-qam", "work")
    (tmp_path / "edited.py").write_text("X = 3\n", encoding="utf-8")
    (tmp_path / "new.py").write_text("Y = 1\n", encoding="utf-8")
    assert sorted(scope.changed_since("main", tmp_path)) == ["committed.py", "edited.py", "new.py"]
