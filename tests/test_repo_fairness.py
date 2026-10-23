"""Repo-case fairness labels: two labellers per case on two axes, Cohen's kappa, flagged cases dropped. #920."""
import json
from pathlib import Path

import pytest

from evals import fairness
from evals.core import load_cases
from evals.importers import history

ROOT = Path(__file__).resolve().parents[1]


def _labels(**cases):
    return {"labellers": ["A", "B"], "labels": cases}


def _pair(a, b, why="a detail the issue never asks for"):
    return {"A": {"spec": a[0], "tests": a[1], "why": {"spec": why, "tests": why}},
            "B": {"spec": b[0], "tests": b[1], "why": {"spec": why, "tests": why}}}


def test_kappa_matches_a_hand_computed_value():
    assert fairness.kappa([0, 0, 1, 1], [0, 1, 1, 1]) == pytest.approx(0.5)
    assert fairness.kappa([2, 1, 0], [2, 1, 0]) == pytest.approx(1.0)
    assert fairness.kappa([0, 0], [0, 0]) is None
    with pytest.raises(ValueError):
        fairness.kappa([0], [0, 1])


def test_both_labellers_flagging_an_axis_flags_the_case_and_one_disputes_it():
    got = fairness.summary(_labels(x=_pair((0, 2), (1, 3)), y=_pair((2, 0), (0, 0)), z=_pair((0, 0), (0, 1))),
                           ["x", "y", "z"])
    assert got["flagged"] == {"x": ["tests"]} and got["disputed"] == {"y": ["spec"]}


def test_a_settled_score_decides_a_disputed_axis():
    labels = {**_labels(y=_pair((2, 0), (0, 0)), w=_pair((0, 2), (0, 0))), "settled": {"y": {"spec": 1}, "w": {"tests": 3}}}
    got = fairness.summary(labels, ["y", "w"])
    assert got["disputed"] == {} and got["flagged"] == {"w": ["tests"]}


def test_a_missing_label_an_off_scale_score_and_an_unexplained_flag_are_named():
    bad = _labels(x={"A": {"spec": 0, "tests": 4}, "B": {"spec": 2, "tests": 0, "why": {}}})
    wrong = fairness.check(bad, ["x", "y"])
    assert any("A tests score 4" in w for w in wrong)
    assert any("B scored spec 2 with no reason" in w for w in wrong)
    assert any("y: no label from A" in w for w in wrong) and any("y: no label from B" in w for w in wrong)


def test_every_committed_repo_case_has_two_valid_labels():
    cases = load_cases(ROOT / "evals" / "cases" / "repo")
    assert fairness.check(fairness.load(), [c.id for c in cases]) == []


def test_unfair_cases_stay_committed_and_only_validity_failures_are_dropped():
    """Eric on #944: keep and tag. A flagged or disputed case stays, outside the fair subset. #920."""
    cases = [c.id for c in load_cases(ROOT / "evals" / "cases" / "repo")]
    labels = fairness.load()
    got = fairness.summary(labels, cases)
    assert got["flagged"] and set(got["flagged"]) <= set(cases)
    assert all(why.startswith("validation") for why in history.DROPPED.values())
    fair = fairness.fair(labels, cases)
    assert not fair & (set(got["flagged"]) | set(got["disputed"]))
    assert "sohot-642-symptom" in got["disputed"] and "sohot-642-symptom" not in fair


def test_a_disputed_axis_is_unfair_until_settled():
    labels = _labels(y=_pair((0, 2), (0, 1)), z=_pair((1, 1), (0, 0)))
    assert fairness.fair(labels, ["y", "z"]) == {"z"}
    assert fairness.fair({**labels, "settled": {"y": {"tests": 1}}}, ["y", "z"]) == {"y", "z"}
    assert fairness.fair(labels, ["unlabelled"]) == set()


def test_soh_cases_labels_repo_reports_kappa(tmp_path, capsys):
    from harness import cli
    (tmp_path / "repo").mkdir()
    case = {"id": "x", "modality": "repo", "prompt": "p",
            "params": {"source_repo": "s", "base": "a" * 40, "fix": "b" * 40, "variant": "spec",
                       "context": "oracle", "context_files": ["m.py"], "fail_to_pass": ["tests/t.py::t"]}}
    import yaml
    (tmp_path / "repo" / "x.yaml").write_text(yaml.safe_dump(case), encoding="utf-8")
    (tmp_path / "repo" / "labels.json").write_text(json.dumps(_labels(x=_pair((0, 2), (0, 3)))),
                                                   encoding="utf-8")
    assert cli.main(["cases", "labels", "repo", "--out", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "kappa spec: undefined" in out and "flagged x: tests" in out


def test_a_dropped_case_is_not_imported_and_the_committed_cases_follow_the_drop_list(monkeypatch):
    committed = {c.id for c in load_cases(ROOT / "evals" / "cases" / "repo" / "history")}
    assert committed == {f"{r['id']}-{r['variant']}" for r in history.fetch()}
    first = sorted(committed)[0]
    monkeypatch.setitem(history.DROPPED, first, "both labellers flagged tests")
    assert first not in {f"{r['id']}-{r['variant']}" for r in history.fetch()}
