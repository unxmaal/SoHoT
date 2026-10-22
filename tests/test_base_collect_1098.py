"""A fail-to-pass file that cannot collect at base because it imports the fix's new symbol is a failing test. #1098."""
import subprocess
import sys

import pytest

from evals import repo
from evals.importers import history
from tests.test_history_sources_889 import FIXED, ISSUE, MERGES, _commit, _git, _merged
from tests.test_history_sources_889 import ADD_TEST, DARWIN, _here
from tests.test_repo_lane import BASE_FILES, _two_commits
from tests.test_repo_lane import FIXED as PKG_FIXED

TREE = {"pytest.ini": "[pytest]\npythonpath = .\n", "pkg/__init__.py": "", "pkg/m.py": "def a():\n    pass\n",
        "tests/test_name.py": "from pkg.m import b\n\ndef test_x():\n    pass\n",
        "tests/test_newmod.py": "from pkg.new import b\n\ndef test_x():\n    pass\n",
        "tests/test_attr.py": "import pkg.m\nX = pkg.m.b\n\ndef test_x():\n    pass\n",
        "tests/test_third.py": "import notinstalled_1098\n\ndef test_x():\n    pass\n",
        "tests/test_syn.py": "def test_x(:\n    pass\n",
        "tests/sub/conftest.py": "import notinstalled_1098\n",
        "tests/sub/test_c.py": "def test_y():\n    pass\n"}


def test_each_collection_error_pytest_writes_is_judged_against_the_reference_checkout(tmp_path):
    for rel, text in TREE.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text, encoding="utf-8")
    xml = tmp_path / "r.xml"
    subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-o", "addopts=",
                    "--continue-on-collection-errors", f"--junitxml={xml}", "tests"], cwd=tmp_path,
                   capture_output=True, timeout=120)
    broken = repo.collect_errors(xml)
    assert {k: repo.collect_cause(e, tmp_path) for k, e in broken.items()} == {
        "tests/test_name": "repo_symbol", "tests/test_attr": "repo_symbol",
        "tests/test_newmod": "third_party_module", "tests/test_third": "third_party_module",
        "tests/test_syn": "syntax_error", "tests/sub": "conftest"}
    (tmp_path / "pkg/new.py").write_text("b = 1\n", encoding="utf-8")
    assert repo.collect_cause(broken["tests/test_newmod"], tmp_path) == "repo_symbol"
    assert repo.broken_key("tests/sub/test_c.py", broken) == "tests/sub"


H = "tests/test_mod.py::"
REF = [{"ids": {H + "f": "passed", H + "p": "passed"}, "error": ""}]


def _base(f="error", p="passed", cause=None):
    return [{"ids": {H + "f": f, H + "p": p}, "error": ""}], {"tests/test_mod": cause} if cause else {}


@pytest.mark.parametrize("f, p, cause, want", [
    ("error", "passed", "repo_symbol", "valid"),
    ("error", "passed", "third_party_module", "error: base: did not collect or set up: " + H + "f (third_party_module)"),
    ("error", "passed", "conftest", "(conftest)"),
    ("error", "passed", None, H + "f (setup)"),
    ("error", "error", "repo_symbol", H + "p (repo_symbol)"),
])
def test_only_a_fail_to_pass_id_whose_file_needs_a_repo_symbol_counts_as_failing_at_base(f, p, cause, want):
    base, causes = _base(f, p, cause)
    got = repo.verdict(base, REF, [H + "f"], [H + "p"], causes)
    assert (got == want) if want == "valid" else (want in got), got


def test_an_admitted_id_must_still_pass_with_the_reference():
    base, causes = _base(cause="repo_symbol")
    got = repo.verdict(base, [{"ids": {H + "f": "error", H + "p": "passed"}, "error": ""}],
                       [H + "f"], [H + "p"], causes)
    assert got == "invalid: reference fails: " + H + "f (error)"


def _survey_runs(module: str):
    base = [{"outcomes": {"::tests.test_mod": "error"}, "seconds": 1,
             "collect": {"tests/test_mod": {"kind": "import", "module": module}}}] * 2
    fix = [{"outcomes": {"tests.test_mod::test_sub": "passed", "tests.test_mod::test_add": "passed"},
            "seconds": 1, "collect": {}}] * 2
    return base, fix


def test_the_survey_keeps_a_repo_symbol_and_drops_a_third_party_module_with_its_cause(tmp_path):
    (tmp_path / "mod.py").write_text("", encoding="utf-8")
    files = ["tests/test_mod.py"]
    got = history.classify(*_survey_runs("mod"), files, tmp_path)
    assert got["admitted_by"] == "base_collect_repo_symbol" and got["fail_to_pass"] == [
        "tests/test_mod.py::test_add", "tests/test_mod.py::test_sub"]
    assert history.classify(*_survey_runs("yaml_1098"), files, tmp_path) == {
        "drop": "base_error", "cause": "third_party_module"}


def _merge_fix(src, files: dict):
    _git(src, "checkout", "-q", "-b", "feat/9-mul")
    _commit(src, files, "mul")
    _git(src, "checkout", "-q", "main")
    _git(src, "merge", "-q", "--no-ff", "-m", "Merge pull request #10 from someone/feat/9-mul", "feat/9-mul")


MUL_TEST = "from mod import add, sub, mul\n" + ADD_TEST.split("\n", 1)[1] + "\ndef test_mul():\n    assert mul(2, 3) == 6\n"


@DARWIN
def test_a_fix_whose_test_imports_its_new_symbol_is_kept_and_says_which_rule_admitted_it(tmp_path):
    src = _merged(tmp_path)
    _merge_fix(src, {"mod.py": FIXED + "\ndef mul(a, b):\n    return a * b\n", "tests/test_mod.py": MUL_TEST})
    got = history.survey(str(src), "main", None, tmp_path / "log.txt", get_issue=lambda n: ISSUE, env=_here,
                         src=MERGES)
    assert sorted(t["issue"] for t in got["tasks"]) == [7, 9] and got["dropped"] == {}
    mul = next(t for t in got["tasks"] if t["issue"] == 9)
    assert mul["admitted_by"] == "base_collect_repo_symbol" and "tests/test_mod.py::test_mul" in mul["fail_to_pass"]


@DARWIN
def test_a_file_that_does_not_collect_leaves_the_other_files_tests_in_pass_to_pass(tmp_path):
    src = _merged(tmp_path)
    _merge_fix(src, {"mod.py": FIXED + "\ndef mul(a, b):\n    return a * b\n",
                     "tests/test_mul.py": "from mod import mul\n\ndef test_mul():\n    assert mul(2, 3) == 6\n",
                     "tests/test_mod.py": ADD_TEST + "\ndef test_sub_again():\n    assert True\n"})
    got = history.survey(str(src), "main", None, tmp_path / "log.txt", get_issue=lambda n: ISSUE, env=_here,
                         src=MERGES)
    mul = next(t for t in got["tasks"] if t["issue"] == 9)
    assert mul["fail_to_pass"] == ["tests/test_mul.py::test_mul"]
    assert mul["pass_to_pass"] == ["tests/test_mod.py::test_add", "tests/test_mod.py::test_sub",
                                   "tests/test_mod.py::test_sub_again"]


@DARWIN
def test_a_reference_that_does_not_make_the_file_collect_is_dropped(tmp_path):
    src = _merged(tmp_path)
    _merge_fix(src, {"mod.py": FIXED + "\ndef times(a, b):\n    return a * b\n", "tests/test_mod.py": MUL_TEST})
    got = history.survey(str(src), "main", None, tmp_path / "log.txt", get_issue=lambda n: ISSUE, env=_here,
                         src=MERGES)
    assert [t["issue"] for t in got["tasks"]] == [7] and got["dropped"] == {"reference_fails": 1}


MUL = "from pkg.mod import mul\n\n\ndef test_add_hidden_marker():\n    assert mul(2, 3) == 6\n\n\n"


@DARWIN
@pytest.mark.parametrize("fix, test, want", [
    (PKG_FIXED + "\n\ndef mul(a, b):\n    return a * b\n", MUL, "valid"),
    (PKG_FIXED, "import notinstalled_1098\n" + MUL, "(third_party_module)"),
    (PKG_FIXED, MUL, "invalid: reference fails: tests/test_mod.py::test_add_hidden_marker (error)"),
])
def test_the_case_control_admits_only_a_collection_error_the_reference_resolves(tmp_path, fix, test, want):
    case = _two_commits(tmp_path / "upstream", {**BASE_FILES, "tests/test_mod.py": "def test_sub():\n    pass\n"},
                        {"pkg/mod.py": fix, "tests/test_mod.py": test + "def test_sub():\n    pass\n"},
                        fail_to_pass=[f"tests/test_mod.py::{n}" for n in ("test_add_hidden_marker", "test_sub")],
                        pass_to_pass=[])
    got = repo.controls(case, env=_here)
    assert (got["verdict"] == want) if want == "valid" else (want in got["verdict"]), got["verdict"]
    assert got.get("admitted_by") == ("base_collect_repo_symbol" if want == "valid" else None)
