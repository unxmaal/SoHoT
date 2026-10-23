"""A wrong_fix label says why the row failed, cites the regrade's kept test output, and two labellers compare on it. #1141."""
import json

import pytest

from evals.analysis import repo_failures as F
from tests.test_repo_failures_921 import _write, run_dir  # noqa: F401

TEST = "tests/test_x.py::test_y"
OUTPUT = "    assert got == want\nE   AssertionError: assert 'queued' == 'declined'"


def _regrade(run_dir, resolved=False):
    return {"run": run_dir.name, "file": "org_x--e.json", "case": "e", "resolved": resolved, "patch_applied": True,
            "detail": "" if resolved else f"fail_to_pass still failing: {TEST}",
            "failures": {} if resolved else {TEST: OUTPUT}}


def _graded(run_dir, grading="pinned_detail", **kw):
    at = OUTPUT.index("AssertionError")
    return {"run": run_dir.name, "case": "e", "class": "wrong_fix", "file": "org_x--e.json", "regrade": True,
            "test": TEST, "offset": at, "excerpt": "AssertionError: assert 'queued'", "grading": grading, **kw}


def test_a_label_citing_a_test_is_checked_in_that_tests_kept_output(run_dir):
    regrades = F.load_regrades(_write(run_dir.parent / "r.jsonl", [_regrade(run_dir)]))
    assert F.check_excerpt(run_dir, _graded(run_dir), regrades) == ""
    assert "not the cited excerpt" in F.check_excerpt(run_dir, _graded(run_dir, offset=0), regrades)
    assert "kept no failure text" in F.check_excerpt(run_dir, _graded(run_dir, test="tests/other.py::t"), regrades)


@pytest.mark.gauntlet("a-closed-table-fronting-an-open-set", site="evals/analysis/repo_failures.py:GRADINGS")
@pytest.mark.parametrize("bad", [{"grading": "harsh"}, {"class": "regression"}])
def test_a_grading_off_the_codebook_or_off_wrong_fix_is_refused(run_dir, bad):
    path = _write(run_dir.parent / "l.jsonl", [{**_graded(run_dir), **bad}])
    with pytest.raises(ValueError, match="grading"):
        F.load_labels(path)


def test_a_resolved_regrade_keeps_a_label_only_to_say_the_grade_was_unfair(run_dir, capsys):
    regrades = _write(run_dir.parent / "r.jsonl", [_regrade(run_dir, resolved=True)])
    (at,) = F.locate(run_dir / "org_x--c.json", "<tool_call>")
    plain = {**_graded(run_dir), "regrade": False, "file": "org_x--c.json", "offset": at, "excerpt": "<tool_call>"}
    plain.pop("test")
    unfair = _write(run_dir.parent / "u.jsonl", [plain])
    assert F.main(["tally", str(run_dir), "--labels", str(unfair), "--regrades", str(regrades)]) == 0
    assert "wrong_fix graded: pinned_detail 1 (case)" in capsys.readouterr().out
    model = _write(run_dir.parent / "m.jsonl", [{**plain, "grading": "genuine"}])
    assert F.main(["tally", str(run_dir), "--labels", str(model), "--regrades", str(regrades)]) == 1
    assert "its regrade resolved" in capsys.readouterr().err


def test_kappa_compares_gradings_when_asked(run_dir, capsys):
    a = [_graded(run_dir), {**_graded(run_dir), "case": "f"}]
    b = [a[0], {**a[1], "grading": "genuine"}]
    assert F.kappa(a, b, "grading") == (0.0, 2)
    assert F.disagreements(a, b, "grading") == [(run_dir.name, "f", "pinned_detail", "genuine")]
    pa, pb = _write(run_dir.parent / "a.jsonl", a), _write(run_dir.parent / "b.jsonl", b)
    assert F.main(["kappa", str(pa), str(pb), "--key", "grading"]) == 0
    assert "f: pinned_detail / genuine" in capsys.readouterr().out


def test_every_grading_has_a_definition_and_an_owner(capsys):
    assert set(F.GRADINGS) == set(F.GRADING_DEFINITIONS)
    assert set(F.GRADINGS.values()) <= {"case", "harness", "model"}
    F.main(["codebook"])
    out = capsys.readouterr().out
    assert all(f"{g} ({F.GRADINGS[g]}): {F.GRADING_DEFINITIONS[g]}" in out for g in F.GRADINGS)


def test_every_committed_grading_cites_kept_output_of_a_regrade():
    regrades = F.load_regrades()
    graded = [x for x in F.load_labels() if "grading" in x]
    assert graded
    for x in graded:
        g = regrades.get((x["run"], x["case"]))
        assert g is not None, f"{x['run']} {x['case']}: graded without a regrade"
        assert g["resolved"] or x.get("test") in (g.get("failures") or {}), f"{x['case']}: cites no kept output"
    assert json.dumps(graded)
