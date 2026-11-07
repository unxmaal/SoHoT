"""A pull request runs the test files its change can reach through the import graph, plus the repo-wide ratchets. #1567."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

from harness import ci_history
from tests.gauntlet import mutation, scope

REPO = Path(__file__).resolve().parent.parent

TEXTS = {
    "harness/__init__.py": "",
    "harness/leaf.py": "X = 1\n",
    "harness/middle.py": "from harness import leaf\n",
    "harness/other.py": "Y = 2\n",
    "harness/cli.py": "from harness.commands import hold\nfrom harness import other\n",
    "harness/commands/__init__.py": "",
    "harness/commands/hold.py": "from harness import leaf\n",
    "harness/pkg/__init__.py": "",
    "harness/pkg/a.py": "from . import b\n",
    "harness/pkg/b.py": "Z = 3\n",
    "harness/runs.py": "import subprocess\nsubprocess.run(['bash', 'scripts/launchd.sh'])\n",
    "tests/test_leaf.py": "from harness import leaf\n",
    "tests/test_through_middle.py": "from harness.middle import leaf\n",
    "tests/test_other.py": "from harness import other\n",
    "tests/test_verb.py": "from harness import cli\n\ndef test_x():\n    cli.main(['hold', 'status'])\n",
    "tests/test_cli_other.py": "from harness import cli\n\ndef test_x():\n    cli.main(['other'])\n",
    "tests/test_pkg.py": "from harness.pkg import a\n",
    "tests/test_runs.py": "from harness import runs\n",
    "tests/test_launchd_named.py": "SCRIPT = 'launchd.sh'\n",
    "tests/test_dotted.py": "import subprocess\nsubprocess.run(['python', '-m', 'harness.other'])\n",
    "tests/test_knobs.py": "",
}
TESTS = {p for p in TEXTS if scope.is_test(p)}


def _select(*changed):
    return scope.select(list(changed), TEXTS, TESTS)


def test_a_leaf_change_selects_its_importers_tests_and_the_ratchets_not_unrelated_files():
    chosen, why = _select("harness/leaf.py")
    assert "tests/test_leaf.py" in chosen and "tests/test_knobs.py" in chosen
    assert "tests/test_other.py" not in chosen and "tests/test_pkg.py" not in chosen
    assert any(w.strip().startswith("harness/leaf.py:") for w in why)


def test_a_test_reaching_the_changed_module_only_through_another_module_is_selected():
    chosen, _ = _select("harness/leaf.py")
    assert "tests/test_through_middle.py" in chosen
    chosen, _ = _select("harness/pkg/b.py")
    assert "tests/test_pkg.py" in chosen


@pytest.mark.parametrize("path", ["tests/conftest.py", "pyproject.toml", "uv.lock", "Makefile",
                                  ".github/workflows/ci.yml", "harness/conftest.py"])
def test_a_change_to_shared_configuration_selects_everything(path):
    chosen, why = _select("harness/leaf.py", path)
    assert chosen is None and path in why[0]


def test_no_change_and_an_unnamed_file_run_the_full_suite():
    assert _select()[0] is None
    chosen, why = _select("deploy/unheard-of.plist")
    assert chosen is None and "nothing names deploy/unheard-of.plist" in why[0]


def test_a_command_reaches_the_tests_that_call_its_verb_not_every_cli_test():
    chosen, _ = _select("harness/commands/hold.py")
    assert "tests/test_verb.py" in chosen and "tests/test_cli_other.py" not in chosen
    chosen, _ = _select("harness/leaf.py")
    assert "tests/test_verb.py" in chosen and "tests/test_cli_other.py" not in chosen
    chosen, _ = _select("harness/cli.py")
    assert {"tests/test_verb.py", "tests/test_cli_other.py"} <= set(chosen)


def test_a_script_or_module_named_in_a_string_reaches_the_tests_that_name_it():
    chosen, _ = _select("scripts/launchd.sh")
    assert {"tests/test_runs.py", "tests/test_launchd_named.py"} <= set(chosen)
    assert "tests/test_leaf.py" not in chosen
    chosen, _ = _select("harness/other.py")
    assert "tests/test_dotted.py" in chosen


def test_a_changed_test_file_is_selected_and_a_deleted_module_reaches_its_importers():
    chosen, _ = _select("tests/test_other.py")
    assert "tests/test_other.py" in chosen and "tests/test_leaf.py" not in chosen
    texts = dict(TEXTS)
    del texts["harness/leaf.py"]
    chosen, _ = scope.select(["harness/leaf.py"], texts, TESTS)
    assert "tests/test_leaf.py" in chosen


def test_relative_imports_resolve_only_with_their_package_and_absolute_spellings_are_unchanged():
    assert "harness.pkg.b" in mutation.imported("from . import b\n", "harness.pkg")
    assert "harness.b" in mutation.imported("from ..b import c\n", "harness.pkg")
    assert mutation.imported("from . import b\n") == set()
    assert mutation.imports("import harness.router.x\n", "harness/router.py")
    assert not mutation.imports("from harness.routerx import y\n", "harness/router.py")


def test_every_always_on_ratchet_is_a_real_test_file():
    assert [t for t in scope.ALWAYS if not (REPO / t).is_file()] == []


def test_collection_skips_only_repo_test_files_the_listing_leaves_out(tmp_path):
    listing = tmp_path / "selected.txt"
    listing.write_text("tests/test_a.py\n", encoding="utf-8")
    root = tmp_path / "repo"
    assert not scope.ignored(root / "tests" / "test_a.py", root, str(listing))
    assert scope.ignored(root / "tests" / "test_b.py", root, str(listing))
    assert not scope.ignored(root / "tests" / "fakes.py", root, str(listing))
    assert not scope.ignored(tmp_path / "elsewhere" / "test_b.py", root, str(listing))
    assert not scope.ignored(root / "tests" / "test_b.py", root, str(tmp_path / "missing.txt"))


@pytest.mark.parametrize("workers", ["0", "2"])
def test_a_listing_in_the_environment_reaches_every_xdist_worker_and_skips_unlisted_files(tmp_path, workers):
    env = {k: v for k, v in os.environ.items() if k not in ("PYTEST_ADDOPTS", "SOHOT_CATCHES", "SOHOT_TEST_LOG")}
    argv = [sys.executable, "-m", "pytest", "-v", "-p", "no:randomly", "-n", workers, "-k",
            "slowest_tests_are_ranked or ci_history_reads_a_scoped", "tests/"]

    def run(*files):
        listing = tmp_path / f"selected-{len(files)}.txt"
        listing.write_text("".join(f + "\n" for f in files), encoding="utf-8")
        got = subprocess.run(argv, cwd=REPO, env={**env, "SOHOT_SELECTED": str(listing)}, capture_output=True,
                             text=True, timeout=300)
        return got.stdout[-800:]
    one = run("tests/test_ci_history_1520.py")
    assert "1 passed" in one, one
    both = run("tests/test_ci_history_1520.py", "tests/test_scope_1567.py")
    assert "2 passed" in both, both


def test_the_command_writes_the_listing_and_removes_it_for_a_full_run(tmp_path, capsys):
    out = tmp_path / "selected.txt"
    assert scope.main(["--files", "tests/test_scope_1567.py", "--out", str(out)]) == 0
    listed = out.read_text(encoding="utf-8").split()
    printed = capsys.readouterr().out
    assert "tests/test_scope_1567.py" in listed and set(scope.ALWAYS) <= set(listed)
    assert f"selection: {len(listed)} of " in printed
    assert scope.main(["--files", "pyproject.toml", "--out", str(out)]) == 0
    assert not out.exists() and "selection: pyproject.toml changed; full suite" in capsys.readouterr().out


def test_a_replay_weighs_each_merged_prs_selection_by_suite_seconds():
    prs = [{"number": 1, "files": [{"path": "harness/other.py"}]}, {"number": 2, "files": [{"path": "uv.lock"}]}]
    secs = {"tests/test_other.py": 30.0, "tests/test_dotted.py": 10.0, "tests/test_leaf.py": 60.0}
    (n1, chosen, share), (n2, full, all_) = scope.replay(prs, TEXTS, TESTS, (), secs)
    assert n1 == 1 and "tests/test_other.py" in chosen and share == pytest.approx(0.4)
    assert n2 == 2 and full is None and all_ == 1.0


def test_ci_history_reads_a_scoped_pr_run_apart_from_a_full_fallback():
    log = ("2026-11-07T10:00:00.0000000Z   SOHOT_FAST_PATH: 1\n"
           "2026-11-07T10:00:01.0000000Z selection: 42 of 580 test files\n")
    got = ci_history.from_log(log)
    assert got["fast"] and got["selected"] == 42 and ci_history.path(got) == "scoped (PR)"
    fallback = ci_history.from_log(log.replace("selection: 42 of 580 test files", "selection: uv.lock changed"))
    assert fallback["selected"] is None and ci_history.path(fallback) == "fast (PR)"
    rows = [{"fast": True, "tests": {"pr": 9.0}}, {"fast": False, "tests": {"main": 5.0}}]
    assert ci_history.slowest(rows, fast=True) == [("pr", 9.0, 9.0, 1)]
    assert ci_history.slowest(rows) == [("main", 5.0, 5.0, 1)]
