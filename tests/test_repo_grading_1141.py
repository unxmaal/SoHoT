"""The repo grader runs every named id it can, keeps pytest's failure text, and one bad id or file voids nothing. #1141."""
from evals import repo
from tests.test_repo_lane import BASE_FILES, BUGGY, FIXED, HIDDEN, _diff, _here, _two_commits

REG = "def _requeue_gold():\n    pass\n"
REG_TESTS = ("import pytest\nfrom pkg import reg\n\n\n"
             "@pytest.mark.parametrize('fn', sorted(n for n in dir(reg) if n.startswith('_requeue_')))\n"
             "def test_each(fn):\n    getattr(reg, fn)()\n")
GOLD_ID = "tests/test_reg.py::test_each[_requeue_gold]"
ADD_ID = "tests/test_mod.py::test_add_hidden_marker"


def _case(tmp_path, **params):
    base = {**BASE_FILES, "pkg/reg.py": ""}
    fix = {"pkg/mod.py": FIXED, "tests/test_mod.py": HIDDEN, "pkg/reg.py": REG, "tests/test_reg.py": REG_TESTS}
    return _two_commits(tmp_path / "upstream", base, fix, fail_to_pass=[ADD_ID, GOLD_ID], **params)


def _submit(case, diff):
    a = repo.Attempt.open(case.params, env=_here)
    try:
        return a.submit(diff)
    finally:
        a.close()


def test_an_id_built_from_the_golds_names_fails_alone_when_the_fix_names_it_otherwise(tmp_path):
    case = _case(tmp_path)
    other = _diff(BUGGY, FIXED) + _diff("", "def _requeue_other():\n    pass\n", path="pkg/reg.py")
    got = _submit(case, other)
    assert got.patch_applied and not got.resolved
    assert got.failed == [GOLD_ID]
    assert got.detail == f"fail_to_pass still failing: {GOLD_ID}"
    assert got.failures == {GOLD_ID: "missing: the test did not run"}


def test_the_gold_names_resolve_through_the_same_grader(tmp_path):
    case = _case(tmp_path)
    assert _submit(case, _diff(BUGGY, FIXED) + _diff("", REG, path="pkg/reg.py")).resolved


def test_a_failing_assertion_keeps_its_text(tmp_path):
    got = _submit(_case(tmp_path), _diff("", REG, path="pkg/reg.py"))
    assert got.failed == [ADD_ID]
    assert "assert 0 == 4" in got.failures[ADD_ID]


def test_a_test_file_that_no_longer_collects_breaks_only_its_own_ids(tmp_path):
    extra = "def mul(a, b):\n    return a * b\n"
    base = {**BASE_FILES, "pkg/extra.py": extra,
            "tests/test_other.py": "from pkg.extra import mul\n\n\ndef test_mul():\n    assert mul(2, 3) == 6\n"}
    case = _two_commits(tmp_path / "upstream", base, {"pkg/mod.py": FIXED, "tests/test_mod.py": HIDDEN},
                        pass_to_pass=["tests/test_mod.py::test_sub", "tests/test_other.py::test_mul"])
    got = _submit(case, _diff(BUGGY, FIXED) + _diff(extra, "", path="pkg/extra.py"))
    assert got.failed == ["tests/test_other.py::test_mul"]
    assert got.detail == "pass_to_pass broken: tests/test_other.py::test_mul"
