"""A yield-stopped repo row is classed, its run's stop point is reported, and no runner class falls to unclassed. #1170."""
import json

import pytest

from evals.analysis import repo_failures as F
from harness import reasons
from tests.test_repo_causes_1128 import _run

STOP = "stopped after 100 generated tokens, its yield stop point: tasks still running there rarely pass"


def _rows(tmp_path, receipt):
    d = tmp_path / "r"
    d.mkdir()
    rows = [
        {"case_id": "s1", "candidate": "org/x", "passed": False, "failure_class": "stopped_low_yield",
         "detail": STOP, "limit": "yield_stop>100", "metrics": {"resolved": 0}},
        {"case_id": "s2", "candidate": "org/x", "passed": False, "failure_class": "stopped_low_yield",
         "detail": STOP, "limit": "yield_stop>100", "metrics": {"resolved": 0, "completion_tokens": 104}},
        {"case_id": "early", "candidate": "org/x", "passed": True, "failure_class": "",
         "metrics": {"completion_tokens": 60}},
        {"case_id": "past-pass", "candidate": "org/x", "passed": True, "failure_class": "",
         "metrics": {"completion_tokens": 150}},
        {"case_id": "past-cut", "candidate": "org/x", "passed": False, "failure_class": "token_budget_exhausted",
         "limit": "max_tokens.repo>400", "metrics": {}},
        {"case_id": "other", "candidate": "org/y", "passed": False, "failure_class": "invalid_patch",
         "metrics": {"completion_tokens": 900}},
    ]
    (d / "results.json").write_text(json.dumps({"receipt": receipt, "rows": rows}), encoding="utf-8")
    return d


@pytest.mark.parametrize("fc", sorted(reasons.CLASSES))
def test_every_runner_class_maps_to_a_cause(fc):
    got = F.cause({"failure_class": fc, "detail": ""}, {})
    assert got in F.CAUSES and got != "unclassed"


def test_a_yield_stopped_row_is_its_own_cause_and_counts_as_cut(tmp_path):
    run = F.load_run(_run(tmp_path, "r", {"s": ("stopped_low_yield", STOP, None, None, 10, 100),
                                           "p": ("", "", "ok", "", 10, 50)}))
    rows = F.causes(run, {})
    assert [r["cause"] for r in rows] == ["stopped_low_yield", "pass"]
    table = F.cause_table(rows)
    assert "| cut % | 50 |" in table and "| median completion, uncut | 50 |" in table


def test_the_stop_point_and_the_explored_rows_past_it_are_reported(tmp_path):
    run = F.load_run(_rows(tmp_path, {"yield_stop": {"org/x": {"tokens": 100, "explored": ["early", "past-pass",
                                                                                          "past-cut"]}}}))
    assert F.yield_stops(run) == [{"candidate": "org/x", "tokens": 100, "stopped": 2, "explored": 3,
                                   "past": 2, "passed_past": 1}]


def test_without_a_receipt_the_stop_point_is_read_off_the_rows(tmp_path):
    run = F.load_run(_rows(tmp_path, {}))
    assert F.yield_stops(run) == [{"candidate": "org/x", "tokens": 100, "stopped": 2, "explored": None,
                                   "past": 2, "passed_past": 1}]


def test_the_command_prints_the_stop_line(tmp_path, capsys):
    d = _rows(tmp_path, {"yield_stop": {"org/x": {"tokens": 100, "explored": ["past-pass", "past-cut"]}}})
    assert F.main(["causes", str(d)]) == 0
    assert ("yield stop org/x: 100 tokens, 2 row(s) stopped there; 2 explored, 2 ran past it, 1 of them passed"
            in capsys.readouterr().out)
