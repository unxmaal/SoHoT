"""A documentation hunk that does not apply is left out when no test names the file; the rest is graded. #1107."""
import json

import pytest

from evals import repo
from harness import reasons
from tests.test_repo_lane import BASE_FILES, BUGGY, DARWIN, FIXED, HIDDEN, _diff, _here, _two_commits, runner_with

README = "# pkg\n\nadd() adds.\n"
#: A README hunk whose context base does not have, as at infovore-327-spec and sohot-371-spec.
STALE_README = _diff("# pkg\n\nOld words.\n", "# pkg\n\nNew words.\n", "README.md")
CODE = _diff(BUGGY, FIXED)


def _case(tmp_path, hidden=HIDDEN):
    tmp_path.mkdir(parents=True, exist_ok=True)
    return _two_commits(tmp_path / "upstream", {**BASE_FILES, "README.md": README},
                        {"pkg/mod.py": FIXED, "tests/test_mod.py": hidden})


@DARWIN
def test_code_that_applies_beside_a_readme_that_does_not_is_graded_on_the_code(tmp_path):
    row = runner_with(f"```diff\n{CODE}{STALE_README}```").run(_case(tmp_path))
    assert (row.passed, row.failure_class) == (True, "")
    assert [w.split(":")[:2] for w in row.warnings] == [[repo.DOC_HUNK_SKIPPED, " README.md"]]
    skipped = json.loads(row.output)["grade"]["skipped"]
    assert [s["path"] for s in skipped] == ["README.md"] and "README.md" in skipped[0]["why"]


def test_the_code_is_applied_and_the_readme_left_as_base_had_it(tmp_path):
    a = repo.Attempt.open(_case(tmp_path).params, env=_here)
    try:
        applied, why, skipped = repo.apply_docs_aside(a.task, CODE + STALE_README, lambda p: False)
        assert (applied, why, [s["path"] for s in skipped]) == (True, "", ["README.md"])
        assert (a.task / "pkg" / "mod.py").read_text(encoding="utf-8") == FIXED
        assert (a.task / "README.md").read_text(encoding="utf-8") == README
    finally:
        a.close()


def test_a_source_hunk_that_does_not_apply_stays_invalid_patch(tmp_path):
    bad = _diff("def nothing():\n    pass\n", "def nothing():\n    return 1\n", "pkg/other.py")
    for diff in (CODE + bad + STALE_README, bad + _diff(README, README + "More.\n", "README.md")):
        row = runner_with(f"```diff\n{diff}```").run(_case(tmp_path / str(len(diff))))
        assert (row.passed, row.failure_class, row.warnings) == (False, reasons.INVALID_PATCH, [])


READS = "def test_readme():\n    assert open('README.md').read()\n"


@pytest.mark.parametrize("where", ["tests/test_mod.py", "tests/conftest.py", "conftest.py"])
def test_a_readme_a_graded_test_or_its_conftest_reads_stays_invalid_patch(tmp_path, where):
    hidden = HIDDEN + "\n\n" + READS if where == "tests/test_mod.py" else HIDDEN
    base = {**BASE_FILES, "README.md": README, **({} if where == "tests/test_mod.py" else {where: READS})}
    case = _two_commits(tmp_path / "upstream", base, {"pkg/mod.py": FIXED, "tests/test_mod.py": hidden})
    p = case.params
    assert repo.named_by_tests(repo.mirror(p["source_repo"]), p["base"], p["fix"], "README.md", p["fail_to_pass"])
    row = runner_with(f"```diff\n{CODE}{STALE_README}```").run(case)
    assert (row.passed, row.failure_class, row.warnings) == (False, reasons.INVALID_PATCH, [])
    assert "README.md" in row.detail


def test_a_readme_only_a_test_the_grader_does_not_run_names_is_still_left_out(tmp_path):
    case = _two_commits(tmp_path / "upstream", {**BASE_FILES, "README.md": README, "tests/test_docs.py": READS},
                        {"pkg/mod.py": FIXED, "tests/test_mod.py": HIDDEN})
    p = case.params
    assert not repo.named_by_tests(repo.mirror(p["source_repo"]), p["base"], p["fix"], "README.md",
                                   [*p["fail_to_pass"], *p["pass_to_pass"]])


def test_a_diff_of_nothing_but_a_failed_readme_stays_invalid_patch(tmp_path):
    row = runner_with(f"```diff\n{STALE_README}```").run(_case(tmp_path))
    assert (row.passed, row.failure_class) == (False, reasons.INVALID_PATCH)


def test_the_patterns_are_the_knob_read_when_the_answer_is_graded(tmp_path, monkeypatch):
    monkeypatch.setattr(repo, "DOC_PATTERNS", ())
    row = runner_with(f"```diff\n{CODE}{STALE_README}```").run(_case(tmp_path))
    assert (row.passed, row.failure_class) == (False, reasons.INVALID_PATCH)
    from harness import knobs
    assert knobs.KNOBS["repo_doc_patterns"].default() == ()


@pytest.mark.parametrize("path,doc", [("README.md", True), ("pkg/notes.md", True), ("docs/api.txt", True),
                                      ("CHANGELOG", True), ("sub/CHANGELOG.txt", True), ("docs/conf.py", False),
                                      ("tests/README.md", False), ("pkg/mod.py", False), ("pkg/docs/x.txt", False)])
def test_a_documentation_file_is_one_the_patterns_name_and_never_source_or_test(path, doc):
    assert repo.is_doc(path) is doc
